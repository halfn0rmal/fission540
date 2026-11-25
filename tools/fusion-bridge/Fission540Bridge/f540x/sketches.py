"""Rebuilds one sketch from its f540x description.

Sketch geometry is the part of a design most likely to come back subtly wrong, so two
things are handled explicitly here: points are shared between curves that the bundle
says share them (otherwise the sketch falls apart as soon as a dimension changes), and
coordinates are mapped into whatever axes Fusion chose for the new sketch.
"""

import math

import adsk.core
import adsk.fusion

from .api import (add, cross, distance, enum, enum_value, iterate, mat_apply, normalize,
                  nurbs_curve, object_collection, point, point3d, probe)
from .report import Unsupported
from .resolve import POINT_TOLERANCE

# Geometric constraint type -> (method on GeometricConstraints, entity keys in order).
CONSTRAINTS = {
    "HorizontalConstraint": ("addHorizontal", ["line"]),
    "VerticalConstraint": ("addVertical", ["line"]),
    "HorizontalPointsConstraint": ("addHorizontalPoints", ["pointOne", "pointTwo"]),
    "VerticalPointsConstraint": ("addVerticalPoints", ["pointOne", "pointTwo"]),
    "CoincidentConstraint": ("addCoincident", ["point", "entity"]),
    "ParallelConstraint": ("addParallel", ["lineOne", "lineTwo"]),
    "PerpendicularConstraint": ("addPerpendicular", ["lineOne", "lineTwo"]),
    "CollinearConstraint": ("addCollinear", ["lineOne", "lineTwo"]),
    "TangentConstraint": ("addTangent", ["curveOne", "curveTwo"]),
    "EqualConstraint": ("addEqual", ["curveOne", "curveTwo"]),
    "ConcentricConstraint": ("addConcentric", ["entityOne", "entityTwo"]),
    "MidPointConstraint": ("addMidPoint", ["point", "midPointCurve"]),
    "SymmetryConstraint": ("addSymmetry", ["entityOne", "entityTwo", "symmetryLine"]),
    "SmoothConstraint": ("addSmooth", ["curveOne", "curveTwo"]),
}

# Sketch dimension type -> (method on SketchDimensions, entity keys, takes orientation).
DIMENSIONS = {
    "SketchLinearDimension": ("addDistanceDimension", ["entityOne", "entityTwo"], True),
    "SketchOffsetDimension": ("addOffsetDimension", ["line", "entityTwo"], False),
    "SketchDiameterDimension": ("addDiameterDimension", ["entity"], False),
    "SketchRadialDimension": ("addRadialDimension", ["entity"], False),
    "SketchAngularDimension": ("addAngularDimension", ["lineOne", "lineTwo"], False),
    "SketchConcentricCircleDimension": ("addConcentricCircleDimension",
                                        ["circleOne", "circleTwo"], False),
    "SketchEllipseMajorRadiusDimension": ("addEllipseMajorRadiusDimension", ["ellipse"], False),
    "SketchEllipseMinorRadiusDimension": ("addEllipseMinorRadiusDimension", ["ellipse"], False),
}


