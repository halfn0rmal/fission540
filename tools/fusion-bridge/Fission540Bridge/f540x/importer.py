"""Rebuilds an f540x bundle inside Fusion 360 through the public API.

The design is recreated in a new Fusion document: parameters, components and
occurrences, sketches, then the timeline in order, then joints. Every step is
attempted on its own and failures are collected rather than aborting the import, so
one feature the API cannot express does not cost the rest of the design.

What could not be rebuilt parametrically is listed in the report and, where the
bundle carries a STEP of the component, inserted as a base feature so the geometry
is at least present and visibly frozen.

Values in the bundle are in Fusion's internal units (cm, radians), which is what the
API takes, so nothing is converted here. Compute is deliberately not deferred:
references to faces and edges are matched against the geometry built so far, which
only exists if each feature has actually computed.

This module is the order of events; the parts it drives are `features.py` (one builder
per feature type), `sketches.py` (rebuilding a sketch), `resolve.py` (finding the
geometry a reference describes) and `report.py` (what could not be done).
"""

import datetime
import json
import os
import tempfile
import zipfile

import adsk.core
import adsk.fusion

from .api import (enum, enum_name, enum_value, iterate, mat_apply, mat_multiply,
                  mat_rigid_inverse, matrix, matrix3d, point, probe, relative_difference,
                  short_type, token, value_input)
from .features import FeatureBuilders
from .report import Report, Unsupported
from .resolve import POINT_TOLERANCE, Resolver
from .sketches import SketchBuilder

SUPPORTED_SCHEMAS = ("f540x/0",)

DISTANCE_UNITS = {"mm": "MillimeterDistanceUnits", "cm": "CentimeterDistanceUnits",
                  "m": "MeterDistanceUnits", "in": "InchDistanceUnits",
                  "ft": "FootDistanceUnits"}

