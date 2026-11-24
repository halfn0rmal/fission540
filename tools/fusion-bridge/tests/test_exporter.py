"""Runs the f540x exporter against mock Fusion API objects (no Fusion needed).

    python -m unittest discover -s tools/fusion-bridge/tests

Only checks that the exporter's code paths run and produce the schema's shape; whether
the real Fusion API behaves like these mocks is checked by running the add-in in Fusion.
"""

import json
import os
import sys
import tempfile
import types
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "Fission540Bridge"))


# ---- mock adsk modules ----------------------------------------------------------

def _install_mock_adsk():
    adsk = types.ModuleType("adsk")
    core = types.ModuleType("adsk.core")
    fusion = types.ModuleType("adsk.fusion")

    class SurfaceTypes:
        PlaneSurfaceType = 0
        CylinderSurfaceType = 1

    class Curve3DTypes:
        Line3DCurveType = 0
        Circle3DCurveType = 2

    class FeatureOperations:
        JoinFeatureOperation = 0
        CutFeatureOperation = 1
        NewBodyFeatureOperation = 3

    class FeatureHealthStates:
        HealthyFeatureHealthState = 0

    class DimensionOrientations:
        AlignedDimensionOrientation = 0
        HorizontalDimensionOrientation = 1

    class DesignTypes:
        DirectDesignType = 0
        ParametricDesignType = 1

    class TimelineGroup:
        @staticmethod
        def cast(obj):
            return obj

    core.SurfaceTypes = SurfaceTypes
    core.Curve3DTypes = Curve3DTypes
    fusion.FeatureOperations = FeatureOperations
    fusion.FeatureHealthStates = FeatureHealthStates
    fusion.DimensionOrientations = DimensionOrientations
    fusion.DesignTypes = DesignTypes
    fusion.TimelineGroup = TimelineGroup
    adsk.core, adsk.fusion = core, fusion
    sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})


_install_mock_adsk()
from f540x import exporter  # noqa: E402


class Obj:
    _n = 0

    def __init__(self, type_name, **attrs):
        Obj._n += 1
        self.objectType = "adsk::fusion::" + type_name
        self.entityToken = "tok%d" % Obj._n
        self.__dict__.update(attrs)


class Coll:
    def __init__(self, items):
        self._items = list(items)
        self.count = len(self._items)

    def item(self, i):
        return self._items[i]


