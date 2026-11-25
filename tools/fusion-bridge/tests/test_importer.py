"""Runs the f540x importer against a mock Fusion session (no Fusion needed).

    python -m unittest discover -s tools/fusion-bridge/tests

The mock answers like the Fusion API is documented to; it catches wrong call shapes,
wrong reference matching and wrong bookkeeping, not Fusion disagreeing with its own
documentation. That is only settled by running the add-in in Fusion.
"""

import json
import math
import os
import sys
import tempfile
import types
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "Fission540Bridge"))
sys.path.insert(0, HERE)

import fusion_mock  # noqa: E402

fusion_mock.install()

from f540x import exporter, importer  # noqa: E402

CIRCLE_RADIUS = 1.0
CIRCLE_AREA = 3.141592653589793

# A box of side 2 at the origin, which is what the mock's extrude leaves behind.
BOX_EDGE = {"kind": "edge", "body": "Body1", "component": "c0", "curve": "Line3DCurveType",
            "start": [0.0, 0.0, 0.0], "end": [0.0, 0.0, 2.0], "length": 2.0}
BOX_FACE = {"kind": "face", "body": "Body1", "component": "c0", "surface": "PlaneSurfaceType",
            "centroid": [1.0, 1.0, 0.0], "point": [1.0, 1.0, 0.0], "area": 4.0}


def write_bundle(directory, data, steps=("step/c0.step",)):
    path = os.path.join(directory, "design.f540x")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("design.json", json.dumps(data))
        for step in steps:
            archive.writestr(step, "ISO-10303-21; stub")
    return path


def circle_design(timeline_extra=(), body_volume=2 * CIRCLE_AREA, parameters=()):
    """A design that extrudes a circle, plus whatever timeline items a test adds."""
    sketch = {
        "id": "s0", "name": "Sketch1", "component": "c0",
        "plane": {"kind": "constructionPlane", "name": "XY", "component": "c0"},
        "transform": list(fusion_mock.IDENTITY),
        "points": [{"id": "s0.0", "position": [0.0, 0.0, 0.0]}],
        "curves": [{"id": "s0.1", "type": "SketchCircle", "center": "s0.0",
                    "radius": CIRCLE_RADIUS, "construction": False}],
        "constraints": [], "dimensions": [],
        "profiles": [{"loops": [{"outer": True, "curves": ["s0.1"]}]}],
    }
    extrude = {"kind": "feature", "type": "ExtrudeFeature", "name": "Extrude1",
               "component": "c0", "operation": "NewBodyFeatureOperation",
               "parameters": ["d1"],
               "profile": {"kind": "profile", "sketch": "s0",
                           "loops": [{"outer": True, "curves": ["s0.1"]}]},
               "extentOne": {"type": "DistanceExtentDefinition", "distance": "d1"}}
    items = [{"index": 0, "name": "Sketch1", "entity": {"kind": "sketch", "sketch": "s0"}},
             {"index": 1, "name": "Extrude1", "entity": extrude}]
    for offset, entity in enumerate(timeline_extra):
        items.append({"index": 2 + offset, "name": entity.get("name"), "entity": entity})
    return {
        "schema": "f540x/0",
        "source": {"name": "Disc"},
        "units": {"length": "cm", "angle": "rad", "display": "mm"},
        "designType": "parametric",
        "userParameters": [],
        "modelParameters": [{"name": "d1", "expression": "20 mm", "value": 2.0, "unit": "mm"}]
                           + list(parameters),
        "components": [{"id": "c0", "name": "Disc",
                        "bodies": [{"name": "Body1", "volume": body_volume,
                                    "step": "step/c0.step"}]}],
        "rootComponent": "c0",
        "occurrences": [],
        "sketches": [sketch],
        "timeline": {"markerPosition": len(items), "items": items},
        "joints": [],
    }