class Importer(FeatureBuilders):
    def __init__(self, app, data, bundle_dir=None):
        self.app = app
        self.data = data
        self.bundle_dir = bundle_dir
        self.report = Report()
        self.resolver = Resolver(self)
        self.design = None
        self.root = None
        self.components = {}      # f540x component id -> Component
        self.occurrences = {}     # f540x occurrence id -> Occurrence
        self.sketches = {}        # f540x sketch id -> Sketch
        self.entities = {}        # "s0.3" -> SketchEntity
        self.created = {}         # timeline index -> created object
        self.parameters = {}      # parameter name -> its record from the bundle
        self.known_names = set()  # parameter names that exist in the new design
        self.sketch_data = {}     # f540x sketch id -> its record
        self.built_sketches = set()
        self.unsupported_components = set()

    # ---- helpers the resolver uses ------------------------------------------------

    @staticmethod
    def coords(p):
        return point(p)

    @staticmethod
    def surface_name(value):
        name = enum_name(enum(adsk.core, "SurfaceTypes"), value)
        return name if isinstance(name, str) else None

    @staticmethod
    def curve_name(value):
        name = enum_name(enum(adsk.core, "Curve3DTypes"), value)
        return name if isinstance(name, str) else None

    def find_profile(self, sketch_id, loops):
        """The Profile in a rebuilt sketch whose loops use the same curves as `loops`.

        Fusion recomputes profiles itself, so they are matched by the set of sketch
        curves each loop is made of rather than by any stored identity.
        """
        sketch = self.sketches.get(sketch_id)
        if sketch is None:
            return None
        wanted = self._loop_signature(loops)
        candidates = []
        for profile in iterate(probe(sketch, "profiles")):
            signature = set()
            for loop in iterate(probe(profile, "profileLoops")):
                curves = frozenset(
                    _key(probe(curve, "sketchEntity"))
                    for curve in iterate(probe(loop, "profileCurves"))
                    if probe(curve, "sketchEntity") is not None)
                if curves:
                    signature.add(curves)
            candidates.append((profile, signature))
        for profile, signature in candidates:
            if wanted and signature == wanted:
                return profile
        # A profile whose loops are a superset still bounds the same region when the
        # extra loops are inner ones the exporter listed separately.
        for profile, signature in candidates:
            if wanted and wanted.issubset(signature):
                return profile
        if len(candidates) == 1 and not wanted:
            return candidates[0][0]
        return None

    def _loop_signature(self, loops):
        signature = set()
        for loop in loops or []:
            curves = frozenset(_key(self.entities[c]) for c in loop.get("curves") or []
                               if c in self.entities)
            if curves:
                signature.add(curves)
        return signature

    # ---- parameters ----------------------------------------------------------------

    def value(self, parameter_name, fallback=None, unit=None):
        """ValueInput for a parameter named in the bundle.

        The expression is used when every name it references already exists in the new
        design, so `width / 2` stays parametric; otherwise the exported number is used
        and the loss of the expression is reported.
        """
        record = self.parameters.get(parameter_name) if parameter_name else None
        if record is not None:
            expression = record.get("expression")
            if expression and self.expression_resolvable(expression):
                return value_input(expression)
            if record.get("value") is not None:
                if expression:
                    self.report.issue("parameter %s imported as a number" % parameter_name,
                                      "expression '%s' references names that do not exist here"
                                      % expression)
                return value_input(float(record["value"]))
        if fallback is not None:
            return value_input(float(fallback))
        if parameter_name:
            self.report.issue("parameter %s is not in the bundle" % parameter_name)
        return None

    def expression_resolvable(self, expression):
        for name in _identifiers(expression):
            if name not in self.known_names:
                return False
        return True

    def import_parameters(self):
        for record in self.data.get("userParameters") or []:
            self.parameters[record["name"]] = record
        for record in self.data.get("modelParameters") or []:
            self.parameters.setdefault(record["name"], record)

        # User parameters can reference each other, and the bundle does not record the
        # order they were created in, so keep passing until nothing more can be added.
        # User parameters can reference each other and the bundle does not record the
        # order they were created in, so keep passing over the ones that failed until a
        # pass adds nothing new.
        pending = list(self.data.get("userParameters") or [])
        while pending:
            deferred = []
            for record in pending:
                expression = record.get("expression") or str(record.get("value", 0))
                try:
                    self.design.userParameters.add(record["name"], value_input(expression),
                                                   record.get("unit") or "",
                                                   record.get("comment") or "")
                except Exception:
                    deferred.append(record)
                    continue
                self.known_names.add(record["name"])
                self.report.count("user parameters")
            if len(deferred) == len(pending):
                for record in deferred:
                    self.report.issue("user parameter %s" % record["name"],
                                      "could not be created from '%s'"
                                      % record.get("expression"))
                break
            pending = deferred

    def adopt_parameters(self, feature, names):
        """Give a rebuilt feature's parameters the names the bundle used.

        Downstream expressions in the bundle refer to parameters by name (`d7 + 2 mm`),
        so the names have to come across for those expressions to mean anything.
        """
        if not names or feature is None:
            return
        created = []
        wanted = _key(feature)
        for parameter in iterate(probe(self.design, "allParameters")):
            creator = probe(parameter, "createdBy")
            if creator is not None and _key(creator) == wanted:
                created.append(parameter)
        if len(created) != len(names):
            if names:
                self.report.note("%s created %d parameters, the bundle named %d"
                                 % (probe(feature, "name"), len(created), len(names)))
            return
        for parameter, name in zip(created, names):
            if name in self.known_names:
                continue
            try:
                parameter.name = name
                self.known_names.add(name)
            except Exception:
                self.report.note("could not rename a parameter of %s to %s"
                                 % (probe(feature, "name"), name))

    # ---- components and occurrences -------------------------------------------------

    def import_components(self):
        """Creates every component and occurrence up front.

        Fusion creates a component by creating an occurrence of it, and a feature can
        only be built once its component exists, so the whole tree is made before the
        timeline is replayed rather than at each occurrence's own timeline position.
        """
        root_id = self.data.get("rootComponent")
        if root_id:
            self.components[root_id] = self.root
        by_id = {c.get("id"): c for c in self.data.get("components") or []}
        root_record = by_id.get(root_id)
        if root_record:
            self._apply_component_properties(self.root, root_record)

        def build(records, parent):
            for record in records or []:
                occurrence = None
                component_id = record.get("component")
                transform = matrix3d(record.get("transform"))
                try:
                    existing = self.components.get(component_id)
                    if existing is not None:
                        occurrence = parent.occurrences.addExistingComponent(existing, transform)
                    else:
                        occurrence = parent.occurrences.addNewComponent(transform)
                        component = occurrence.component
                        self.components[component_id] = component
                        properties = by_id.get(component_id)
                        if properties:
                            self._apply_component_properties(component, properties)
                        self.report.count("components")
                except Exception:
                    self.report.failure("occurrence %s" % record.get("name"))
                    continue
                self.occurrences[record.get("id")] = occurrence
                self.report.count("occurrences")
                try:
                    if record.get("name"):
                        occurrence.name = record["name"]
                except Exception:
                    pass
                for attribute, key in (("isGrounded", "grounded"), ("isLightBulbOn", "visible")):
                    if record.get(key) is not None:
                        try:
                            setattr(occurrence, attribute, bool(record[key]))
                        except Exception:
                            pass
                build(record.get("children"), occurrence.component)

        build(self.data.get("occurrences"), self.root)

    def _apply_component_properties(self, component, record):
        for attribute, key in (("name", "name"), ("partNumber", "partNumber"),
                               ("description", "description")):
            value = record.get(key)
            if value in (None, ""):
                continue
            try:
                setattr(component, attribute, value)
            except Exception:
                self.report.note("could not set %s on component %s" % (attribute, record.get("name")))

    # ---- sketches --------------------------------------------------------------------

    def build_sketch(self, sketch_id):
        record = self.sketch_data.get(sketch_id)
        if record is None or sketch_id in self.built_sketches:
            return self.sketches.get(sketch_id)
        self.built_sketches.add(sketch_id)
        component = self.components.get(record.get("component")) or self.root
        plane = self.resolver.resolve(record.get("plane"), component)
        placed_on_fallback = False
        if plane is None:
            plane = probe(component, "xYConstructionPlane")
            placed_on_fallback = True
        sketch = component.sketches.add(plane)
        self.sketches[sketch_id] = sketch
        try:
            if record.get("name"):
                sketch.name = record["name"]
        except Exception:
            pass

        fix = self._sketch_fix(sketch, record, placed_on_fallback)
        positions = {p.get("id"): mat_apply(fix, p.get("position"))
                     for p in record.get("points") or []}
        normal_fix = self._direction_fix(fix)

        pre_existing = list(iterate(probe(sketch, "sketchPoints")))
        builder = SketchBuilder(self, sketch, record, positions, fix, normal_fix,
                                pre_existing)
        builder.build()
        self.report.count("sketches")
        return sketch

    def _sketch_fix(self, sketch, record, placed_on_fallback):
        """Maps the bundle's sketch-space coordinates into the new sketch's space.

        Fusion chooses a sketch's own axes when the sketch is created, which need not
        match the ones the design was exported with. Points are carried through world
        space instead: new = inverse(new sketch transform) * exported transform. The
        result is only used when it keeps the geometry in the sketch plane.
        """
        exported = record.get("transform")
        created = matrix(probe(sketch, "transform"))
        if not exported or not created or len(exported) != 16 or len(created) != 16:
            if placed_on_fallback:
                self.report.issue("sketch %s" % record.get("name"),
                                  "its plane could not be resolved; placed on the XY plane")
            return None
        candidate = mat_multiply(mat_rigid_inverse(created), exported)
        worst = 0.0
        for p in record.get("points") or []:
            mapped = mat_apply(candidate, p.get("position"))
            if mapped is not None:
                worst = max(worst, abs(mapped[2]))
        if worst <= POINT_TOLERANCE:
            return candidate
        self.report.issue(
            "sketch %s" % record.get("name"),
            "its plane does not match the exported one (geometry would be %.4f cm out of plane); "
            "sketch-space coordinates used as they are" % worst)
        return None

    @staticmethod
    def _direction_fix(fix):
        """`fix` as a direction transform: rotation only, no translation."""
        if fix is None:
            return None
        origin = mat_apply(fix, [0.0, 0.0, 0.0])
        return lambda v: None if v is None else [mat_apply(fix, v)[i] - origin[i] for i in range(3)]

    # ---- features ---------------------------------------------------------------------

    def features_of(self, component):
        return probe(component, "features")

    def build_feature(self, data, index):
        feature_type = data.get("type")
        component = self.components.get(data.get("component")) or self.root
        builder = getattr(self, "_f_" + str(feature_type), None)
        if builder is None or data.get("unsupported"):
            self.report.issue("%s '%s' was not rebuilt" % (feature_type, data.get("name")),
                              "schema 0 has no parametric mapping for this feature type")
            self.report.count("features not rebuilt")
            self.unsupported_components.add(data.get("component"))
            return None
        try:
            feature = builder(data, component)
        except Unsupported as why:
            self.report.issue("%s '%s' was not rebuilt" % (feature_type, data.get("name")), why)
            self.report.count("features not rebuilt")
            self.unsupported_components.add(data.get("component"))
            return None
        except Exception:
            self.report.failure("%s '%s'" % (feature_type, data.get("name")))
            self.report.count("features not rebuilt")
            self.unsupported_components.add(data.get("component"))
            return None
        if feature is None:
            return None
        self.report.count("features")
        self.created[index] = feature
        try:
            if data.get("name"):
                feature.name = data["name"]
        except Exception:
            pass
        self.adopt_parameters(feature, data.get("parameters"))
        return feature

    # ---- joints ------------------------------------------------------------------------

    def joint_geometry(self, data, component):
        if not data:
            return None
        entity = None
        for key in ("entityOne", "entityTwo"):
            if data.get(key):
                entity = self.resolver.resolve(data[key], component)
                if entity is not None:
                    break
        if entity is None:
            raise Unsupported("joint geometry entity could not be matched")
        key_point = enum_value(enum(adsk.fusion, "JointKeyPointTypes"),
                               data.get("keyPointType"), 0)
        kind = short_type(entity)
        geometry = adsk.fusion.JointGeometry
        if kind == "BRepFace":
            surface = self.surface_name(probe(probe(entity, "geometry"), "surfaceType"))
            if surface == "PlaneSurfaceType":
                return geometry.createByPlanarFace(entity, None, key_point)
            return geometry.createByNonPlanarFace(entity, key_point)
        if kind == "BRepEdge":
            return geometry.createByCurve(entity, key_point)
        if kind in ("BRepVertex", "SketchPoint", "ConstructionPoint"):
            return geometry.createByPoint(entity)
        if kind.startswith("Sketch"):
            return geometry.createByCurve(entity, key_point)
        raise Unsupported("joint geometry on a %s" % kind)

    def build_joint(self, data):
        occurrence_one = self.resolver.resolve(data.get("occurrenceOne"))
        occurrence_two = self.resolver.resolve(data.get("occurrenceTwo"))
        component = self.components.get(data.get("component")) or self.root
        joints = probe(component, "joints")
        if data.get("kind") == "asBuilt":
            as_built = probe(component, "asBuiltJoints")
            feature_input = as_built.createInput(occurrence_one, occurrence_two, None)
            self._apply_motion(feature_input, data)
            return as_built.add(feature_input)
        geometry_one = self.joint_geometry(data.get("geometryOne"), component)
        geometry_two = self.joint_geometry(data.get("geometryTwo"), component)
        feature_input = joints.createInput(geometry_one, geometry_two)
        self._apply_motion(feature_input, data)
        if data.get("offset"):
            try:
                feature_input.offset = self.value(data["offset"])
            except Exception:
                self.report.note("joint offset ignored for %s" % data.get("name"))
        if data.get("angle"):
            try:
                feature_input.angle = self.value(data["angle"])
            except Exception:
                self.report.note("joint angle ignored for %s" % data.get("name"))
        if data.get("flipped") is not None:
            try:
                feature_input.isFlipped = bool(data["flipped"])
            except Exception:
                pass
        joint = joints.add(feature_input)
        try:
            if data.get("name"):
                joint.name = data["name"]
        except Exception:
            pass
        return joint

    def _apply_motion(self, feature_input, data):
        motion = data.get("motion") or "RigidJointMotion"
        values = data.get("values") or {}
        directions = enum(adsk.fusion, "JointDirections")

        def direction(key, default="ZAxisJointDirection"):
            return enum_value(directions, values.get(key) or default,
                              enum_value(directions, default, 0))

        if motion == "RevoluteJointMotion":
            feature_input.setAsRevoluteJointMotion(direction("rotationAxis"))
        elif motion == "SliderJointMotion":
            feature_input.setAsSliderJointMotion(direction("slideDirection", "XAxisJointDirection"))
        elif motion == "CylindricalJointMotion":
            feature_input.setAsCylindricalJointMotion(direction("rotationAxis"))
        elif motion == "PinSlotJointMotion":
            feature_input.setAsPinSlotJointMotion(direction("rotationAxis"),
                                                  direction("slideDirection", "XAxisJointDirection"))
        elif motion == "PlanarJointMotion":
            feature_input.setAsPlanarJointMotion(direction("normalDirection"))
        elif motion == "BallJointMotion":
            feature_input.setAsBallJointMotion(direction("pitchDirection"),
                                               direction("yawDirection", "XAxisJointDirection"))
        else:
            feature_input.setAsRigidJointMotion()

    # ---- fallback geometry ---------------------------------------------------------------

    def insert_step(self, component_id, step_path, why):
        """Brings a component's exported STEP in as a base feature.

        Used where the parametric rebuild could not reproduce the geometry: the shape is
        present and frozen in the timeline, which is what the plan calls for, and the
        report says why it is frozen.
        """
        component = self.components.get(component_id) or self.root
        base = None
        try:
            base = self.features_of(component).baseFeatures.add()
            base.startEdit()
            options = self.app.importManager.createSTEPImportOptions(step_path)
            try:
                self.app.importManager.importToTarget2(options, component)
            except Exception:
                self.app.importManager.importToTarget(options, component)
            base.finishEdit()
            try:
                base.name = "Fission540 fallback geometry"
            except Exception:
                pass
            self.report.count("STEP fallbacks")
            self.report.issue("component %s uses STEP fallback geometry" % component_id, why)
            return base
        except Exception:
            if base is not None:
                try:
                    base.finishEdit()
                except Exception:
                    pass
            self.report.failure("STEP fallback for component %s" % component_id)
            return None

    def check_geometry(self):
        """Compares rebuilt bodies against the bundle, inserting STEP where they differ."""
        for record in self.data.get("components") or []:
            component_id = record.get("id")
            component = self.components.get(component_id)
            expected = record.get("bodies") or []
            if component is None or not expected:
                continue
            bodies = iterate(probe(component, "bRepBodies"))
            reasons = []
            if len(bodies) != len(expected):
                reasons.append("%d bodies rebuilt, %d in the bundle" % (len(bodies), len(expected)))
            else:
                # Bodies do not have to come back in the bundle's order, so compare the
                # volumes as sets: what matters is that the same solids are there.
                rebuilt = sorted(probe(probe(b, "physicalProperties"), "volume") or 0.0
                                 for b in bodies)
                wanted = sorted(b.get("volume") or 0.0 for b in expected)
                for got, want in zip(rebuilt, wanted):
                    if want and relative_difference(got, want) > 1e-3:
                        reasons.append("a body is %.4f cm3, the bundle has %.4f cm3" % (got, want))
            if not reasons:
                if component_id in self.unsupported_components:
                    self.report.note("component %s matches the bundle despite features that were "
                                     "not rebuilt" % component_id)
                continue
            step = (expected[0] or {}).get("step")
            path = os.path.join(self.bundle_dir, step.replace("/", os.sep)) \
                if (step and self.bundle_dir) else None
            why = "; ".join(reasons)
            if path and os.path.exists(path):
                self.insert_step(component_id, path, why)
            else:
                self.report.issue("component %s does not match the bundle" % component_id,
                                  why + " (no STEP in the bundle to fall back to)")

    # ---- the whole design -------------------------------------------------------------------

    def import_into(self, design):
        schema = self.data.get("schema")
        if schema not in SUPPORTED_SCHEMAS:
            raise Unsupported("bundle schema '%s' is not one this add-in reads (%s)"
                              % (schema, ", ".join(SUPPORTED_SCHEMAS)))
        self.design = design
        self.root = design.rootComponent
        self.unsupported_components = set()

        if self.data.get("designType") != "direct":
            try:
                design.designType = enum_value(enum(adsk.fusion, "DesignTypes"),
                                               "ParametricDesignType", 1)
            except Exception:
                self.report.note("could not switch the document to a parametric design")
        else:
            # The source had no timeline. The new document keeps one anyway: its
            # geometry arrives as base features, which can still be built on.
            self.report.note("the bundle is a direct design; it is rebuilt in a "
                             "parametric document as base features")
        self._apply_units()
        self.import_parameters()
        self.import_components()
        for record in self.data.get("sketches") or []:
            self.sketch_data[record.get("id")] = record

        timeline = self.data.get("timeline") or {}
        items = sorted(timeline.get("items") or [], key=lambda i: i.get("index") or 0)
        for item in items:
            entity = item.get("entity") or {}
            kind = entity.get("kind")
            try:
                if kind == "sketch":
                    self.build_sketch(entity.get("sketch"))
                elif kind == "feature":
                    self.build_feature(entity, item.get("index"))
                elif kind == "joint":
                    pass  # joints are built after the solids they attach to
                elif kind == "occurrence":
                    self.report.count("occurrences from the timeline")
                else:
                    self.report.issue("timeline item '%s' was not rebuilt" % item.get("name"),
                                      "the bundle does not describe it (kind %s)" % kind)
            except Exception:
                self.report.failure("timeline item '%s'" % item.get("name"))

        # Sketches that are not in the timeline (direct designs, or sketches the export
        # could not place in it) still carry geometry worth having.
        for sketch_id in list(self.sketch_data):
            if sketch_id not in self.built_sketches:
                try:
                    self.build_sketch(sketch_id)
                except Exception:
                    self.report.failure("sketch %s" % sketch_id)

        for record in self.data.get("joints") or []:
            try:
                joint = self.build_joint(record)
                if joint is not None:
                    self.report.count("joints")
            except Unsupported as why:
                self.report.issue("joint '%s' was not rebuilt" % record.get("name"), why)
            except Exception:
                self.report.failure("joint '%s'" % record.get("name"))

        self.check_geometry()
        self._suppress(items)
        self._set_marker(timeline)
        return self.report

    def _apply_units(self):
        display = (self.data.get("units") or {}).get("display")
        name = DISTANCE_UNITS.get(display)
        if name is None:
            return
        try:
            units = probe(self.design, "fusionUnitsManager")
            units.distanceDisplayUnits = enum_value(enum(adsk.fusion, "DistanceUnits"), name, 0)
        except Exception:
            self.report.note("could not set the display unit to %s" % display)

    def _suppress(self, items):
        """Suppression is applied last: suppressing early hides geometry later features need."""
        for item in items:
            if not item.get("suppressed"):
                continue
            feature = self.created.get(item.get("index"))
            if feature is None:
                continue
            try:
                feature.isSuppressed = True
                self.report.count("suppressed features")
            except Exception:
                self.report.note("could not suppress %s" % item.get("name"))

    def _set_marker(self, timeline):
        """Puts the rollback marker back where the design was exported with it.

        A marker at the end of the exported timeline means the end of this one too,
        which is not the same number: the rebuilt timeline has a different length, and
        any fallback geometry was appended after the features the bundle listed.
        """
        position = timeline.get("markerPosition")
        if position is None:
            return
        try:
            design_timeline = probe(self.design, "timeline")
            count = probe(design_timeline, "count")
            if not count:
                return
            exported_length = len(timeline.get("items") or [])
            at_end = exported_length and int(position) >= exported_length
            design_timeline.markerPosition = int(count) if at_end \
                else min(int(position), int(count))
        except Exception:
            self.report.note("could not restore the timeline marker position")


