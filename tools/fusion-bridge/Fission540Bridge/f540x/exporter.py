"""Describes a Fusion design as f540x schema 0 and writes the bundle.

Everything is read through the public Fusion API. Values stay in Fusion's internal
units (cm, radians). Anything that cannot be described is still listed, flagged
"unsupported", and the reason goes to export.log.
"""

import datetime
import json
import os
import tempfile
import traceback
import zipfile

import adsk.core
import adsk.fusion

SCHEMA = "f540x/0"


# ---- small helpers ----------------------------------------------------------------

def short_type(obj):
    """'adsk::fusion::ExtrudeFeature' -> 'ExtrudeFeature'."""
    try:
        return obj.objectType.split("::")[-1]
    except Exception:
        return type(obj).__name__


def probe(obj, attr):
    """Attribute value, or None if this object type does not have it or it is invalid."""
    try:
        return getattr(obj, attr)
    except Exception:
        return None


def point(p):
    return None if p is None else [p.x, p.y, p.z]


def matrix(m):
    return None if m is None else list(m.asArray())


def token(obj):
    return probe(obj, "entityToken")


_enum_names = {}


def enum(module, name):
    """Enum class by name, or None if this Fusion version does not have it."""
    return getattr(module, name, None)


def enum_name(enum_class, value):
    """Fusion enum value -> its API name (falls back to the integer)."""
    if value is None or enum_class is None:
        return value
    key = id(enum_class)
    if key not in _enum_names:
        names = {}
        for name in dir(enum_class):
            if not name.startswith("_"):
                v = getattr(enum_class, name)
                if isinstance(v, int):
                    names.setdefault(v, name)
        _enum_names[key] = names
    return _enum_names[key].get(value, value)


def is_parameter(obj):
    return short_type(obj) in ("ModelParameter", "UserParameter", "Parameter")


def iterate(collection):
    """Items of a Fusion collection (or ObjectCollection / Python list)."""
    if collection is None:
        return []
    if isinstance(collection, (list, tuple)):
        return list(collection)
    count = probe(collection, "count")
    if count is None:
        return [collection]
    return [collection.item(i) for i in range(count)]


class IdMap:
    """Assigns exporter ids ("<prefix><n>") to Fusion objects, keyed by entity token."""

    def __init__(self, prefix):
        self.prefix = prefix
        self.ids = {}

    def get(self, obj, key=None):
        if obj is None:
            return None
        k = key if key is not None else (token(obj) or id(obj))
        if k not in self.ids:
            self.ids[k] = "%s%d" % (self.prefix, len(self.ids))
        return self.ids[k]

    def find(self, obj, key=None):
        if obj is None:
            return None
        return self.ids.get(key if key is not None else token(obj))


class Summary:
    def __init__(self):
        self.counts = {}
        self.warnings = []

    def text(self, path):
        lines = ["Wrote " + path, ""]
        for k, v in self.counts.items():
            lines.append("%s: %d" % (k, v))
        if self.warnings:
            lines.append("")
            lines.append("%d warning(s), see export.log in the bundle. First ones:" % len(self.warnings))
            lines.extend(w.splitlines()[0] for w in self.warnings[:8])
        return "\n".join(lines)


# ---- exporter ---------------------------------------------------------------------