def run_import(data, bundle_dir=None):
    app = fusion_mock.FakeApp()
    document = app.documents.add(0)
    design = document.products.itemByProductType("DesignProductType")
    report = importer.Importer(app, data, bundle_dir).import_into(design)
    return app, design, report


class RoundTripTest(unittest.TestCase):
    """Exporter and importer against the same bundle, the way the two will be used."""

    def test_export_then_import(self):
        app = types.SimpleNamespace(version="2.0.test", activeDocument=None)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "AshTray.f540x")
            exporter.export_design(app, fusion_mock.make_design(), path)
            fusion = fusion_mock.FakeApp()
            report, directory = importer.import_bundle(fusion, path)
        design = fusion.documents.created[0].design
        root = design.rootComponent

        self.assertEqual(root.name, "Root")
        self.assertEqual(fusion.documents.created[0].name, "AshTray")
        self.assertIsNotNone(design.allParameters.itemByName("width"))

        sketch = root.sketches.item(0)
        self.assertEqual(sketch.name, "Sketch1")
        self.assertEqual([c.objectType.split("::")[-1] for c in sketch.curves],
                         ["SketchLine", "SketchCircle"])
        line = sketch.curves[0]
        self.assertEqual((line.endSketchPoint.geometry.x, line.endSketchPoint.geometry.y), (2.0, 0.0))
        # The line's start and the circle's centre are the same exported point, so they
        # have to be the same sketch point here too.
        self.assertIs(line.startSketchPoint, sketch.curves[1].centerSketchPoint)
        self.assertEqual(sketch.curves[1].radius, 1.0)
        self.assertEqual([call[0] for call in sketch.sketchDimensions.calls],
                         ["addDiameterDimension"])
        self.assertEqual([call[0] for call in sketch.geometricConstraints.calls], ["addHorizontal"])

        # The diameter dimension's parameter keeps the name the bundle used, so that
        # expressions elsewhere in the bundle still mean something.
        self.assertIsNotNone(design.allParameters.itemByName("d1"))
        self.assertIsNotNone(design.allParameters.itemByName("d2"))
        self.assertEqual(design.allParameters.itemByName("d1").value, 2.0)

        extrude = [o for o in design.history if "ExtrudeFeature" in o.objectType][0]
        self.assertEqual(extrude.name, "Extrude1")
        self.assertEqual(extrude.input.extent[0], "distance")

        # The mock does not really model solids, so the rebuilt volume will not match the
        # bundle: the importer must notice and bring the STEP in as a base feature.
        self.assertEqual(report.counts.get("STEP fallbacks"), 1)
        self.assertEqual(len(app_imports(fusion)), 1)
        self.assertTrue(root.baseFeatureList[0].finished)
        self.assertIn("the bundle has 8.0000 cm3", report.log_text())
        self.assertTrue(os.path.isdir(directory))

    def test_import_log_is_written_beside_the_bundle(self):
        app = types.SimpleNamespace(version="2.0.test", activeDocument=None)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "AshTray.f540x")
            exporter.export_design(app, fusion_mock.make_design(), path)
            report, _directory = importer.import_bundle(fusion_mock.FakeApp(), path)
            log = importer.write_log(path, report)
            self.assertEqual(log, os.path.join(tmp, "AshTray-import.log"))
            with open(log) as f:
                self.assertIn("Fission540 import of AshTray.f540x", f.read())


def app_imports(app):
    return app.importManager.imported