def _key(obj):
    """A stable identity for a Fusion entity.

    The API returns a new proxy object every time an entity is asked for, so two
    references to the same face are different Python objects; the entity token is what
    actually identifies it inside the document.
    """
    if obj is None:
        return None
    return token(obj) or id(obj)


def _identifiers(expression):
    """Names an expression refers to, ignoring numbers, units and functions."""
    out, current = [], ""
    for character in str(expression) + " ":
        if character.isalnum() or character in "_":
            current += character
        else:
            if current and not current[0].isdigit():
                out.append(current)
            current = ""
    units = {"mm", "cm", "m", "in", "ft", "deg", "rad", "kg", "g", "lb", "s",
             "sin", "cos", "tan", "asin", "acos", "atan", "sqrt", "abs", "pow",
             "log", "ln", "exp", "min", "max", "pi", "e", "mil", "micron", "nm", "um"}
    return [name for name in out if name.lower() not in units]


# ---- entry points ---------------------------------------------------------------------

def read_bundle(path):
    """design.json out of a .f540x (or .f540) bundle, and the directory it was unpacked to.

    The caller is responsible for cleaning the directory up; it holds the STEP files the
    import falls back to, so it has to outlive reading the JSON.
    """
    directory = tempfile.mkdtemp(prefix="f540x-import-")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if "design.json" not in names:
            raise Unsupported("%s has no design.json, so it is not a bundle this add-in reads"
                              % os.path.basename(path))
        archive.extractall(directory)
    with open(os.path.join(directory, "design.json"), "r", encoding="utf-8") as f:
        return json.load(f), directory


def import_bundle(app, path, document=None):
    """Reads a bundle and rebuilds it in a new Fusion document. Returns a Report."""
    data, directory = read_bundle(path)
    if document is None:
        document = app.documents.add(
            enum_value(enum(adsk.core, "DocumentTypes"), "FusionDesignDocumentType", 0))
    design = document.products.itemByProductType("DesignProductType")
    if design is None:
        raise Unsupported("the new document has no design in it")
    importer = Importer(app, data, directory)
    report = importer.import_into(design)
    report.count("bundle schema 0 designs")
    source = (data.get("source") or {}).get("name")
    if source:
        try:
            document.name = source
        except Exception:
            pass
    report.log.insert(0, "Fission540 import of %s at %s"
                      % (os.path.basename(path),
                         datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return report, directory


def write_log(path, report):
    """Writes the import log beside the bundle; returns where it went, or None."""
    log_path = os.path.splitext(path)[0] + "-import.log"
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(report.log_text())
        return log_path
    except Exception:
        return None