class SketchBuilder:
    """Rebuilds one sketch's points, curves, constraints and dimensions."""

    def __init__(self, owner, sketch, record, positions, fix, direction, pre_existing):
        self.owner = owner
        self.report = owner.report
        self.sketch = sketch
        self.record = record
        self.positions = positions
        self.fix = fix
        self.direction = direction or (lambda v: v)
        self.pre_existing = pre_existing
        self.points = {}  # f540x point id -> SketchPoint

    # -- points

    def position(self, point_id):
        return self.positions.get(point_id)

    def existing_at(self, coords):
        """A sketch point Fusion already made (the origin) at these coordinates."""
        for candidate in self.pre_existing:
            if distance(point(probe(candidate, "geometry")), coords) <= POINT_TOLERANCE:
                return candidate
        return None

    def point_input(self, point_id):
        """An existing SketchPoint for this id if there is one, else a Point3D."""
        if point_id in self.points:
            return self.points[point_id]
        coords = self.position(point_id)
        if coords is None:
            return None
        found = self.existing_at(coords)
        if found is not None:
            self.adopt(point_id, found)
            return found
        return point3d(coords)

    def adopt(self, point_id, sketch_point):
        """Binds an exported point id to the sketch point that now stands for it.

        Both maps are written: the local one so curves sharing the point share it here
        too, and the importer's so a feature elsewhere in the bundle (a hole placed on
        a sketch point, say) can still refer to it.
        """
        if point_id and sketch_point is not None and point_id not in self.points:
            self.points[point_id] = sketch_point
            self.owner.entities[point_id] = sketch_point

    # -- build

    def build(self):
        curves = self.record.get("curves") or []
        for data in curves:
            try:
                self.build_curve(data)
            except Unsupported as why:
                self.report.issue("sketch %s: %s was not rebuilt"
                                  % (self.record.get("name"), data.get("type")), why)
            except Exception:
                self.report.failure("sketch %s: %s" % (self.record.get("name"), data.get("type")))
        self.build_points()
        self.build_dimensions()
        self.build_constraints()
        references = sum(1 for c in curves if c.get("reference"))
        if references:
            self.report.note("sketch %s: %d projected entities were rebuilt as ordinary sketch "
                             "geometry (they will not follow the model)"
                             % (self.record.get("name"), references))

    def build_points(self):
        """Any exported point no curve created: standalone sketch points."""
        for data in self.record.get("points") or []:
            point_id = data.get("id")
            if point_id in self.points:
                continue
            coords = self.position(point_id)
            if coords is None:
                continue
            found = self.existing_at(coords)
            if found is not None:
                self.adopt(point_id, found)
                continue
            try:
                self.adopt(point_id, self.sketch.sketchPoints.add(point3d(coords)))
            except Exception:
                self.report.failure("sketch %s: point %s"
                                    % (self.record.get("name"), point_id))

    def build_curve(self, data):
        kind = data.get("type")
        curves = self.sketch.sketchCurves
        created = None
        if kind == "SketchLine":
            start, end = self.point_input(data.get("start")), self.point_input(data.get("end"))
            if start is None or end is None:
                raise Unsupported("an end point is missing from the bundle")
            created = curves.sketchLines.addByTwoPoints(start, end)
            self.adopt(data.get("start"), probe(created, "startSketchPoint"))
            self.adopt(data.get("end"), probe(created, "endSketchPoint"))
        elif kind == "SketchCircle":
            center = self.point_input(data.get("center"))
            if center is None or data.get("radius") is None:
                raise Unsupported("centre or radius is missing from the bundle")
            created = curves.sketchCircles.addByCenterRadius(center, float(data["radius"]))
            self.adopt(data.get("center"), probe(created, "centerSketchPoint"))
        elif kind == "SketchArc":
            created = self.build_arc(data)
        elif kind == "SketchEllipse":
            created = self.build_ellipse(data)
        elif kind == "SketchFittedSpline":
            created = self.build_fitted_spline(data)
        else:
            created = self.build_from_nurbs(data)
        if created is None:
            raise Unsupported("no way to rebuild a %s in schema 0" % kind)
        self.owner.entities[data.get("id")] = created
        for attribute, key in (("isConstruction", "construction"), ("isFixed", "fixed")):
            if data.get(key):
                try:
                    setattr(created, attribute, True)
                except Exception:
                    pass
        self.report.count("sketch curves")
        return created

    def build_arc(self, data):
        """Three points, so the arc's own orientation does not have to be reasoned about.

        The mid point is taken from the arc's exported frame (centre, reference vector,
        normal, start and end angle), which fixes the direction unambiguously; only if
        that frame is missing does it fall back to bisecting the chord.
        """
        start, end = self.point_input(data.get("start")), self.point_input(data.get("end"))
        center = self.position(data.get("center"))
        radius = data.get("radius")
        if start is None or end is None or center is None or radius is None:
            raise Unsupported("the arc's points are missing from the bundle")
        middle = self.arc_mid_point(data, center, float(radius))
        created = self.sketch.sketchCurves.sketchArcs.addByThreePoints(start, point3d(middle), end)
        self.adopt(data.get("start"), probe(created, "startSketchPoint"))
        self.adopt(data.get("end"), probe(created, "endSketchPoint"))
        center_id = data.get("center")
        if center_id in self.points:
            try:  # keep the shared centre point and the arc's own centre together
                self.sketch.geometricConstraints.addCoincident(
                    self.points[center_id], probe(created, "centerSketchPoint"))
            except Exception:
                self.report.note("sketch %s: arc centre left unconstrained"
                                 % self.record.get("name"))
        else:
            self.adopt(center_id, probe(created, "centerSketchPoint"))
        return created

    def arc_mid_point(self, data, center, radius):
        reference = normalize(self.direction(data.get("referenceVector")) or [])
        normal = normalize(self.direction(data.get("normal")) or [])
        start_angle, end_angle = data.get("startAngle"), data.get("endAngle")
        if reference and normal and start_angle is not None and end_angle is not None:
            sweep = (end_angle - start_angle) % (2 * math.pi)
            angle = start_angle + sweep / 2.0
            perpendicular = cross(normal, reference)
            offset = [math.cos(angle) * reference[i] + math.sin(angle) * perpendicular[i]
                      for i in range(3)]
            return add(center, offset, radius)
        start = self.position(data.get("start"))
        end = self.position(data.get("end"))
        chord_mid = [(start[i] + end[i]) / 2.0 for i in range(3)]
        outward = normalize([chord_mid[i] - center[i] for i in range(3)])
        if outward is None:  # a half circle: any perpendicular direction will do
            outward = normalize(cross([0.0, 0.0, 1.0], [end[i] - start[i] for i in range(3)]))
        self.report.note("sketch %s: an arc was rebuilt from its chord; check its direction"
                         % self.record.get("name"))
        return add(center, outward or [1.0, 0.0, 0.0], radius)

    def build_ellipse(self, data):
        center = self.position(data.get("center"))
        major = normalize(self.direction(data.get("majorAxis")) or [])
        major_radius, minor_radius = data.get("majorRadius"), data.get("minorRadius")
        if center is None or not major or major_radius is None or minor_radius is None:
            return self.build_from_nurbs(data)
        normal = normalize(self.direction(data.get("normal")) or []) or [0.0, 0.0, 1.0]
        minor = normalize(cross(normal, major)) or [0.0, 1.0, 0.0]
        created = self.sketch.sketchCurves.sketchEllipses.add(
            point3d(center), point3d(add(center, major, float(major_radius))),
            point3d(add(center, minor, float(minor_radius))))
        self.adopt(data.get("center"), probe(created, "centerSketchPoint"))
        return created

    def build_fitted_spline(self, data):
        fit_points = [self.point_input(p) for p in data.get("fitPoints") or []]
        fit_points = [p for p in fit_points if p is not None]
        if len(fit_points) < 2:
            return self.build_from_nurbs(data)
        created = self.sketch.sketchCurves.sketchFittedSplines.add(object_collection(fit_points))
        if data.get("closed"):
            try:
                created.isClosed = True
            except Exception:
                pass
        for point_id, sketch_point in zip(data.get("fitPoints") or [],
                                          iterate(probe(created, "fitPoints"))):
            self.adopt(point_id, sketch_point)
        return created

    def build_from_nurbs(self, data):
        """Last resort for curve types with no constructor here: a fixed spline.

        The shape is exact but the curve is not editable, which the report says.
        """
        nurbs = data.get("nurbs")
        if not nurbs:
            return None
        if self.fix is not None:
            nurbs = dict(nurbs)
            nurbs["controlPoints"] = [mat_apply(self.fix, p)
                                      for p in nurbs.get("controlPoints") or []]
        curve = nurbs_curve(nurbs)
        if curve is None:
            return None
        created = self.sketch.sketchCurves.sketchFixedSplines.addByNurbsCurve(curve)
        self.report.note("sketch %s: a %s was rebuilt as a fixed spline"
                         % (self.record.get("name"), data.get("type")))
        return created

    # -- constraints and dimensions

    def entity(self, value):
        """A constraint or dimension operand: a sketch entity id, or a model reference."""
        if isinstance(value, str):
            return self.points.get(value) or self.owner.entities.get(value)
        if isinstance(value, dict):
            return self.owner.resolver.resolve(value, probe(self.sketch, "parentComponent"))
        return None

    def build_constraints(self):
        for data in self.record.get("constraints") or []:
            kind = data.get("type")
            mapping = CONSTRAINTS.get(kind)
            if mapping is None:
                self.report.issue("sketch %s: %s was not rebuilt"
                                  % (self.record.get("name"), kind),
                                  "schema 0 has no mapping for this constraint")
                continue
            method_name, keys = mapping
            entities = [self.entity((data.get("entities") or {}).get(key)) for key in keys]
            if any(e is None for e in entities):
                self.report.issue("sketch %s: %s was not rebuilt"
                                  % (self.record.get("name"), kind),
                                  "one of its entities is missing")
                continue
            try:
                getattr(self.sketch.geometricConstraints, method_name)(*entities)
                self.report.count("sketch constraints")
            except Exception:
                self.report.failure("sketch %s: %s" % (self.record.get("name"), kind))

    def build_dimensions(self):
        orientations = enum(adsk.fusion, "DimensionOrientations")
        for data in self.record.get("dimensions") or []:
            kind = data.get("type")
            mapping = DIMENSIONS.get(kind)
            if mapping is None:
                self.report.issue("sketch %s: %s was not rebuilt"
                                  % (self.record.get("name"), kind),
                                  "schema 0 has no mapping for this dimension")
                continue
            method_name, keys, takes_orientation = mapping
            entities = [self.entity((data.get("entities") or {}).get(key)) for key in keys]
            if any(e is None for e in entities):
                self.report.issue("sketch %s: %s was not rebuilt"
                                  % (self.record.get("name"), kind),
                                  "one of its entities is missing")
                continue
            text_point = point3d(mat_apply(self.fix, data.get("textPosition"))
                                 or [0.0, 0.0, 0.0])
            arguments = list(entities)
            if takes_orientation:
                arguments.append(enum_value(orientations, data.get("orientation"), 0))
            arguments.append(text_point)
            try:
                dimension = getattr(self.sketch.sketchDimensions, method_name)(*arguments)
                self.report.count("sketch dimensions")
            except Exception:
                self.report.failure("sketch %s: %s" % (self.record.get("name"), kind))
                continue
            self.apply_dimension_value(dimension, data)

    def apply_dimension_value(self, dimension, data):
        parameter = probe(dimension, "parameter")
        name = data.get("parameter")
        expression = data.get("expression")
        if parameter is None:
            return
        if expression and self.owner.expression_resolvable(expression):
            try:
                parameter.expression = expression
            except Exception:
                self.report.note("could not set a dimension to '%s'" % expression)
        elif data.get("value") is not None:
            try:
                parameter.value = float(data["value"])
            except Exception:
                self.report.note("could not set a dimension to %s" % data["value"])
            if expression:
                self.report.issue("sketch %s: dimension kept as a number"
                                  % self.record.get("name"),
                                  "expression '%s' references names that do not exist here"
                                  % expression)
        if name:
            try:
                if name not in self.owner.known_names:
                    parameter.name = name
                    self.owner.known_names.add(name)
            except Exception:
                pass
        if data.get("driving") is False:
            try:
                dimension.isDriving = False
            except Exception:
                pass