class P:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class M:
    def asArray(self):
        return (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def make_design():
    root = Obj("Component", name="Root", partNumber="ASH-1", description="")
    root.xYConstructionPlane = Obj("ConstructionPlane", name="XY Plane", component=root)
    body = Obj("BRepBody", name="Body1", isSolid=True, isVisible=True, parentComponent=root,
               physicalProperties=types.SimpleNamespace(volume=8.0, area=24.0),
               faces=Coll([]), edges=Coll([]))
    root.bRepBodies = Coll([body])
    root.constructionPlanes = Coll([])
    root.constructionAxes = Coll([])
    root.constructionPoints = Coll([])
    root.joints = Coll([])
    root.asBuiltJoints = Coll([])

    sketch = Obj("Sketch", name="Sketch1", parentComponent=root, transform=M(), isVisible=True,
                 referencePlane=root.xYConstructionPlane)
    p0 = Obj("SketchPoint", geometry=P(0, 0, 0), parentSketch=sketch, isFixed=False, isReference=False)
    p1 = Obj("SketchPoint", geometry=P(2, 0, 0), parentSketch=sketch, isFixed=False, isReference=False)
    line = Obj("SketchLine", startSketchPoint=p0, endSketchPoint=p1, parentSketch=sketch,
               isConstruction=False, isFixed=False, isReference=False, isFullyConstrained=True,
               geometry=None)
    circle = Obj("SketchCircle", centerSketchPoint=p0, radius=1.0, parentSketch=sketch,
                 isConstruction=False, isFixed=False, isReference=False, isFullyConstrained=True,
                 geometry=None)
    sketch.sketchPoints = Coll([p0, p1])
    sketch.sketchCurves = Coll([line, circle])
    sketch.geometricConstraints = Coll([Obj("HorizontalConstraint", line=line)])
    d1 = Obj("ModelParameter", name="d1", expression="20 mm", value=2.0, unit="mm", role="Diameter")
    sketch.sketchDimensions = Coll([Obj("SketchDiameterDimension", entity=circle, parameter=d1,
                                        isDriving=True, textPosition=P(1, 1, 0))])
    loop = Obj("ProfileLoop", isOuter=True,
               profileCurves=Coll([Obj("ProfileCurve", sketchEntity=circle)]))
    profile = Obj("Profile", parentSketch=sketch, profileLoops=Coll([loop]))
    sketch.profiles = Coll([profile])
    root.sketches = Coll([sketch])
    d1.createdBy = sketch.sketchDimensions.item(0)
    d1.component = root

    d2 = Obj("ModelParameter", name="d2", expression="10 mm", value=1.0, unit="mm",
             role="AlongDistance", component=root)
    extrude = Obj("ExtrudeFeature", name="Extrude1", parentComponent=root, healthState=0,
                  errorOrWarningMessage="", bodies=Coll([body]), profile=profile, operation=3,
                  extentOne=Obj("DistanceExtentDefinition", distance=d2),
                  startExtent=Obj("ProfilePlaneStartDefinition"))
    d2.createdBy = extrude
    width = Obj("UserParameter", name="width", expression="20 mm", value=2.0, unit="mm", comment="")

    timeline = Coll([
        Obj("TimelineObject", index=0, name="Sketch1", isSuppressed=False, isRolledBack=False,
            isGroup=False, entity=sketch),
        Obj("TimelineObject", index=1, name="Extrude1", isSuppressed=False, isRolledBack=False,
            isGroup=False, entity=extrude),
    ])
    timeline.markerPosition = 2

    design = Obj("Design", rootComponent=root, allComponents=Coll([root]),
                 userParameters=Coll([width]), allParameters=Coll([width, d1, d2]),
                 unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
                 timeline=timeline, designType=1,
                 parentDocument=types.SimpleNamespace(name="AshTray", dataFile=None))
    root.occurrences = Coll([])

    class Manager:
        def createSTEPExportOptions(self, path, comp):
            return path

        def createFusionArchiveExportOptions(self, path, comp):
            return path

        def execute(self, path):
            with open(path, "w") as f:
                f.write("stub")
            return True

    design.exportManager = Manager()
    return design


class ExporterTest(unittest.TestCase):
    def test_describe_design(self):
        design = make_design()
        e = exporter.Exporter(types.SimpleNamespace(version="2.0.test", activeDocument=None), design)
        data = e.describe_design({"c0": "step/c0.step"})
        json.dumps(data)  # must be serialisable

        self.assertEqual(data["schema"], "f540x/0")
        self.assertEqual(data["designType"], "parametric")
        self.assertEqual(data["rootComponent"], "c0")
        self.assertEqual(data["components"][0]["bodies"][0]["volume"], 8.0)
        self.assertEqual(data["userParameters"][0]["name"], "width")

        sketch = data["sketches"][0]
        self.assertEqual(sketch["plane"], {"kind": "constructionPlane", "name": "XY", "component": "c0"})
        self.assertEqual([p["id"] for p in sketch["points"]], ["s0.0", "s0.1"])
        line, circle = sketch["curves"]
        self.assertEqual((line["type"], line["start"], line["end"]), ("SketchLine", "s0.0", "s0.1"))
        self.assertEqual((circle["center"], circle["radius"]), ("s0.0", 1.0))
        self.assertEqual(sketch["constraints"][0]["entities"], {"line": line["id"]})
        self.assertEqual(sketch["dimensions"][0]["parameter"], "d1")
        self.assertEqual(sketch["profiles"][0]["loops"][0]["curves"], [circle["id"]])

        items = data["timeline"]["items"]
        self.assertEqual(items[0]["entity"], {"kind": "sketch", "sketch": "s0"})
        extrude = items[1]["entity"]
        self.assertEqual(extrude["type"], "ExtrudeFeature")
        self.assertEqual(extrude["operation"], "NewBodyFeatureOperation")
        self.assertEqual(extrude["extentOne"], {"type": "DistanceExtentDefinition", "distance": "d2"})
        self.assertEqual(extrude["profile"]["loops"][0]["curves"], [circle["id"]])
        self.assertEqual(extrude["parameters"], ["d2"])
        self.assertNotIn("unsupported", extrude)
        self.assertEqual(e.summary.warnings, [])

    def test_bundle(self):
        design = make_design()
        app = types.SimpleNamespace(version="2.0.test", activeDocument=None)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out", "AshTray.f540x")
            summary = exporter.export_design(app, design, path)
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
                data = json.loads(z.read("design.json"))
        self.assertEqual(names, {"design.json", "export.log", "source.f3d",
                                 "step/assembly.step", "step/c0.step"})
        self.assertEqual(data["components"][0]["bodies"][0]["step"], "step/c0.step")
        self.assertEqual(summary.warnings, [])


if __name__ == "__main__":
    unittest.main()
