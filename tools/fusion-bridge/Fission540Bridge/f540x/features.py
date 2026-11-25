"""One builder per Fusion feature type, driven by the f540x description.

Mixed into `Importer`, so each builder has the importer's `value()` for parameters,
`resolver` for references and `report` for what it could not do. A builder either
returns the created feature or raises `Unsupported` with a reason a person can act on;
it never half-builds a feature and carries on.

The method name is the feature's type in the bundle (`_f_ExtrudeFeature`), which is how
`Importer.build_feature` finds it — a type with no method here is reported as having no
mapping in schema 0 and backed by the STEP fallback instead.
"""

import math

import adsk.core
import adsk.fusion

from .api import enum, enum_value, matrix3d, object_collection, point3d, probe
from .report import Unsupported


class FeatureBuilders:
    def operation(self, data, default="NewBodyFeatureOperation"):
        operations = enum(adsk.fusion, "FeatureOperations")
        return enum_value(operations, data.get("operation"),
                          default=enum_value(operations, default, 0))

    def one(self, data, key, component, required=True):
        found = self.resolver.resolve_all(data.get(key), component)
        if not found:
            if required:
                raise Unsupported("%s could not be resolved" % key)
            return None
        return found[0]
    # -- sketch-based features

    def _profile_input(self, data, component, key="profile"):
        profiles = self.resolver.resolve_all(data.get(key), component)
        if not profiles:
            raise Unsupported("no profile resolved; the sketch it uses may have failed")
        return profiles[0] if len(profiles) == 1 else object_collection(profiles)

    def _f_ExtrudeFeature(self, data, component):
        extrudes = self.features_of(component).extrudeFeatures
        feature_input = extrudes.createInput(self._profile_input(data, component),
                                             self.operation(data))
        self._apply_start_extent(feature_input, data.get("start"), component)
        self._apply_extrude_extent(feature_input, data, component)
        participants = self.resolver.resolve_all(data.get("participantBodies"), component)
        if participants:
            try:
                feature_input.participantBodies = participants
            except Exception:
                self.report.note("participant bodies ignored for %s" % data.get("name"))
        return extrudes.add(feature_input)

    def _apply_start_extent(self, feature_input, start, component):
        if not start or start.get("type") in (None, "ProfilePlaneStartDefinition"):
            return
        try:
            if start["type"] == "OffsetStartDefinition":
                definition = adsk.fusion.OffsetStartDefinition.create(
                    self.value(start.get("offset"), 0.0))
            elif start["type"] == "EntityStartDefinition":
                entity = self.one(start, "entity", component)
                definition = adsk.fusion.EntityStartDefinition.create(
                    entity, self.value(start.get("offset"), 0.0))
            else:
                raise Unsupported("start extent %s" % start["type"])
            feature_input.startExtent = definition
        except Unsupported:
            raise
        except Exception:
            self.report.note("start extent %s could not be applied" % start.get("type"))

    def _apply_extrude_extent(self, feature_input, data, component):
        one, two = data.get("extentOne"), data.get("extentTwo")
        taper = self.value(data.get("taperOne")) if data.get("taperOne") else None
        if one is None:
            raise Unsupported("no extent in the bundle")
        kind = one.get("type")
        if two is not None and two.get("type") == "DistanceExtentDefinition" \
                and kind == "DistanceExtentDefinition":
            feature_input.setTwoSidesDistanceExtent(self.value(one.get("distance"), 1.0),
                                                    self.value(two.get("distance"), 1.0))
            return
        if kind == "DistanceExtentDefinition":
            feature_input.setDistanceExtent(False, self.value(one.get("distance"), 1.0))
        elif kind == "SymmetricExtentDefinition":
            feature_input.setSymmetricExtent(self.value(one.get("distance"), 1.0),
                                             bool(one.get("fullLength", True)))
        elif kind == "ThroughAllExtentDefinition":
            directions = enum(adsk.fusion, "ExtentDirections")
            positive = one.get("positive")
            name = "NegativeExtentDirection" if positive is False else "PositiveExtentDirection"
            feature_input.setAllExtent(enum_value(directions, name, 0))
        elif kind == "ToEntityExtentDefinition":
            feature_input.setOneSideToExtent(self.one(one, "entity", component),
                                             bool(one.get("chained", False)))
        else:
            raise Unsupported("extent %s" % kind)
        if taper is not None:
            try:
                feature_input.taperAngle = taper
            except Exception:
                self.report.note("taper angle ignored for %s" % data.get("name"))

    def _f_RevolveFeature(self, data, component):
        revolves = self.features_of(component).revolveFeatures
        axis = self.one(data, "axis", component)
        feature_input = revolves.createInput(self._profile_input(data, component), axis,
                                             self.operation(data))
        one = data.get("extentOne") or {}
        kind = one.get("type")
        if kind == "AngleExtentDefinition":
            feature_input.setAngleExtent(bool(one.get("symmetric", False)),
                                         self.value(one.get("angle"), 2 * math.pi))
        elif kind == "FullExtentDefinition" or kind is None:
            feature_input.setAllExtent()
        elif kind == "ToEntityExtentDefinition":
            feature_input.setToEntityExtent(self.one(one, "entity", component),
                                            bool(one.get("chained", False)))
        else:
            raise Unsupported("revolve extent %s" % kind)
        return revolves.add(feature_input)

    def _f_SweepFeature(self, data, component):
        sweeps = self.features_of(component).sweepFeatures
        curves = self.resolver.resolve_all(data.get("path"), component)
        if not curves:
            raise Unsupported("sweep path could not be resolved")
        path = self._path(curves)
        feature_input = sweeps.createInput(self._profile_input(data, component), path,
                                           self.operation(data))
        for key, attribute in (("taper", "taperAngle"), ("twist", "twistAngle"),
                               ("distanceOne", "distanceOne"), ("distanceTwo", "distanceTwo")):
            if data.get(key):
                try:
                    setattr(feature_input, attribute, self.value(data[key]))
                except Exception:
                    self.report.note("sweep %s ignored" % key)
        rails = self.resolver.resolve_all(data.get("guideRail"), component)
        if rails:
            try:
                feature_input.guideRail = self._path(rails)
            except Exception:
                self.report.note("sweep guide rail ignored")
        return sweeps.add(feature_input)

    def _path(self, curves):
        chain = enum_value(enum(adsk.fusion, "ChainedCurveOptions"), "noChainedCurves", 0)
        try:
            return adsk.fusion.Path.create(object_collection(curves), chain)
        except Exception:
            return adsk.fusion.Path.create(curves[0], chain)

    def _f_HoleFeature(self, data, component):
        holes = self.features_of(component).holeFeatures
        hole_type = data.get("holeType")
        if hole_type == "CounterboreHoleType":
            feature_input = holes.createCounterboreInput(
                self.value(data.get("diameter"), 0.5),
                self.value(data.get("counterboreDiameter"), 1.0),
                self.value(data.get("counterboreDepth"), 0.2))
        elif hole_type == "CountersinkHoleType":
            feature_input = holes.createCountersinkInput(
                self.value(data.get("diameter"), 0.5),
                self.value(data.get("countersinkDiameter"), 1.0),
                self.value(data.get("countersinkAngle"), math.radians(90)))
        else:
            feature_input = holes.createSimpleInput(self.value(data.get("diameter"), 0.5))
        self._position_hole(feature_input, data, component)
        extent = data.get("extent") or {}
        kind = extent.get("type")
        if kind == "DistanceExtentDefinition":
            feature_input.setDistanceExtent(self.value(extent.get("distance"), 1.0))
        elif kind == "ToEntityExtentDefinition":
            feature_input.setOneSideToExtent(self.one(extent, "entity", component), False)
        else:
            feature_input.setAllExtent(
                enum_value(enum(adsk.fusion, "ExtentDirections"), "PositiveExtentDirection", 0))
        return holes.add(feature_input)

    def _position_hole(self, feature_input, data, component):
        position = data.get("positionDefinition") or {}
        kind = position.get("type")
        if kind == "SketchPointHolePositionDefinition":
            sketch_point = self.one(position, "sketchPoint", component)
            feature_input.setPositionBySketchPoint(sketch_point)
            return
        if kind == "SketchPointsHolePositionDefinition":
            points = self.resolver.resolve_all(position.get("sketchPoints"), component)
            if not points:
                raise Unsupported("hole sketch points could not be resolved")
            feature_input.setPositionBySketchPoints(object_collection(points))
            return
        if kind == "PointAndPlaneHolePositionDefinition":
            feature_input.setPositionByPoint(self.one(position, "planarEntity", component),
                                             self.one(position, "point", component))
            return
        if kind == "PlaneAndOffsetsHolePositionDefinition":
            feature_input.setPositionByPlaneAndOffsets(
                self.one(position, "planarEntity", component),
                point3d(data.get("position")),
                self.one(position, "edgeOne", component),
                self.value(position.get("offsetOne"), 0.0),
                self.one(position, "edgeTwo", component),
                self.value(position.get("offsetTwo"), 0.0))
            return
        raise Unsupported("hole position %s is not in schema 0's mapping"
                          % (kind or "was not exported"))

    def _f_LoftFeature(self, data, component):
        lofts = self.features_of(component).loftFeatures
        sections = self.resolver.resolve_all(data.get("sections"), component)
        if len(sections) < 2:
            raise Unsupported("loft sections were not exported in schema 0")
        feature_input = lofts.createInput(self.operation(data))
        for section in sections:
            feature_input.loftSections.add(section)
        return lofts.add(feature_input)

    # -- dress-up features

    def _edges_of(self, edge_set, component):
        edges = self.resolver.resolve_all(edge_set.get("edges"), component)
        if not edges:
            raise Unsupported("no edge in an edge set could be matched")
        return object_collection(edges)

    def _f_FilletFeature(self, data, component):
        fillets = self.features_of(component).filletFeatures
        feature_input = fillets.createInput()
        sets = probe(feature_input, "edgeSetInputs") or feature_input
        for edge_set in data.get("edgeSets") or []:
            edges = self._edges_of(edge_set, component)
            chain = bool(edge_set.get("tangentChain", True))
            kind = edge_set.get("type") or ""
            if "VariableRadius" in kind:
                sets.addVariableRadiusEdgeSet(edges, self.value(edge_set.get("startRadius"), 0.1),
                                              self.value(edge_set.get("endRadius"), 0.1), chain)
            elif "ChordLength" in kind:
                sets.addChordLengthEdgeSet(edges, self.value(edge_set.get("chordLength"), 0.1), chain)
            else:
                sets.addConstantRadiusEdgeSet(edges, self.value(edge_set.get("radius"), 0.1), chain)
        if not (data.get("edgeSets") or []):
            raise Unsupported("no edge sets in the bundle")
        return fillets.add(feature_input)

    def _f_ChamferFeature(self, data, component):
        chamfers = self.features_of(component).chamferFeatures
        edge_sets = data.get("edgeSets") or []
        if not edge_sets and data.get("edges"):
            edge_sets = [{"type": "EqualDistance", "edges": data.get("edges"),
                          "distance": data.get("distance"),
                          "tangentChain": data.get("tangentChain")}]
        if not edge_sets:
            raise Unsupported("no edge sets in the bundle")
        try:
            feature_input = chamfers.createInput2()
        except Exception:
            return self._legacy_chamfer(chamfers, edge_sets, component)
        sets = probe(feature_input, "chamferEdgeSets") or feature_input
        for edge_set in edge_sets:
            edges = self._edges_of(edge_set, component)
            chain = bool(edge_set.get("tangentChain", True))
            kind = edge_set.get("type") or ""
            if "TwoDistances" in kind:
                sets.addTwoDistancesChamferEdgeSet(edges,
                                                   self.value(edge_set.get("distanceOne"), 0.1),
                                                   self.value(edge_set.get("distanceTwo"), 0.1), chain)
            elif "DistanceAndAngle" in kind:
                sets.addDistanceAndAngleChamferEdgeSet(edges,
                                                       self.value(edge_set.get("distance"), 0.1),
                                                       self.value(edge_set.get("angle"),
                                                                  math.radians(45)), chain)
            else:
                sets.addEqualDistanceChamferEdgeSet(
                    edges, self.value(edge_set.get("distance")
                                      or edge_set.get("distanceOne"), 0.1), chain)
        return chamfers.add(feature_input)

    def _legacy_chamfer(self, chamfers, edge_sets, component):
        """One equal-distance edge set, for a Fusion whose API has no createInput2."""
        first = edge_sets[0]
        feature_input = chamfers.createInput(self._edges_of(first, component),
                                             bool(first.get("tangentChain", True)))
        feature_input.setToEqualDistance(self.value(first.get("distance")
                                                    or first.get("distanceOne"), 0.1))
        if len(edge_sets) > 1:
            self.report.issue("only the first of %d chamfer edge sets was rebuilt"
                              % len(edge_sets), "this Fusion's API takes one set at a time")
        return chamfers.add(feature_input)

    def _f_ShellFeature(self, data, component):
        shells = self.features_of(component).shellFeatures
        entities = self.resolver.resolve_all(data.get("inputEntities"), component)
        if not entities:
            raise Unsupported("no faces or bodies could be matched")
        feature_input = shells.createInput(object_collection(entities),
                                           bool(data.get("tangentChain", True)))
        if data.get("inside"):
            feature_input.insideThickness = self.value(data["inside"])
        if data.get("outside"):
            feature_input.outsideThickness = self.value(data["outside"])
        return shells.add(feature_input)

    def _f_DraftFeature(self, data, component):
        drafts = self.features_of(component).draftFeatures
        faces = self.resolver.resolve_all(data.get("faces"), component)
        if not faces:
            raise Unsupported("no faces could be matched")
        plane = self.one(data, "plane", component)
        feature_input = drafts.createInput(object_collection(faces), plane,
                                           bool(data.get("tangentChain", True)))
        if data.get("angle"):
            try:
                feature_input.angle = self.value(data["angle"])
            except Exception:
                self.report.note("draft angle ignored")
        return drafts.add(feature_input)

    def _f_ThickenFeature(self, data, component):
        thickens = self.features_of(component).thickenFeatures
        faces = self.resolver.resolve_all(data.get("faces"), component)
        if not faces:
            raise Unsupported("no faces could be matched")
        feature_input = thickens.createInput(object_collection(faces),
                                             self.value(data.get("thickness"), 0.1),
                                             bool(data.get("symmetric", False)),
                                             self.operation(data), False)
        return thickens.add(feature_input)

    def _f_OffsetFacesFeature(self, data, component):
        offsets = self.features_of(component).offsetFacesFeatures
        faces = self.resolver.resolve_all(data.get("faces"), component)
        if not faces:
            raise Unsupported("no faces could be matched")
        feature_input = offsets.createInput(object_collection(faces),
                                            self.value(data.get("distance"), 0.1))
        return offsets.add(feature_input)

    # -- body-level features

    def _f_CombineFeature(self, data, component):
        combines = self.features_of(component).combineFeatures
        target = self.one(data, "target", component)
        tools = self.resolver.resolve_all(data.get("tools"), component)
        if not tools:
            raise Unsupported("no tool body could be matched")
        feature_input = combines.createInput(target, object_collection(tools))
        feature_input.operation = self.operation(data, "JoinFeatureOperation")
        if data.get("keepTools") is not None:
            feature_input.isKeepToolBodies = bool(data["keepTools"])
        return combines.add(feature_input)

    def _f_SplitBodyFeature(self, data, component):
        splits = self.features_of(component).splitBodyFeatures
        bodies = self.resolver.resolve_all(data.get("bodies"), component)
        tool = self.one(data, "tool", component)
        if not bodies:
            raise Unsupported("no body to split could be matched")
        feature_input = splits.createInput(
            bodies[0] if len(bodies) == 1 else object_collection(bodies), tool,
            bool(data.get("extendTool", True)))
        return splits.add(feature_input)

    def _f_MirrorFeature(self, data, component):
        mirrors = self.features_of(component).mirrorFeatures
        entities = self.resolver.resolve_all(data.get("inputEntities"), component)
        if not entities:
            raise Unsupported("nothing to mirror could be matched")
        plane = self.one(data, "mirrorPlane", component)
        feature_input = mirrors.createInput(object_collection(entities), plane)
        return mirrors.add(feature_input)

    def _f_MoveFeature(self, data, component):
        moves = self.features_of(component).moveFeatures
        entities = self.resolver.resolve_all(data.get("inputEntities"), component)
        if not entities:
            raise Unsupported("nothing to move could be matched")
        feature_input = moves.createInput(object_collection(entities),
                                          matrix3d(data.get("transform")))
        return moves.add(feature_input)

    def _f_ScaleFeature(self, data, component):
        scales = self.features_of(component).scaleFeatures
        entities = self.resolver.resolve_all(data.get("inputEntities"), component)
        if not entities:
            raise Unsupported("nothing to scale could be matched")
        feature_input = scales.createInput(object_collection(entities),
                                           self.one(data, "point", component),
                                           self.value(data.get("scale"), 1.0))
        return scales.add(feature_input)

    def _f_RectangularPatternFeature(self, data, component):
        patterns = self.features_of(component).rectangularPatternFeatures
        entities = self.resolver.resolve_all(data.get("inputEntities"), component)
        if not entities:
            raise Unsupported("nothing to pattern could be matched")
        distance_type = enum_value(enum(adsk.fusion, "PatternDistanceType"),
                                   data.get("distanceType"), 0)
        feature_input = patterns.createInput(object_collection(entities),
                                             self.one(data, "directionOne", component),
                                             self.value(data.get("quantityOne"), 2),
                                             self.value(data.get("distanceOne"), 1.0),
                                             distance_type)
        if data.get("directionTwo"):
            second = self.one(data, "directionTwo", component, required=False)
            if second is not None:
                feature_input.setDirectionTwo(second, self.value(data.get("quantityTwo"), 1),
                                              self.value(data.get("distanceTwo"), 1.0))
        for key, attribute in (("symmetricOne", "isSymmetricInDirectionOne"),
                               ("symmetricTwo", "isSymmetricInDirectionTwo")):
            if data.get(key) is not None:
                try:
                    setattr(feature_input, attribute, bool(data[key]))
                except Exception:
                    pass
        return patterns.add(feature_input)

    def _f_CircularPatternFeature(self, data, component):
        patterns = self.features_of(component).circularPatternFeatures
        entities = self.resolver.resolve_all(data.get("inputEntities"), component)
        if not entities:
            raise Unsupported("nothing to pattern could be matched")
        feature_input = patterns.createInput(object_collection(entities),
                                             self.one(data, "axis", component))
        if data.get("quantity"):
            feature_input.quantity = self.value(data["quantity"], 2)
        if data.get("totalAngle"):
            feature_input.totalAngle = self.value(data["totalAngle"], 2 * math.pi)
        if data.get("symmetric") is not None:
            feature_input.isSymmetric = bool(data["symmetric"])
        return patterns.add(feature_input)

    # -- construction geometry

    def _f_ConstructionPlane(self, data, component):
        planes = component.constructionPlanes
        feature_input = planes.createInput()
        definition = data.get("definition") or {}
        kind = definition.get("type") or ""
        if "Offset" in kind:
            feature_input.setByOffset(self.one(definition, "planarEntity", component),
                                      self.value(definition.get("offset"), 0.0))
        elif "AtAngle" in kind:
            feature_input.setByAngle(self.one(definition, "linearEntity", component),
                                     self.value(definition.get("angle"), 0.0),
                                     self.one(definition, "planarEntity", component))
        elif "Midplane" in kind:
            feature_input.setByTwoPlanes(self.one(definition, "planeOne", component),
                                         self.one(definition, "planeTwo", component))
        elif "ThreePoints" in kind:
            feature_input.setByThreePoints(self.one(definition, "pointOne", component),
                                           self.one(definition, "pointTwo", component),
                                           self.one(definition, "pointThree", component))
        elif "TwoEdges" in kind:
            feature_input.setByTwoEdges(self.one(definition, "edgeOne", component),
                                        self.one(definition, "edgeTwo", component))
        elif "TangentAtPoint" in kind:
            feature_input.setByTangentAtPoint(self.one(definition, "tangentFace", component),
                                              self.one(definition, "point", component))
        elif "Tangent" in kind:
            feature_input.setByTangent(self.one(definition, "tangentFace", component),
                                       self.value(definition.get("angle"), 0.0),
                                       self.one(definition, "planarEntity", component))
        elif "DistanceOnPath" in kind:
            feature_input.setByDistanceOnPath(self.one(definition, "pathEntity", component),
                                              self.value(definition.get("distance"), 0.5))
        else:
            raise Unsupported("construction plane definition %s" % (kind or "missing"))
        return planes.add(feature_input)

    def _f_ConstructionAxis(self, data, component):
        axes = component.constructionAxes
        feature_input = axes.createInput()
        definition = data.get("definition") or {}
        kind = definition.get("type") or ""
        if "ByLine" in kind:
            feature_input.setByLine(self.one(definition, "linearEntity", component))
        elif "TwoPlanes" in kind:
            feature_input.setByTwoPlanes(self.one(definition, "planeOne", component),
                                         self.one(definition, "planeTwo", component))
        elif "TwoPoints" in kind:
            feature_input.setByTwoPoints(self.one(definition, "pointOne", component),
                                         self.one(definition, "pointTwo", component))
        elif "Edge" in kind:
            feature_input.setByEdge(self.one(definition, "edge", component))
        elif "NormalToFaceAtPoint" in kind:
            feature_input.setByNormalToFaceAtPoint(self.one(definition, "face", component),
                                                   self.one(definition, "point", component))
        elif "Perpendicular" in kind:
            feature_input.setByPerpendicularAtPoint(self.one(definition, "face", component),
                                                    self.one(definition, "point", component))
        elif "CircularFace" in kind:
            feature_input.setByCircularFace(self.one(definition, "circularFace", component))
        else:
            raise Unsupported("construction axis definition %s" % (kind or "missing"))
        return axes.add(feature_input)

    def _f_ConstructionPoint(self, data, component):
        points = component.constructionPoints
        feature_input = points.createInput()
        definition = data.get("definition") or {}
        kind = definition.get("type") or ""
        if "ThreePlanes" in kind:
            feature_input.setByThreePlanes(self.one(definition, "planeOne", component),
                                           self.one(definition, "planeTwo", component),
                                           self.one(definition, "planeThree", component))
        elif "TwoEdges" in kind:
            feature_input.setByTwoEdges(self.one(definition, "edgeOne", component),
                                        self.one(definition, "edgeTwo", component))
        elif "EdgePlane" in kind:
            feature_input.setByEdgePlane(self.one(definition, "edge", component),
                                         self.one(definition, "plane", component))
        elif "Center" in kind:
            feature_input.setByCenter(self.one(definition, "circularEntity", component))
        elif "Point" in kind:
            feature_input.setByPoint(self.one(definition, "point", component))
        else:
            raise Unsupported("construction point definition %s" % (kind or "missing"))
        return points.add(feature_input)