class Exporter:
    def __init__(self, app, design):
        self.app = app
        self.design = design
        self.summary = Summary()
        self.components = IdMap("c")
        self.occurrences = IdMap("o")
        self.sketches = IdMap("s")
        self.sketch_entities = {}  # sketch id -> IdMap of its entities
        self.joints = IdMap("j")
        self.params_by_creator = {}

    def warn(self, what):
        self.summary.warnings.append(what + "\n" + traceback.format_exc())

    # -- references -------------------------------------------------------------

    def param(self, p):
        return probe(p, "name") if p is not None and is_parameter(p) else None

    def component_id(self, comp):
        return self.components.get(comp) if comp is not None else None

    def body_ref_fields(self, body):
        if body is None:
            return {}
        return {"body": probe(body, "name"),
                "component": self.component_id(probe(body, "parentComponent"))}

    def sketch_entity_id(self, entity):
        sketch = probe(entity, "parentSketch")
        if sketch is None:
            return None, None
        sid = self.sketches.get(sketch)
        ids = self.sketch_entities.setdefault(sid, IdMap(sid + "."))
        return sid, ids.get(entity)

    def construction_name(self, obj):
        comp = probe(obj, "component") or probe(obj, "parentComponent")
        if comp is not None:
            origin = {
                "xYConstructionPlane": "XY", "xZConstructionPlane": "XZ", "yZConstructionPlane": "YZ",
                "xConstructionAxis": "X", "yConstructionAxis": "Y", "zConstructionAxis": "Z",
                "originConstructionPoint": "Origin",
            }
            t = token(obj)
            for attr, name in origin.items():
                o = probe(comp, attr)
                if o is not None and t is not None and token(o) == t:
                    return name, comp
        return probe(obj, "name"), comp

    def ref(self, obj):
        if obj is None:
            return None
        if isinstance(obj, (list, tuple)):
            return [self.ref(o) for o in obj]
        t = short_type(obj)
        if t == "ObjectCollection":
            return [self.ref(o) for o in iterate(obj)]
        if t == "Path":
            return [self.ref(probe(e, "entity")) for e in iterate(obj)]
        if t == "BRepFace":
            d = {"kind": "face"}
            d.update(self.body_ref_fields(probe(obj, "body")))
            geom = probe(obj, "geometry")
            p = probe(obj, "pointOnFace")
            d["surface"] = enum_name(enum(adsk.core, "SurfaceTypes"), probe(geom, "surfaceType"))
            d["point"] = point(p)
            d["centroid"] = point(probe(obj, "centroid"))
            d["area"] = probe(obj, "area")
            try:
                ok, normal = obj.evaluator.getNormalAtPoint(p)
                d["normal"] = point(normal) if ok else None
            except Exception:
                d["normal"] = None
            return d
        if t == "BRepEdge":
            d = {"kind": "edge"}
            d.update(self.body_ref_fields(probe(obj, "body")))
            geom = probe(obj, "geometry")
            d["curve"] = enum_name(enum(adsk.core, "Curve3DTypes"), probe(geom, "curveType"))
            d["start"] = point(probe(probe(obj, "startVertex"), "geometry"))
            d["end"] = point(probe(probe(obj, "endVertex"), "geometry"))
            d["point"] = point(probe(obj, "pointOnEdge"))
            d["length"] = probe(obj, "length")
            return d
        if t == "BRepVertex":
            d = {"kind": "vertex"}
            d.update(self.body_ref_fields(probe(obj, "body")))
            d["point"] = point(probe(obj, "geometry"))
            return d
        if t == "BRepBody":
            d = {"kind": "body"}
            d.update(self.body_ref_fields(obj))
            return d
        if t == "Profile":
            sketch = probe(obj, "parentSketch")
            return {"kind": "profile", "sketch": self.sketches.get(sketch) if sketch else None,
                    "loops": self.profile_loops(obj)}
        if t == "Sketch":
            return {"kind": "sketch", "sketch": self.sketches.get(obj)}
        if t.startswith("Sketch") and probe(obj, "parentSketch") is not None:
            sid, eid = self.sketch_entity_id(obj)
            return {"kind": "sketchEntity", "sketch": sid, "entity": eid}
        if t in ("ConstructionPlane", "ConstructionAxis", "ConstructionPoint"):
            name, comp = self.construction_name(obj)
            kind = t[0].lower() + t[1:]
            return {"kind": kind, "name": name, "component": self.component_id(comp)}
        if t == "Occurrence":
            path = probe(obj, "fullPathName")
            return {"kind": "occurrence", "occurrence": self.occurrences.get(obj, key=path)}
        if t == "JointOrigin":
            return {"kind": "jointOrigin", "name": probe(obj, "name")}
        if is_parameter(obj):
            return {"kind": "parameter", "name": probe(obj, "name")}
        return {"kind": "unknown", "type": t, "name": probe(obj, "name")}

    def describe(self, obj, spec):
        """spec: (api attribute, output key, kind); kind is ref|param|value|point|vector|extent|enum class."""
        out = {}
        for attr, key, kind in spec:
            v = probe(obj, attr)
            if v is None:
                continue
            try:
                if kind == "ref":
                    out[key] = self.ref(v)
                elif kind == "param":
                    out[key] = self.param(v)
                elif kind == "value":
                    out[key] = v
                elif kind in ("point", "vector"):
                    out[key] = point(v)
                elif kind == "matrix":
                    out[key] = matrix(v)
                elif kind == "extent":
                    out[key] = self.extent(v)
                elif kind == "paramOrRef":
                    out[key] = self.param(v) if is_parameter(v) else self.ref(v)
                elif kind == "enum" or kind is None:
                    out[key] = v
                else:  # enum class
                    out[key] = enum_name(kind, v)
            except Exception:
                self.warn("could not read %s.%s" % (short_type(obj), attr))
        return out

    def extent(self, definition):
        if definition is None:
            return None
        d = {"type": short_type(definition)}
        d.update(self.describe(definition, [
            ("distance", "distance", "param"),
            ("angle", "angle", "param"),
            ("offset", "offset", "param"),
            ("taperAngle", "taper", "param"),
            ("entity", "entity", "ref"),
            ("isFullLength", "fullLength", "value"),
            ("isSymmetric", "symmetric", "value"),
            ("isChained", "chained", "value"),
            ("isPositiveDirection", "positive", "value"),
        ]))
        return d

    # -- parameters ---------------------------------------------------------------

    def parameters(self):
        units = self.design.unitsManager
        user = []
        for p in iterate(self.design.userParameters):
            user.append({"name": p.name, "expression": p.expression, "value": p.value,
                         "unit": p.unit, "comment": probe(p, "comment") or ""})
        model = []
        for p in iterate(self.design.allParameters):
            if short_type(p) != "ModelParameter":
                continue
            creator = probe(p, "createdBy")
            creator_token = token(creator) if creator is not None else None
            if creator_token is not None:
                self.params_by_creator.setdefault(creator_token, []).append(p.name)
            model.append({"name": p.name, "expression": p.expression, "value": p.value,
                          "unit": p.unit, "role": probe(p, "role"),
                          "createdBy": probe(creator, "name"),
                          "component": self.component_id(probe(p, "component")),
                          "comment": probe(p, "comment") or ""})
        self.summary.counts["parameters"] = len(user) + len(model)
        return user, model, probe(units, "defaultLengthUnits")

    def created_parameters(self, obj):
        t = token(obj)
        return list(self.params_by_creator.get(t, [])) if t is not None else []

    # -- components and occurrences -------------------------------------------------

    def component(self, comp, step_files):
        cid = self.component_id(comp)
        bodies = []
        for body in iterate(comp.bRepBodies):
            props = probe(body, "physicalProperties")
            bodies.append({
                "name": body.name,
                "solid": probe(body, "isSolid"),
                "visible": probe(body, "isVisible"),
                "material": probe(probe(body, "material"), "name"),
                "appearance": probe(probe(body, "appearance"), "name"),
                "volume": probe(props, "volume"),
                "area": probe(props, "area"),
                "faces": probe(probe(body, "faces"), "count"),
                "edges": probe(probe(body, "edges"), "count"),
                "step": step_files.get(cid),
            })

        def construction(collection, kind):
            out = []
            for c in iterate(collection):
                d = {"name": c.name, "visible": probe(c, "isLightBulbOn")}
                defn = probe(c, "definition")
                if defn is not None:
                    d["definition"] = self.construction_definition(defn)
                if kind == "ConstructionPlane":
                    plane = probe(c, "geometry")
                    d["origin"] = point(probe(plane, "origin"))
                    d["normal"] = point(probe(plane, "normal"))
                elif kind == "ConstructionAxis":
                    line = probe(c, "geometry")
                    d["origin"] = point(probe(line, "origin"))
                    d["direction"] = point(probe(line, "direction"))
                else:
                    d["position"] = point(probe(c, "geometry"))
                out.append(d)
            return out

        return {
            "id": cid,
            "name": comp.name,
            "partNumber": probe(comp, "partNumber"),
            "description": probe(comp, "description"),
            "material": probe(probe(comp, "material"), "name"),
            "token": token(comp),
            "bodies": bodies,
            "constructionPlanes": construction(probe(comp, "constructionPlanes"), "ConstructionPlane"),
            "constructionAxes": construction(probe(comp, "constructionAxes"), "ConstructionAxis"),
            "constructionPoints": construction(probe(comp, "constructionPoints"), "ConstructionPoint"),
        }

    def construction_definition(self, defn):
        d = {"type": short_type(defn)}
        attrs = ["offset", "angle", "distance", "planarEntity", "linearEntity", "planeOne",
                 "planeTwo", "pointOne", "pointTwo", "pointThree", "edge", "edgeOne", "edgeTwo",
                 "face", "point", "circularFace", "cylindricalFace", "planeEntity", "pathEntity",
                 "tangentFace", "linearEntityOne", "linearEntityTwo", "vertex", "entity",
                 "entityOne", "entityTwo"]
        d.update(self.describe(defn, [(a, a, "paramOrRef") for a in attrs]))
        return d

    def occurrence(self, occ):
        native = probe(occ, "nativeObject") or occ
        transform = probe(native, "transform2") or probe(native, "transform")
        path = probe(occ, "fullPathName")
        return {
            "id": self.occurrences.get(occ, key=path),
            "name": occ.name,
            "path": path,
            "component": self.component_id(occ.component),
            "transform": matrix(transform),
            "grounded": probe(occ, "isGrounded"),
            "visible": probe(occ, "isLightBulbOn"),
            "children": [self.occurrence(c) for c in iterate(probe(occ, "childOccurrences"))],
        }

    # -- sketches -----------------------------------------------------------------------

    def profile_loops(self, profile):
        loops = []
        for loop in iterate(probe(profile, "profileLoops")):
            curves = []
            for pc in iterate(probe(loop, "profileCurves")):
                entity = probe(pc, "sketchEntity")
                curves.append(self.sketch_entity_id(entity)[1] if entity is not None else None)
            loops.append({"outer": probe(loop, "isOuter"), "curves": curves})
        return loops

    def nurbs(self, geometry):
        try:
            ok, control_points, degree, knots, rational, weights, periodic = geometry.getData()
        except Exception:
            return None
        if not ok:
            return None
        return {"degree": degree, "controlPoints": [point(p) for p in control_points],
                "knots": list(knots), "weights": list(weights) if rational else None,
                "periodic": periodic}

    def sketch_curve(self, sid, ids, curve):
        t = short_type(curve)
        d = {"id": ids.get(curve), "type": t,
             "construction": probe(curve, "isConstruction"),
             "fixed": probe(curve, "isFixed"),
             "reference": probe(curve, "isReference"),
             "fullyConstrained": probe(curve, "isFullyConstrained")}
        pid = lambda p: ids.get(p) if p is not None else None  # noqa: E731
        geometry = probe(curve, "geometry")
        if t == "SketchLine":
            d["start"] = pid(curve.startSketchPoint)
            d["end"] = pid(curve.endSketchPoint)
        elif t == "SketchCircle":
            d["center"] = pid(curve.centerSketchPoint)
            d["radius"] = curve.radius
        elif t == "SketchArc":
            d["center"] = pid(curve.centerSketchPoint)
            d["start"] = pid(curve.startSketchPoint)
            d["end"] = pid(curve.endSketchPoint)
            d["radius"] = curve.radius
            ok, _c, normal, ref_vec, _r, a0, a1 = geometry.getData()
            if ok:
                d.update({"normal": point(normal), "referenceVector": point(ref_vec),
                          "startAngle": a0, "endAngle": a1})
        elif t in ("SketchEllipse", "SketchEllipticalArc"):
            d["center"] = pid(probe(curve, "centerSketchPoint"))
            data = geometry.getData()
            if data[0]:
                d.update({"normal": point(data[2]), "majorAxis": point(data[3]),
                          "majorRadius": data[4], "minorRadius": data[5]})
                if t == "SketchEllipticalArc":
                    d.update({"startAngle": data[6], "endAngle": data[7]})
            if t == "SketchEllipticalArc":
                d["start"] = pid(probe(curve, "startSketchPoint"))
                d["end"] = pid(probe(curve, "endSketchPoint"))
        elif t == "SketchFittedSpline":
            d["fitPoints"] = [pid(p) for p in iterate(probe(curve, "fitPoints"))]
            d["closed"] = probe(curve, "isClosed")
            d["nurbs"] = self.nurbs(geometry)
        elif t == "SketchFixedSpline":
            d["nurbs"] = self.nurbs(geometry)
        elif t == "SketchConicCurve":
            d["start"] = pid(probe(curve, "startSketchPoint"))
            d["end"] = pid(probe(curve, "endSketchPoint"))
            d["apex"] = pid(probe(curve, "apexSketchPoint"))
            d["rho"] = probe(curve, "rhoValue")
        else:
            d["unsupported"] = True
            d["nurbs"] = self.nurbs(geometry)
        return d

    _constraint_attrs = ["point", "entity", "line", "lineOne", "lineTwo", "entityOne", "entityTwo",
                         "curveOne", "curveTwo", "pointOne", "pointTwo", "midPointCurve",
                         "symmetryLine", "circleOne", "circleTwo", "ellipse", "surface"]

    def sketch_relations(self, ids, collection, is_dimension):
        out = []
        for item in iterate(collection):
            t = short_type(item)
            d = {"type": t, "entities": {}}
            for attr in self._constraint_attrs:
                v = probe(item, attr)
                if v is None:
                    continue
                if probe(v, "parentSketch") is not None:
                    d["entities"][attr] = ids.get(v)
                else:
                    d["entities"][attr] = self.ref(v)
            if is_dimension:
                parameter = probe(item, "parameter")
                d["parameter"] = self.param(parameter)
                d["expression"] = probe(parameter, "expression")
                d["value"] = probe(parameter, "value")
                d["driving"] = probe(item, "isDriving")
                orientation = probe(item, "orientation")
                if orientation is not None:
                    d["orientation"] = enum_name(enum(adsk.fusion, "DimensionOrientations"), orientation)
                d["textPosition"] = point(probe(item, "textPosition"))
            else:
                for attr in ("quantity", "quantityOne", "quantityTwo", "distanceOne", "distanceTwo",
                             "totalAngle", "offset", "sides"):
                    v = probe(item, attr)
                    if v is not None:
                        d[attr] = self.param(v) if is_parameter(v) else v
            out.append(d)
        return out

    def sketch(self, sketch):
        sid = self.sketches.get(sketch)
        ids = self.sketch_entities.setdefault(sid, IdMap(sid + "."))
        points = []
        for p in iterate(sketch.sketchPoints):
            points.append({"id": ids.get(p), "position": point(p.geometry),
                           "fixed": probe(p, "isFixed"), "reference": probe(p, "isReference")})
        curves = []
        for c in iterate(sketch.sketchCurves):
            try:
                curves.append(self.sketch_curve(sid, ids, c))
            except Exception:
                self.warn("sketch %s: curve %s" % (sketch.name, short_type(c)))
                curves.append({"id": ids.get(c), "type": short_type(c), "unsupported": True})
        profiles = []
        for profile in iterate(probe(sketch, "profiles")):
            profiles.append({"loops": self.profile_loops(profile)})
        plane = probe(sketch, "referencePlane")
        return {
            "id": sid,
            "name": sketch.name,
            "component": self.component_id(probe(sketch, "parentComponent")),
            "plane": self.ref(plane) if plane is not None else None,
            "transform": matrix(probe(sketch, "transform")),
            "visible": probe(sketch, "isVisible"),
            "points": points,
            "curves": curves,
            "constraints": self.sketch_relations(ids, probe(sketch, "geometricConstraints"), False),
            "dimensions": self.sketch_relations(ids, probe(sketch, "sketchDimensions"), True),
            "profiles": profiles,
        }

    # -- features -----------------------------------------------------------------------

    def feature_spec(self, t):
        ops = enum(adsk.fusion, "FeatureOperations")
        common_pattern = [("inputEntities", "inputEntities", "ref"),
                          ("patternComputeOption", "computeOption",
                           enum(adsk.fusion, "PatternComputeOptions"))]
        specs = {
            "ExtrudeFeature": [
                ("profile", "profile", "ref"), ("operation", "operation", ops),
                ("startExtent", "start", "extent"), ("extentOne", "extentOne", "extent"),
                ("extentTwo", "extentTwo", "extent"), ("taperAngleOne", "taperOne", "param"),
                ("taperAngleTwo", "taperTwo", "param"),
                ("participantBodies", "participantBodies", "ref"),
                ("extentType", "extentType", enum(adsk.fusion, "FeatureExtentTypes"))],
            "RevolveFeature": [
                ("profile", "profile", "ref"), ("axis", "axis", "ref"), ("operation", "operation", ops),
                ("extentDefinition", "extentOne", "extent"), ("extentTwo", "extentTwo", "extent"),
                ("participantBodies", "participantBodies", "ref")],
            "SweepFeature": [
                ("profile", "profile", "ref"), ("path", "path", "ref"), ("guideRail", "guideRail", "ref"),
                ("operation", "operation", ops), ("distanceOne", "distanceOne", "param"),
                ("distanceTwo", "distanceTwo", "param"), ("taperAngle", "taper", "param"),
                ("twistAngle", "twist", "param")],
            "ShellFeature": [
                ("inputEntities", "inputEntities", "ref"), ("insideThickness", "inside", "param"),
                ("outsideThickness", "outside", "param"), ("isTangentChain", "tangentChain", "value")],
            "HoleFeature": [
                ("holeType", "holeType", enum(adsk.fusion, "HoleTypes")), ("position", "position", "point"),
                ("direction", "direction", "vector"), ("holeDiameter", "diameter", "param"),
                ("tipAngle", "tipAngle", "param"), ("counterboreDiameter", "counterboreDiameter", "param"),
                ("counterboreDepth", "counterboreDepth", "param"),
                ("countersinkDiameter", "countersinkDiameter", "param"),
                ("countersinkAngle", "countersinkAngle", "param"),
                ("extentDefinition", "extent", "extent")],
            "CombineFeature": [
                ("targetBody", "target", "ref"), ("toolBodies", "tools", "ref"),
                ("operation", "operation", ops), ("isKeepToolBodies", "keepTools", "value")],
            "MirrorFeature": common_pattern + [("mirrorPlane", "mirrorPlane", "ref")],
            "RectangularPatternFeature": common_pattern + [
                ("directionOneEntity", "directionOne", "ref"), ("directionTwoEntity", "directionTwo", "ref"),
                ("quantityOne", "quantityOne", "param"), ("quantityTwo", "quantityTwo", "param"),
                ("distanceOne", "distanceOne", "param"), ("distanceTwo", "distanceTwo", "param"),
                ("isSymmetricInDirectionOne", "symmetricOne", "value"),
                ("isSymmetricInDirectionTwo", "symmetricTwo", "value"),
                ("patternDistanceType", "distanceType", enum(adsk.fusion, "PatternDistanceType"))],
            "CircularPatternFeature": common_pattern + [
                ("axis", "axis", "ref"), ("quantity", "quantity", "param"),
                ("totalAngle", "totalAngle", "param"), ("isSymmetric", "symmetric", "value")],
            "MoveFeature": [("inputEntities", "inputEntities", "ref"),
                            ("transform", "transform", "matrix")],
            "SplitBodyFeature": [("splitBodies", "bodies", "ref"), ("splittingTool", "tool", "ref"),
                                 ("isSplittingToolExtended", "extendTool", "value")],
            "ThickenFeature": [("inputFaces", "faces", "ref"), ("thickness", "thickness", "param"),
                               ("isSymmetric", "symmetric", "value"), ("operation", "operation", ops)],
            "DraftFeature": [("inputEntities", "faces", "ref"), ("plane", "plane", "ref"),
                             ("isTangentChain", "tangentChain", "value")],
            "ScaleFeature": [("inputEntities", "inputEntities", "ref"), ("point", "point", "ref"),
                             ("scaleFactor", "scale", "param")],
            "OffsetFacesFeature": [("faces", "faces", "ref"), ("distance", "distance", "param")],
            "LoftFeature": [("operation", "operation", ops)],
        }
        return specs.get(t)

    def edge_sets(self, feature):
        out = []
        for es in iterate(probe(feature, "edgeSets")):
            d = {"type": short_type(es)}
            d.update(self.describe(es, [
                ("edges", "edges", "ref"), ("radius", "radius", "param"),
                ("startRadius", "startRadius", "param"), ("endRadius", "endRadius", "param"),
                ("chordLength", "chordLength", "param"), ("distance", "distance", "param"),
                ("distanceOne", "distanceOne", "param"), ("distanceTwo", "distanceTwo", "param"),
                ("angle", "angle", "param"), ("isFlipped", "flipped", "value"),
                ("isTangentChain", "tangentChain", "value")]))
            out.append(d)
        return out

    def feature(self, feature):
        t = short_type(feature)
        d = {"kind": "feature", "type": t, "name": probe(feature, "name"),
             "component": self.component_id(probe(feature, "parentComponent")),
             "health": enum_name(enum(adsk.fusion, "FeatureHealthStates"), probe(feature, "healthState")),
             "message": probe(feature, "errorOrWarningMessage") or "",
             "parameters": self.created_parameters(feature),
             "bodies": [probe(b, "name") for b in iterate(probe(feature, "bodies"))]}
        if t in ("ConstructionPlane", "ConstructionAxis", "ConstructionPoint"):
            defn = probe(feature, "definition")
            d["definition"] = self.construction_definition(defn) if defn is not None else None
            return d
        if t in ("FilletFeature", "ChamferFeature"):
            d["edgeSets"] = self.edge_sets(feature)
            if t == "ChamferFeature" and not d["edgeSets"]:
                d.update(self.describe(feature, [("edges", "edges", "ref"),
                                                 ("isTangentChain", "tangentChain", "value")]))
            return d
        spec = self.feature_spec(t)
        if spec is None:
            d["unsupported"] = True
        else:
            d.update(self.describe(feature, spec))
        return d

    # -- timeline -----------------------------------------------------------------------

    def timeline_entity(self, entity):
        t = short_type(entity)
        if t == "Sketch":
            return {"kind": "sketch", "sketch": self.sketches.get(entity)}
        if t == "Occurrence":
            return {"kind": "occurrence",
                    "occurrence": self.occurrences.get(entity, key=probe(entity, "fullPathName")),
                    "component": self.component_id(probe(entity, "component"))}
        if t in ("Joint", "AsBuiltJoint"):
            return {"kind": "joint", "joint": self.joints.get(entity)}
        if t.endswith("Feature") or t.startswith("Construction"):
            return self.feature(entity)
        return {"kind": "other", "type": t, "name": probe(entity, "name"), "unsupported": True}

    def timeline(self):
        timeline = probe(self.design, "timeline")
        if timeline is None:
            return None
        items, seen = [], set()

        def visit(obj, group):
            index = probe(obj, "index")
            if probe(obj, "isGroup"):
                g = adsk.fusion.TimelineGroup.cast(obj)
                for child in iterate(g):
                    visit(child, probe(g, "name"))
                return
            if index in seen:
                return
            seen.add(index)
            d = {"index": index, "name": probe(obj, "name"),
                 "suppressed": probe(obj, "isSuppressed"),
                 "rolledBack": probe(obj, "isRolledBack"), "group": group}
            try:
                entity = probe(obj, "entity")
                d["entity"] = (self.timeline_entity(entity) if entity is not None
                               else {"kind": "other", "unsupported": True})
            except Exception:
                self.warn("timeline item %s" % d["name"])
                d["entity"] = {"kind": "other", "unsupported": True}
            items.append(d)

        for obj in iterate(timeline):
            visit(obj, None)
        items.sort(key=lambda i: (i["index"] is None, i["index"]))
        self.summary.counts["timeline items"] = len(items)
        return {"markerPosition": probe(timeline, "markerPosition"), "items": items}

    # -- joints -------------------------------------------------------------------------

    def joint_geometry(self, g):
        if g is None:
            return None
        if short_type(g) != "JointGeometry":
            return self.ref(g)
        d = {"origin": point(probe(g, "origin")),
             "primaryAxis": point(probe(g, "primaryAxisVector")),
             "secondaryAxis": point(probe(g, "secondaryAxisVector")),
             "thirdAxis": point(probe(g, "thirdAxisVector")),
             "type": enum_name(enum(adsk.fusion, "JointGeometryTypes"), probe(g, "geometryType")),
             "keyPointType": enum_name(enum(adsk.fusion, "JointKeyPointTypes"), probe(g, "keyPointType"))}
        for attr in ("entityOne", "entityTwo"):
            v = probe(g, attr)
            if v is not None:
                d[attr] = self.ref(v)
        return d

    def limits(self, lim):
        if lim is None:
            return None
        return {k: probe(lim, a) for k, a in (
            ("minEnabled", "isMinimumValueEnabled"), ("min", "minimumValue"),
            ("maxEnabled", "isMaximumValueEnabled"), ("max", "maximumValue"),
            ("restEnabled", "isRestValueEnabled"), ("rest", "restValue"))}

    def joint(self, joint, kind):
        motion = probe(joint, "jointMotion")
        d = {"id": self.joints.get(joint), "name": probe(joint, "name"), "kind": kind,
             "motion": short_type(motion) if motion is not None else None,
             "occurrenceOne": self.ref(probe(joint, "occurrenceOne")),
             "occurrenceTwo": self.ref(probe(joint, "occurrenceTwo")),
             "geometryOne": self.joint_geometry(probe(joint, "geometryOrOriginOne")
                                                or probe(joint, "geometry")),
             "geometryTwo": self.joint_geometry(probe(joint, "geometryOrOriginTwo")),
             "offset": self.param(probe(joint, "offset")),
             "angle": self.param(probe(joint, "angle")),
             "flipped": probe(joint, "isFlipped"),
             "suppressed": probe(joint, "isSuppressed"),
             "parameters": self.created_parameters(joint)}
        if motion is not None:
            values, limits = {}, {}
            for attr in ("rotationValue", "slideValue", "pitchValue", "yawValue", "rollValue",
                         "primarySlideValue", "secondarySlideValue", "pitchValue"):
                v = probe(motion, attr)
                if v is not None:
                    values[attr] = v
            for attr in ("rotationLimits", "slideLimits", "pitchLimits", "yawLimits", "rollLimits",
                         "primarySlideLimits", "secondarySlideLimits"):
                v = probe(motion, attr)
                if v is not None:
                    limits[attr] = self.limits(v)
            for attr in ("rotationAxis", "slideDirection", "normalDirection", "pitchDirection"):
                v = probe(motion, attr)
                if v is not None:
                    values[attr] = enum_name(enum(adsk.fusion, "JointDirections"), v)
            d["values"], d["limits"] = values, limits
        return d

    # -- whole design -------------------------------------------------------------------

    def describe_design(self, step_files):
        design = self.design
        root = design.rootComponent
        self.components.get(root)  # root is c0
        user, model, display = self.parameters()

        components, sketches, joints = [], [], []
        for comp in iterate(design.allComponents):
            try:
                components.append(self.component(comp, step_files))
            except Exception:
                self.warn("component %s" % probe(comp, "name"))
                components.append({"id": self.component_id(comp), "name": probe(comp, "name"),
                                   "unsupported": True})
            for sketch in iterate(probe(comp, "sketches")):
                try:
                    sketches.append(self.sketch(sketch))
                except Exception:
                    self.warn("sketch %s" % probe(sketch, "name"))
                    sketches.append({"id": self.sketches.get(sketch), "name": probe(sketch, "name"),
                                     "unsupported": True})
            for collection, kind in (("joints", "joint"), ("asBuiltJoints", "asBuilt")):
                for j in iterate(probe(comp, collection)):
                    try:
                        joints.append(self.joint(j, kind))
                    except Exception:
                        self.warn("joint %s" % probe(j, "name"))

        occurrences = [self.occurrence(o) for o in iterate(root.occurrences)]
        parametric = design.designType == adsk.fusion.DesignTypes.ParametricDesignType
        timeline = self.timeline() if parametric else None

        self.summary.counts.update({
            "components": len(components),
            "bodies": sum(len(c.get("bodies", [])) for c in components),
            "sketches": len(sketches),
            "joints": len(joints),
        })

        document = probe(design, "parentDocument") or self.app.activeDocument
        data_file = probe(document, "dataFile")
        return {
            "schema": SCHEMA,
            "source": {
                "name": probe(document, "name"),
                "fusionVersion": probe(self.app, "version"),
                "dataFileId": probe(data_file, "id"),
                "version": probe(data_file, "versionNumber"),
                "exported": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "units": {"length": "cm", "angle": "rad", "display": display},
            "designType": "parametric" if parametric else "direct",
            "userParameters": user,
            "modelParameters": model,
            "components": components,
            "rootComponent": self.component_id(root),
            "occurrences": occurrences,
            "sketches": sketches,
            "timeline": timeline,
            "joints": joints,
        }


def _json_default(obj):
    """Fusion objects that slipped into the data: keep their type instead of failing."""
    return {"kind": "unknown", "type": short_type(obj)}


def _export_files(exporter, tmp):
    """STEP per component with bodies, assembly STEP, Fusion archive. Returns {component id: path}."""
    design = exporter.design
    manager = design.exportManager
    step_dir = os.path.join(tmp, "step")
    os.makedirs(step_dir, exist_ok=True)
    step_files = {}

    try:
        manager.execute(manager.createSTEPExportOptions(os.path.join(step_dir, "assembly.step"),
                                                        design.rootComponent))
    except Exception:
        exporter.warn("assembly STEP export")

    for comp in iterate(design.allComponents):
        if probe(probe(comp, "bRepBodies"), "count") in (None, 0):
            continue
        cid = exporter.component_id(comp)
        try:
            manager.execute(manager.createSTEPExportOptions(os.path.join(step_dir, cid + ".step"), comp))
            step_files[cid] = "step/%s.step" % cid
        except Exception:
            exporter.warn("STEP export of component %s" % comp.name)

    try:
        manager.execute(manager.createFusionArchiveExportOptions(os.path.join(tmp, "source.f3d"),
                                                                 design.rootComponent))
    except Exception:
        exporter.warn("Fusion archive export")
    return step_files


def export_design(app, design, path):
    """Writes the design to a .f540x bundle at `path`. Returns a Summary."""
    exporter = Exporter(app, design)
    exporter.components.get(design.rootComponent)  # root is c0, before any STEP file names
    with tempfile.TemporaryDirectory(prefix="f540x-") as tmp:
        step_files = _export_files(exporter, tmp)
        data = exporter.describe_design(step_files)
        with open(os.path.join(tmp, "design.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False, default=_json_default)
        with open(os.path.join(tmp, "export.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(exporter.summary.warnings) + "\n")

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        partial = path + ".partial"
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
            for base, _dirs, files in os.walk(tmp):
                for name in files:
                    full = os.path.join(base, name)
                    z.write(full, os.path.relpath(full, tmp).replace(os.sep, "/"))
        os.replace(partial, path)
    return exporter.summary