class SketchTest(unittest.TestCase):
    def test_geometry_follows_the_new_sketch_axes(self):
        """A sketch rebuilt on axes Fusion chose differently still lands in the same place."""
        data = circle_design()
        data["sketches"][0]["points"].append({"id": "s0.2", "position": [2.0, 0.0, 0.0]})
        data["sketches"][0]["curves"] = [
            {"id": "s0.3", "type": "SketchLine", "start": "s0.0", "end": "s0.2"}]
        data["sketches"][0]["profiles"] = []
        data["timeline"]["items"] = [data["timeline"]["items"][0]]

        app = fusion_mock.FakeApp()
        document = app.documents.add(0)
        design = document.products.itemByProductType("DesignProductType")
        # Fusion's own sketch axes, rotated 90 degrees about Z from the exported ones.
        design.rootComponent.xYConstructionPlane.sketchTransform = (
            0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
        importer.Importer(app, data, None).import_into(design)

        line = design.rootComponent.sketches.item(0).curves[0]
        end = line.endSketchPoint.geometry
        self.assertAlmostEqual(end.x, 0.0)
        self.assertAlmostEqual(end.y, -2.0)

    def test_out_of_plane_geometry_is_reported_not_moved(self):
        data = circle_design()
        data["sketches"][0]["points"].append({"id": "s0.2", "position": [2.0, 1.0, 0.0]})
        # Exported from a plane rotated about X, so the geometry would not be flat in a
        # sketch Fusion placed on the XY plane.
        data["sketches"][0]["transform"] = (1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1)
        _app, _design, report = run_import(data)
        self.assertIn("does not match the exported one", report.log_text())

    def test_unresolved_plane_falls_back_to_xy(self):
        data = circle_design()
        data["sketches"][0]["plane"] = {"kind": "constructionPlane", "name": "Nope",
                                        "component": "c0"}
        data["sketches"][0]["transform"] = None
        _app, design, report = run_import(data)
        self.assertEqual(design.rootComponent.sketches.count, 1)
        self.assertIn("placed on the XY plane", report.log_text())

    def test_exotic_curves_come_in_as_fixed_splines(self):
        data = circle_design()
        data["sketches"][0]["curves"].append({
            "id": "s0.9", "type": "SketchConicCurve",
            "nurbs": {"degree": 1, "controlPoints": [[0.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
                      "knots": [0.0, 0.0, 1.0, 1.0], "weights": None, "periodic": False}})
        _app, design, report = run_import(data)
        kinds = [c.objectType.split("::")[-1] for c in design.rootComponent.sketches.item(0).curves]
        self.assertIn("SketchFixedSpline", kinds)
        self.assertIn("rebuilt as a fixed spline", report.log_text())


class FeatureTest(unittest.TestCase):
    def test_extrude_uses_the_bundle_expression(self):
        _app, design, report = run_import(circle_design())
        self.assertEqual(report.counts.get("features"), 1)
        extrude = [o for o in design.history if "ExtrudeFeature" in o.objectType][0]
        self.assertEqual(extrude.input.extent[2].expression, "20 mm")
        self.assertAlmostEqual(extrude.bodies.item(0).physicalProperties.volume,
                               2 * CIRCLE_AREA)
        self.assertEqual(report.counts.get("STEP fallbacks"), None)  # volumes agree

    def test_expression_falls_back_to_a_number_when_a_name_is_missing(self):
        data = circle_design()
        data["modelParameters"][0]["expression"] = "plate_thickness * 2"
        data["modelParameters"][0]["value"] = 2.0
        _app, design, report = run_import(data)
        extrude = [o for o in design.history if "ExtrudeFeature" in o.objectType][0]
        self.assertEqual(extrude.input.extent[2].real, 2.0)
        self.assertIn("imported as a number", report.log_text())

    def test_user_parameters_are_added_in_dependency_order(self):
        data = circle_design()
        data["userParameters"] = [
            {"name": "height", "expression": "width * 2", "value": 8.0, "unit": "mm"},
            {"name": "width", "expression": "40 mm", "value": 4.0, "unit": "mm"},
        ]
        _app, design, report = run_import(data)
        self.assertEqual(report.counts.get("user parameters"), 2)
        self.assertAlmostEqual(design.allParameters.itemByName("height").value, 8.0)

    def test_a_user_parameter_that_cannot_be_evaluated_is_reported(self):
        data = circle_design()
        data["userParameters"] = [{"name": "bad", "expression": "nonsense * 2", "value": 1.0,
                                   "unit": "mm"}]
        _app, _design, report = run_import(data)
        self.assertIn("user parameter bad", report.log_text())

    def test_fillet_resolves_an_edge_by_its_signature(self):
        fillet = {"kind": "feature", "type": "FilletFeature", "name": "Fillet1",
                  "component": "c0", "parameters": ["r1"],
                  "edgeSets": [{"type": "FilletConstantRadiusEdgeSet", "edges": [BOX_EDGE],
                                "radius": "r1", "tangentChain": True}]}
        data = circle_design(timeline_extra=[fillet],
                             parameters=[{"name": "r1", "expression": "2 mm", "value": 0.2,
                                          "unit": "mm"}])
        _app, design, report = run_import(data)

        self.assertEqual(report.counts.get("features"), 2)
        created = [o for o in design.history if "FilletFeature" in o.objectType][0]
        self.assertEqual(created.name, "Fillet1")
        kind, edges, radius, chain = created.input.edgeSetInputs.sets[0]
        self.assertEqual((kind, edges.count, radius.expression, chain), ("constant", 1, "2 mm", True))
        edge = edges.item(0)
        self.assertEqual((edge.startVertex.geometry.z, edge.endVertex.geometry.z), (0.0, 2.0))
        self.assertIsNotNone(design.allParameters.itemByName("r1"))

    def test_an_edge_that_does_not_match_is_reported_not_guessed(self):
        moved = dict(BOX_EDGE, start=[0.0, 0.0, 5.0], end=[0.0, 0.0, 7.0])
        fillet = {"kind": "feature", "type": "FilletFeature", "name": "Fillet1",
                  "component": "c0", "edgeSets": [{"type": "FilletConstantRadiusEdgeSet",
                                                   "edges": [moved], "radius": "r1"}]}
        data = circle_design(timeline_extra=[fillet])
        _app, design, report = run_import(data)
        self.assertEqual([o for o in design.history if "FilletFeature" in o.objectType], [])
        self.assertIn("unresolved edge reference", report.log_text())
        self.assertIn("closest edge was", report.log_text())
        self.assertEqual(report.counts.get("features not rebuilt"), 1)

    def test_a_face_resolves_by_centroid_and_area(self):
        data = circle_design()
        _app, design, report = run_import(data)
        imp = importer.Importer(None, data, None)
        imp.design, imp.root = design, design.rootComponent
        imp.components["c0"] = design.rootComponent
        face = imp.resolver.resolve(BOX_FACE)
        self.assertIsNotNone(face)
        self.assertEqual(face.centroid.z, 0.0)
        self.assertIsNone(imp.resolver.resolve(dict(BOX_FACE, area=99.0)))

    def test_an_unmapped_feature_type_is_reported_and_backed_by_step(self):
        rib = {"kind": "feature", "type": "RibFeature", "name": "Rib1", "component": "c0",
               "unsupported": True}
        data = circle_design(timeline_extra=[rib], body_volume=99.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_bundle(tmp, data)
            app = fusion_mock.FakeApp()
            report, directory = importer.import_bundle(app, path)
            design = app.documents.created[0].design
            self.assertEqual(report.counts.get("features not rebuilt"), 1)
            self.assertIn("RibFeature 'Rib1' was not rebuilt", report.log_text())
            self.assertEqual(report.counts.get("STEP fallbacks"), 1)
            self.assertEqual(len(app.importManager.imported), 1)
            self.assertTrue(app.importManager.imported[0][0].endswith("c0.step"))
            self.assertEqual(design.rootComponent.baseFeatureList[0].name,
                             "Fission540 fallback geometry")
            self.assertTrue(os.path.isdir(directory))

    def test_suppressed_features_are_suppressed_last(self):
        data = circle_design()
        data["timeline"]["items"][1]["suppressed"] = True
        _app, design, report = run_import(data)
        extrude = [o for o in design.history if "ExtrudeFeature" in o.objectType][0]
        self.assertTrue(extrude.isSuppressed)
        self.assertEqual(report.counts.get("suppressed features"), 1)
        # Suppressing early would have hidden the body the geometry check needs.
        self.assertEqual(extrude.bodies.count, 1)

    def test_the_timeline_marker_ends_after_the_fallback_geometry(self):
        data = circle_design(body_volume=99.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_bundle(tmp, data)
            app = fusion_mock.FakeApp()
            importer.import_bundle(app, path)
            design = app.documents.created[0].design
        self.assertEqual(design.timeline.markerPosition, design.timeline.count)


class ComponentTest(unittest.TestCase):
    def test_occurrences_are_rebuilt_as_a_tree(self):
        data = circle_design()
        data["components"].append({"id": "c1", "name": "Bracket", "bodies": []})
        data["components"].append({"id": "c2", "name": "Screw", "bodies": []})
        data["occurrences"] = [{
            "id": "o0", "name": "Bracket:1", "component": "c1",
            "transform": list(fusion_mock.IDENTITY), "grounded": True,
            "children": [{"id": "o1", "name": "Screw:1", "component": "c2",
                          "transform": list(fusion_mock.IDENTITY), "children": []},
                         {"id": "o2", "name": "Screw:2", "component": "c2",
                          "transform": list(fusion_mock.IDENTITY), "children": []}],
        }]
        _app, design, report = run_import(data)
        root = design.rootComponent
        self.assertEqual(root.occurrences.count, 1)
        bracket = root.occurrences.item(0).component
        self.assertEqual(bracket.name, "Bracket")
        self.assertTrue(root.occurrences.item(0).isGrounded)
        self.assertEqual(bracket.occurrences.count, 2)
        # The second instance of the same component must reuse it, not make a copy.
        self.assertIs(bracket.occurrences.item(0).component,
                      bracket.occurrences.item(1).component)
        self.assertEqual(report.counts.get("occurrences"), 3)
        self.assertEqual(report.counts.get("components"), 2)

    def test_a_feature_is_built_in_its_own_component(self):
        data = circle_design()
        data["components"].append({"id": "c1", "name": "Lid", "bodies": []})
        data["occurrences"] = [{"id": "o0", "name": "Lid:1", "component": "c1",
                                "transform": list(fusion_mock.IDENTITY), "children": []}]
        data["sketches"][0]["component"] = "c1"
        data["timeline"]["items"][1]["entity"]["component"] = "c1"
        _app, design, _report = run_import(data)
        lid = design.rootComponent.occurrences.item(0).component
        self.assertEqual(lid.sketches.count, 1)
        self.assertEqual(lid.bRepBodies.count, 1)
        self.assertEqual(design.rootComponent.sketches.count, 0)


class JointTest(unittest.TestCase):
    def test_a_revolute_joint_is_rebuilt_from_resolved_geometry(self):
        data = circle_design()
        data["joints"] = [{
            "id": "j0", "name": "Hinge", "kind": "joint", "motion": "RevoluteJointMotion",
            "occurrenceOne": None, "occurrenceTwo": None,
            "geometryOne": {"type": "JointPlanarBRepFaceGeometry", "keyPointType": "CenterKeyPoint",
                            "entityOne": BOX_FACE},
            "geometryTwo": {"type": "JointPlanarBRepFaceGeometry", "keyPointType": "CenterKeyPoint",
                            "entityOne": dict(BOX_FACE, centroid=[1.0, 1.0, 2.0],
                                              point=[1.0, 1.0, 2.0])},
            "values": {"rotationAxis": "ZAxisJointDirection"},
        }]
        _app, design, report = run_import(data)
        self.assertEqual(report.counts.get("joints"), 1)
        joint = design.rootComponent.joints.item(0)
        self.assertEqual(joint.name, "Hinge")
        self.assertEqual(joint.input.motion[0], "setAsRevoluteJointMotion")

    def test_a_joint_whose_geometry_is_gone_is_reported(self):
        data = circle_design()
        data["joints"] = [{"id": "j0", "name": "Hinge", "kind": "joint",
                           "motion": "RevoluteJointMotion",
                           "geometryOne": {"entityOne": dict(BOX_FACE, centroid=[9.0, 9.0, 9.0])},
                           "geometryTwo": {"entityOne": BOX_FACE}}]
        _app, design, report = run_import(data)
        self.assertEqual(design.rootComponent.joints.count, 0)
        self.assertIn("joint 'Hinge' was not rebuilt", report.log_text())


class BundleTest(unittest.TestCase):
    def test_an_unknown_schema_is_refused(self):
        data = circle_design()
        data["schema"] = "f540x/99"
        with self.assertRaises(importer.Unsupported) as caught:
            run_import(data)
        self.assertIn("f540x/99", str(caught.exception))

    def test_a_zip_without_design_json_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "not-a-bundle.f540x")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("readme.txt", "nothing to see")
            with self.assertRaises(importer.Unsupported):
                importer.read_bundle(path)

    def test_a_direct_design_still_brings_its_sketches_and_geometry(self):
        data = circle_design()
        data["designType"] = "direct"
        data["timeline"] = {}
        with tempfile.TemporaryDirectory() as tmp:
            path = write_bundle(tmp, data)
            app = fusion_mock.FakeApp()
            report, _directory = importer.import_bundle(app, path)
            design = app.documents.created[0].design
        self.assertEqual(design.rootComponent.sketches.count, 1)
        self.assertEqual(report.counts.get("STEP fallbacks"), 1)

    def test_the_display_unit_comes_across(self):
        _app, design, _report = run_import(circle_design())
        self.assertEqual(design.fusionUnitsManager.distanceDisplayUnits,
                         fusion_mock.DistanceUnits.MillimeterDistanceUnits)

    def test_identifiers_in_an_expression(self):
        self.assertEqual(importer._identifiers("width / 2 + 3 mm"), ["width"])
        self.assertEqual(importer._identifiers("40 mm"), [])
        self.assertEqual(importer._identifiers("sin(a1) * d7"), ["a1", "d7"])


class RichDesignTest(unittest.TestCase):
    """Every feature type with a builder, against a mock that checks call shapes."""

    def design(self, *features):
        parameters = [{"name": "p1", "expression": "3 mm", "value": 0.3, "unit": "mm"},
                      {"name": "a1", "expression": "45 deg", "value": 0.785398, "unit": "deg"}]
        return circle_design(timeline_extra=list(features), parameters=parameters)

    def build(self, *features):
        data = self.design(*features)
        _app, design, report = run_import(data)
        return design, report

    def created(self, design, type_name):
        found = [o for o in design.history if type_name in o.objectType]
        self.assertTrue(found, "%s was not created" % type_name)
        return found[0]

    def test_revolve(self):
        design, report = self.build({
            "kind": "feature", "type": "RevolveFeature", "name": "Revolve1", "component": "c0",
            "operation": "NewBodyFeatureOperation",
            "profile": {"kind": "profile", "sketch": "s0",
                        "loops": [{"outer": True, "curves": ["s0.1"]}]},
            "axis": {"kind": "constructionAxis", "name": "X", "component": "c0"},
            "extentOne": {"type": "AngleExtentDefinition", "angle": "a1", "symmetric": False}})
        revolve = self.created(design, "RevolveFeature")
        self.assertEqual(revolve.input.calls[0][0], "setAngleExtent")
        self.assertEqual(revolve.input.calls[0][1][1].expression, "45 deg")
        self.assertEqual(report.counts.get("features"), 2)

    def test_chamfer_shell_and_draft(self):
        design, _report = self.build(
            {"kind": "feature", "type": "ChamferFeature", "name": "Chamfer1", "component": "c0",
             "edgeSets": [{"type": "ChamferEqualDistanceEdgeSet", "edges": [BOX_EDGE],
                           "distance": "p1", "tangentChain": False}]},
            {"kind": "feature", "type": "ShellFeature", "name": "Shell1", "component": "c0",
             "inputEntities": [BOX_FACE], "inside": "p1", "tangentChain": True},
            {"kind": "feature", "type": "DraftFeature", "name": "Draft1", "component": "c0",
             "faces": [dict(BOX_FACE, centroid=[0.0, 1.0, 1.0], point=[0.0, 1.0, 1.0])],
             "plane": {"kind": "constructionPlane", "name": "XY", "component": "c0"},
             "tangentChain": True})
        chamfer = self.created(design, "ChamferFeature")
        name, args = chamfer.input.calls[0]
        self.assertEqual(name, "addEqualDistanceChamferEdgeSet")
        self.assertEqual((args[0].count, args[1].expression, args[2]), (1, "3 mm", False))
        shell = self.created(design, "ShellFeature")
        self.assertEqual(shell.input.args[0].count, 1)
        self.assertEqual(shell.input.set["insideThickness"].expression, "3 mm")
        self.assertEqual(self.created(design, "DraftFeature").input.args[2], True)

    def test_combine_mirror_and_patterns(self):
        design, report = self.build(
            {"kind": "feature", "type": "CombineFeature", "name": "Combine1", "component": "c0",
             "target": {"kind": "body", "body": "Body1", "component": "c0"},
             "tools": [{"kind": "body", "body": "Body1", "component": "c0"}],
             "operation": "CutFeatureOperation", "keepTools": True},
            {"kind": "feature", "type": "MirrorFeature", "name": "Mirror1", "component": "c0",
             "inputEntities": [{"kind": "body", "body": "Body1", "component": "c0"}],
             "mirrorPlane": {"kind": "constructionPlane", "name": "YZ", "component": "c0"}},
            {"kind": "feature", "type": "RectangularPatternFeature", "name": "Pattern1",
             "component": "c0",
             "inputEntities": [{"kind": "body", "body": "Body1", "component": "c0"}],
             "directionOne": {"kind": "constructionAxis", "name": "X", "component": "c0"},
             "directionTwo": {"kind": "constructionAxis", "name": "Y", "component": "c0"},
             "quantityOne": "p1", "distanceOne": "p1", "quantityTwo": "p1", "distanceTwo": "p1",
             "distanceType": "SpacingPatternDistanceType"},
            {"kind": "feature", "type": "CircularPatternFeature", "name": "Pattern2",
             "component": "c0",
             "inputEntities": [{"kind": "body", "body": "Body1", "component": "c0"}],
             "axis": {"kind": "constructionAxis", "name": "Z", "component": "c0"},
             "quantity": "p1", "totalAngle": "a1", "symmetric": False})
        combine = self.created(design, "CombineFeature")
        self.assertEqual(combine.input.set["operation"], fusion_mock.FeatureOperations.CutFeatureOperation)
        self.assertEqual(combine.input.set["isKeepToolBodies"], True)
        self.assertEqual(self.created(design, "MirrorFeature").input.args[1].name, "YZ Plane")
        rectangular = self.created(design, "RectangularPatternFeature")
        self.assertEqual(rectangular.input.args[1].name, "X Axis")
        self.assertEqual(rectangular.input.args[4],
                         fusion_mock.PatternDistanceType.SpacingPatternDistanceType)
        self.assertEqual(rectangular.input.calls[0][0], "setDirectionTwo")
        circular = self.created(design, "CircularPatternFeature")
        self.assertEqual(circular.input.args[1].name, "Z Axis")
        self.assertEqual(circular.input.set["totalAngle"].expression, "45 deg")
        self.assertEqual(report.counts.get("features"), 5)

    def test_hole_on_a_sketch_point(self):
        data = self.design({
            "kind": "feature", "type": "HoleFeature", "name": "Hole1", "component": "c0",
            "holeType": "SimpleHoleType", "diameter": "p1",
            "positionDefinition": {"type": "SketchPointHolePositionDefinition",
                                   "sketchPoint": {"kind": "sketchEntity", "sketch": "s0",
                                                   "entity": "s0.0"}},
            "extent": {"type": "DistanceExtentDefinition", "distance": "p1"}})
        _app, design, _report = run_import(data)
        hole = self.created(design, "HoleFeature")
        self.assertEqual(hole.input.args[0].expression, "3 mm")
        self.assertEqual([call[0] for call in hole.input.calls],
                         ["setPositionBySketchPoint", "setDistanceExtent"])

    def test_a_hole_with_no_position_definition_is_reported(self):
        design, report = self.build({
            "kind": "feature", "type": "HoleFeature", "name": "Hole1", "component": "c0",
            "holeType": "SimpleHoleType", "diameter": "p1"})
        self.assertEqual([o for o in design.history if "HoleFeature" in o.objectType], [])
        self.assertIn("hole position was not exported", report.log_text())

    def test_construction_plane_by_offset(self):
        design, _report = self.build({
            "kind": "feature", "type": "ConstructionPlane", "name": "Plane1", "component": "c0",
            "definition": {"type": "ConstructionPlaneOffsetDefinition",
                           "planarEntity": {"kind": "constructionPlane", "name": "XY",
                                            "component": "c0"},
                           "offset": "p1"}})
        plane = design.rootComponent.constructionPlanes.item(0)
        method, args = plane.definition
        self.assertEqual(method, "setByOffset")
        self.assertEqual((args[0].name, args[1].expression), ("XY Plane", "3 mm"))

    def test_an_arc_keeps_its_direction(self):
        """The mid point comes from the arc's own frame, so the right half is rebuilt."""
        for normal, start_angle, end_angle, expected in (
                ([0.0, 0.0, 1.0], 0.0, math.pi / 2, (0.7071067811, 0.7071067811)),
                ([0.0, 0.0, -1.0], 0.0, 3 * math.pi / 2, (-0.7071067811, -0.7071067811))):
            data = circle_design()
            data["sketches"][0]["points"] += [{"id": "s0.2", "position": [1.0, 0.0, 0.0]},
                                              {"id": "s0.3", "position": [0.0, 1.0, 0.0]}]
            data["sketches"][0]["curves"] = [{
                "id": "s0.4", "type": "SketchArc", "center": "s0.0", "start": "s0.2",
                "end": "s0.3", "radius": 1.0, "normal": normal,
                "referenceVector": [1.0, 0.0, 0.0],
                "startAngle": start_angle, "endAngle": end_angle}]
            data["sketches"][0]["profiles"] = []
            data["timeline"]["items"] = [data["timeline"]["items"][0]]
            _app, design, report = run_import(data)
            arc = design.rootComponent.sketches.item(0).curves[0]
            self.assertAlmostEqual(arc.pointOnArc.x, expected[0], places=6)
            self.assertAlmostEqual(arc.pointOnArc.y, expected[1], places=6)
            self.assertNotIn("rebuilt from its chord", report.log_text())

    def test_an_arc_with_no_frame_falls_back_to_its_chord(self):
        data = circle_design()
        data["sketches"][0]["points"] += [{"id": "s0.2", "position": [1.0, 0.0, 0.0]},
                                          {"id": "s0.3", "position": [0.0, 1.0, 0.0]}]
        data["sketches"][0]["curves"] = [{"id": "s0.4", "type": "SketchArc", "center": "s0.0",
                                          "start": "s0.2", "end": "s0.3", "radius": 1.0}]
        data["sketches"][0]["profiles"] = []
        data["timeline"]["items"] = [data["timeline"]["items"][0]]
        _app, design, report = run_import(data)
        arc = design.rootComponent.sketches.item(0).curves[0]
        self.assertAlmostEqual(arc.pointOnArc.x, 0.7071067811, places=6)
        self.assertIn("rebuilt from its chord", report.log_text())


if __name__ == "__main__":
    unittest.main()
