"""Mock of the slice of the Fusion API the bridge uses, so it can be tested on Linux.

`install()` registers fake `adsk`, `adsk.core` and `adsk.fusion` modules; it has to run
before the add-in's modules are imported. `make_design()` builds a design for the
exporter to read, `FakeApp` a Fusion session for the importer to build into.

The mocks are only as faithful as reading the API documentation makes them: they catch
Python errors, wrong call shapes and wrong logic, not Fusion behaving differently from
its documentation. Whether the add-in works is settled by running it in Fusion.
"""

import math
import sys
import types


# ---- enums and value types ---------------------------------------------------------

class SurfaceTypes:
    PlaneSurfaceType = 0
    CylinderSurfaceType = 1
    ConeSurfaceType = 2
    SphereSurfaceType = 3
    TorusSurfaceType = 4
    NurbsSurfaceType = 6


class Curve3DTypes:
    Line3DCurveType = 0
    Arc3DCurveType = 1
    Circle3DCurveType = 2
    Ellipse3DCurveType = 3
    EllipticalArc3DCurveType = 4
    NurbsCurve3DCurveType = 5


class FeatureOperations:
    JoinFeatureOperation = 0
    CutFeatureOperation = 1
    IntersectFeatureOperation = 2
    NewBodyFeatureOperation = 3
    NewComponentFeatureOperation = 4


class FeatureHealthStates:
    HealthyFeatureHealthState = 0
    WarningFeatureHealthState = 1
    ErrorFeatureHealthState = 2


class DimensionOrientations:
    AlignedDimensionOrientation = 0
    HorizontalDimensionOrientation = 1
    VerticalDimensionOrientation = 2


class DesignTypes:
    DirectDesignType = 0
    ParametricDesignType = 1


class DocumentTypes:
    FusionDesignDocumentType = 0


class ExtentDirections:
    PositiveExtentDirection = 0
    NegativeExtentDirection = 1
    SymmetricExtentDirection = 2


class DistanceUnits:
    MillimeterDistanceUnits = 0
    CentimeterDistanceUnits = 1
    MeterDistanceUnits = 2
    InchDistanceUnits = 3
    FootDistanceUnits = 4


class PatternDistanceType:
    ExtentPatternDistanceType = 0
    SpacingPatternDistanceType = 1


class PatternComputeOptions:
    AdjustPatternCompute = 0
    IdenticalPatternCompute = 1


class FeatureExtentTypes:
    OneSideFeatureExtentType = 0
    TwoSidesFeatureExtentType = 1
    SymmetricFeatureExtentType = 2


class HoleTypes:
    SimpleHoleType = 0
    CounterboreHoleType = 1
    CountersinkHoleType = 2


class JointDirections:
    XAxisJointDirection = 0
    YAxisJointDirection = 1
    ZAxisJointDirection = 2
    CustomJointDirection = 3


class JointKeyPointTypes:
    StartKeyPoint = 0
    MiddleKeyPoint = 1
    EndKeyPoint = 2
    CenterKeyPoint = 3


class JointGeometryTypes:
    JointPlanarBRepFaceGeometry = 0
    JointPointGeometry = 1


class ChainedCurveOptions:
    noChainedCurves = 0
    connectedChainedCurves = 1
    tangentChainedCurves = 2


class TimelineGroup:
    @staticmethod
    def cast(obj):
        return obj


class Point3D:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    @staticmethod
    def create(x=0.0, y=0.0, z=0.0):
        return Point3D(x, y, z)

    def asArray(self):
        return (self.x, self.y, self.z)

    def copy(self):
        return Point3D(self.x, self.y, self.z)

    def __repr__(self):
        return "Point3D(%g, %g, %g)" % (self.x, self.y, self.z)


class Vector3D(Point3D):
    @staticmethod
    def create(x=0.0, y=0.0, z=0.0):
        return Vector3D(x, y, z)


IDENTITY = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


class Matrix3D:
    def __init__(self, values=IDENTITY):
        self._values = tuple(float(v) for v in values)

    @staticmethod
    def create():
        return Matrix3D()

    def asArray(self):
        return self._values

    def setWithArray(self, values):
        if len(values) != 16:
            raise ValueError("a 4x4 matrix needs 16 values")
        self._values = tuple(float(v) for v in values)
        return True


class ValueInput:
    def __init__(self, expression=None, real=None):
        self.expression, self.real = expression, real

    @staticmethod
    def createByString(expression):
        return ValueInput(expression=expression)

    @staticmethod
    def createByReal(real):
        return ValueInput(real=float(real))

    def __repr__(self):
        return "ValueInput(%r)" % (self.expression if self.real is None else self.real)


class ObjectCollection:
    def __init__(self, items=()):
        self._items = list(items)

    @staticmethod
    def create():
        return ObjectCollection()

    @property
    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]

    def add(self, item):
        self._items.append(item)
        return True

    def __iter__(self):
        return iter(self._items)


class NurbsCurve3D:
    def __init__(self, control_points, degree, knots, weights, periodic):
        self.controlPoints = list(control_points)
        self.degree = degree
        self.knots = list(knots)
        self.weights = list(weights) if weights else None
        self.isPeriodic = periodic
        self.objectType = "adsk::core::NurbsCurve3D"

    @staticmethod
    def createNonRational(points, degree, knots, periodic):
        return NurbsCurve3D(points, degree, knots, None, periodic)

    @staticmethod
    def createRational(points, degree, knots, weights, periodic):
        return NurbsCurve3D(points, degree, knots, weights, periodic)


class _StartDefinition:
    def __init__(self, kind, entity=None, offset=None):
        self.kind, self.entity, self.offset = kind, entity, offset


class ProfilePlaneStartDefinition:
    @staticmethod
    def create():
        return _StartDefinition("profilePlane")


class OffsetStartDefinition:
    @staticmethod
    def create(offset):
        return _StartDefinition("offset", offset=offset)


class EntityStartDefinition:
    @staticmethod
    def create(entity, offset):
        return _StartDefinition("entity", entity=entity, offset=offset)


class Path:
    def __init__(self, curves):
        self.curves = curves
        self.objectType = "adsk::fusion::Path"

    @staticmethod
    def create(curves, chain_option):
        return Path(curves)


class JointGeometry:
    def __init__(self, kind, entity):
        self.kind, self.entity = kind, entity
        self.objectType = "adsk::fusion::JointGeometry"

    @staticmethod
    def createByPlanarFace(face, edge, key_point):
        return JointGeometry("planarFace", face)

    @staticmethod
    def createByNonPlanarFace(face, key_point):
        return JointGeometry("nonPlanarFace", face)

    @staticmethod
    def createByCurve(curve, key_point):
        return JointGeometry("curve", curve)

    @staticmethod
    def createByPoint(point):
        return JointGeometry("point", point)


# ---- the add-in's own surface: event handlers and the panel it adds buttons to --------

class _EventHandlerBase:
    """Stands in for adsk.core.*EventHandler, which add-in handlers subclass."""

    def __init__(self):
        pass


class CommandCreatedEventHandler(_EventHandlerBase):
    pass


class CommandEventHandler(_EventHandlerBase):
    pass


class DialogResults:
    DialogOK = 0
    DialogCancel = 1


class _Event:
    def __init__(self):
        self.handlers = []

    def add(self, handler):
        self.handlers.append(handler)
        return True


class _CommandDefinition:
    def __init__(self, cmd_id, name, tooltip):
        self.id = cmd_id
        self.name = name
        self.tooltip = tooltip
        self.commandCreated = _Event()
        self.deleted = False

    def deleteMe(self):
        self.deleted = True
        return True


class _Keyed:
    """A collection addressed by id, like Fusion's command definitions and controls."""

    def __init__(self):
        self.items = {}

    def itemById(self, key):
        return self.items.get(key)


class _CommandDefinitions(_Keyed):
    def addButtonDefinition(self, cmd_id, name, tooltip):
        definition = _CommandDefinition(cmd_id, name, tooltip)
        self.items[cmd_id] = definition
        return definition


class _Controls(_Keyed):
    def addCommand(self, definition):
        self.items[definition.id] = definition
        return definition


class _Panel:
    def __init__(self, panel_id):
        self.id = panel_id
        self.controls = _Controls()


class Application:
    """adsk.core.Application: the add-in's way in. `current` is the session it gets."""

    current = None

    @staticmethod
    def get():
        if Application.current is None:
            Application.current = FakeApp()
        return Application.current


class FakeUserInterface:
    def __init__(self, panel_id="SolidScriptsAddinsPanel"):
        self.commandDefinitions = _CommandDefinitions()
        self.allToolbarPanels = _Keyed()
        self.allToolbarPanels.items[panel_id] = _Panel(panel_id)
        self.messages = []

    def messageBox(self, text, title=""):
        self.messages.append((title, text))
        return True


_ADSK_CORE = [SurfaceTypes, Curve3DTypes, DocumentTypes, Point3D, Vector3D, Matrix3D,
              ValueInput, ObjectCollection, NurbsCurve3D, DialogResults, Application,
              CommandCreatedEventHandler, CommandEventHandler]
_ADSK_FUSION = [FeatureOperations, FeatureHealthStates, DimensionOrientations, DesignTypes,
                ExtentDirections, DistanceUnits, PatternDistanceType, PatternComputeOptions,
                FeatureExtentTypes, HoleTypes, JointDirections, JointKeyPointTypes,
                JointGeometryTypes, ChainedCurveOptions, TimelineGroup, Path, JointGeometry,
                ProfilePlaneStartDefinition, OffsetStartDefinition, EntityStartDefinition]


def install():
    """Registers the mock adsk modules; call before importing the add-in's modules."""
    adsk = sys.modules.get("adsk") or types.ModuleType("adsk")
    core = sys.modules.get("adsk.core") or types.ModuleType("adsk.core")
    fusion = sys.modules.get("adsk.fusion") or types.ModuleType("adsk.fusion")
    for cls in _ADSK_CORE:
        setattr(core, cls.__name__, cls)
    for cls in _ADSK_FUSION:
        setattr(fusion, cls.__name__, cls)
    adsk.core, adsk.fusion = core, fusion
    sys.modules.update({"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})
    return adsk


# ---- objects for the exporter to read ------------------------------------------------

class Obj:
    """An object that answers like a Fusion API object of the given type."""

    _n = 0

    def __init__(self, type_name, **attrs):
        Obj._n += 1
        self.objectType = "adsk::fusion::" + type_name
        self.entityToken = "tok%d" % Obj._n
        self.__dict__.update(attrs)


class Coll:
    def __init__(self, items):
        self._items = list(items)

    @property
    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]

    def itemByName(self, name):
        for item in self._items:
            if getattr(item, "name", None) == name:
                return item
        return None

    def add(self, item):
        self._items.append(item)
        return item

    def __iter__(self):
        return iter(self._items)


class P:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class M:
    def __init__(self, values=IDENTITY):
        self._values = values

    def asArray(self):
        return self._values


def make_design():
    """A small parametric design: one sketch (line + circle) extruded into a body."""
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


# ---- a B-rep box, for testing reference resolution ------------------------------------

def make_box(component, name="Body1", size=2.0, origin=(0.0, 0.0, 0.0)):
    """A box body with 6 planar faces, 12 line edges and 8 vertices.

    Enough for the importer's reference matching to be tested against geometry whose
    signatures (centroids, areas, end points, lengths) are known exactly.
    """
    ox, oy, oz = origin
    s = size
    corners = [(ox + x * s, oy + y * s, oz + z * s)
               for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    vertices = [Obj("BRepVertex", geometry=P(*c)) for c in corners]
    by_corner = dict(zip(corners, vertices))

    edges = []
    for a in corners:
        for b in corners:
            if a >= b:
                continue
            differing = [i for i in range(3) if abs(a[i] - b[i]) > 1e-12]
            if len(differing) != 1:
                continue
            edge = Obj("BRepEdge", startVertex=by_corner[a], endVertex=by_corner[b],
                       geometry=Obj("Line3D", curveType=Curve3DTypes.Line3DCurveType),
                       length=s, pointOnEdge=P(*[(a[i] + b[i]) / 2.0 for i in range(3)]))
            edges.append(edge)

    faces = []
    for axis in range(3):
        for side in (0, 1):
            centre = [ox + s / 2.0, oy + s / 2.0, oz + s / 2.0]
            centre[axis] = (ox, oy, oz)[axis] + side * s
            normal = [0.0, 0.0, 0.0]
            normal[axis] = 1.0 if side else -1.0
            face = Obj("BRepFace",
                       geometry=Obj("Plane", surfaceType=SurfaceTypes.PlaneSurfaceType),
                       centroid=P(*centre), pointOnFace=P(*centre), area=s * s)
            face.evaluator = types.SimpleNamespace(
                getNormalAtPoint=lambda _p, n=normal: (True, P(*n)))
            faces.append(face)

    body = Obj("BRepBody", name=name, isSolid=True, isVisible=True, parentComponent=component,
               physicalProperties=types.SimpleNamespace(volume=s ** 3, area=6 * s * s))
    body.faces = Coll(faces)
    body.edges = Coll(edges)
    body.vertices = Coll(vertices)
    for face in faces:
        face.body = body
    for edge in edges:
        edge.body = body
    for vertex in vertices:
        vertex.body = body
    return body


# ---- a Fusion session for the importer to build into -----------------------------------
# These fakes record what the importer asked for and keep just enough state for the next
# call to be meaningful: parameters that can be looked up, sketches whose profiles come
# out of the curves added to them, and features that leave a body behind.

import re  # noqa: E402  (kept with the section it belongs to)

UNIT_SCALE = {"": 1.0, "mm": 0.1, "cm": 1.0, "m": 100.0, "in": 2.54, "ft": 30.48,
              "deg": math.pi / 180.0, "rad": 1.0}

_NUMBER = re.compile(r"(\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([A-Za-z]+)?")
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


class UnknownName(Exception):
    """What Fusion does when an expression names a parameter that does not exist."""


def evaluate(design, expression):
    """Expression -> value in internal units. Numbers with units, names, + - * / ( )."""
    text = str(expression).strip()
    if not text:
        raise UnknownName("empty expression")

    def number(match):
        unit = (match.group(2) or "").strip()
        if unit and unit not in UNIT_SCALE:
            raise UnknownName("unit " + unit)
        return repr(float(match.group(1)) * UNIT_SCALE.get(unit, 1.0))

    def name(match):
        parameter = design.allParameters.itemByName(match.group(0))
        if parameter is None:
            raise UnknownName(match.group(0))
        return repr(float(parameter.value))

    converted = _NAME.sub(name, _NUMBER.sub(number, text))
    try:
        return float(eval(converted, {"__builtins__": {}}, {}))  # noqa: S307 (test mock)
    except UnknownName:
        raise
    except Exception:
        raise UnknownName("could not evaluate " + text)


def value_of(design, value_input, default=1.0):
    """The number a ValueInput stands for."""
    if value_input is None:
        return default
    if getattr(value_input, "real", None) is not None:
        return value_input.real
    return evaluate(design, value_input.expression)


class FakeParameter:
    def __init__(self, design, name, expression, value, unit="", created_by=None, role=None):
        self.objectType = "adsk::fusion::ModelParameter"
        self.entityToken = "param:" + name
        self._design = design
        self.name = name
        self._expression = expression
        self._value = value
        self.unit = unit
        self.comment = ""
        self.createdBy = created_by
        self.role = role

    @property
    def expression(self):
        return self._expression

    @expression.setter
    def expression(self, text):
        self._value = evaluate(self._design, text)
        self._expression = text

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, number):
        self._value = float(number)
        self._expression = "%g cm" % float(number)


class FakeUserParameters:
    def __init__(self, design):
        self._design = design

    @property
    def count(self):
        return sum(1 for p in self._design.allParameters
                   if getattr(p, "createdBy", None) is None)

    def add(self, name, value_input, unit, comment):
        if self._design.allParameters.itemByName(name) is not None:
            raise UnknownName("duplicate parameter " + name)
        value = value_of(self._design, value_input)  # raises if a name is not known yet
        parameter = FakeParameter(self._design, name, getattr(value_input, "expression", None)
                                  or "%g" % value, value, unit)
        parameter.comment = comment
        self._design.allParameters.add(parameter)
        return parameter


class FakeTimeline:
    def __init__(self, design):
        self._design = design
        self.markerPosition = 0

    @property
    def count(self):
        return len(self._design.history)


class FakeDesign:
    def __init__(self):
        self.objectType = "adsk::fusion::Design"
        self.designType = DesignTypes.ParametricDesignType
        self.allParameters = Coll([])
        self.userParameters = FakeUserParameters(self)
        self.unitsManager = types.SimpleNamespace(defaultLengthUnits="mm")
        self.fusionUnitsManager = types.SimpleNamespace(distanceDisplayUnits=None)
        self.history = []
        self.timeline = FakeTimeline(self)
        self.rootComponent = FakeComponent(self, "Root")

    def record(self, obj):
        self.history.append(obj)
        return obj

    def parameter(self, name_hint, expression, value, created_by, role=None):
        """A model parameter of a feature, named the way Fusion names them (d1, d2, ...)."""
        index = sum(1 for p in self.allParameters if p.name.startswith("d")) + 1
        parameter = FakeParameter(self, "d%d" % index, expression, value, "mm", created_by, role)
        self.allParameters.add(parameter)
        return parameter


class FakeOccurrence:
    def __init__(self, component, transform, name):
        self.objectType = "adsk::fusion::Occurrence"
        self.entityToken = "occ:" + name
        self.component = component
        self.transform2 = transform
        self.name = name
        self.isGrounded = False
        self.isLightBulbOn = True
        self.childOccurrences = Coll([])

    @property
    def fullPathName(self):
        return self.name


class FakeOccurrences:
    def __init__(self, component):
        self._component = component
        self._items = []

    @property
    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]

    def addNewComponent(self, transform):
        design = self._component.design
        component = FakeComponent(design, "Component%d" % (len(design.history) + 1))
        occurrence = FakeOccurrence(component, transform, component.name + ":1")
        self._items.append(occurrence)
        self._component.childOccurrencesList.append(occurrence)
        design.record(occurrence)
        return occurrence

    def addExistingComponent(self, component, transform):
        occurrence = FakeOccurrence(component, transform,
                                    "%s:%d" % (component.name, len(self._items) + 1))
        self._items.append(occurrence)
        self._component.design.record(occurrence)
        return occurrence


class FakeConstructionCollection:
    """constructionPlanes / constructionAxes / constructionPoints."""

    def __init__(self, component, type_name):
        self._component = component
        self._type = type_name
        self._items = []

    @property
    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]

    def itemByName(self, name):
        for item in self._items:
            if item.name == name:
                return item
        return None

    def createInput(self):
        return _ConstructionInput(self._type)

    def add(self, feature_input):
        if feature_input.definition is None:
            raise ValueError("construction input was never defined")
        created = Obj(self._type, name="%s%d" % (self._type, len(self._items) + 1),
                      component=self._component, definition=feature_input.definition,
                      isLightBulbOn=True)
        self._items.append(created)
        self._component.design.record(created)
        return created


class _ConstructionInput:
    def __init__(self, type_name):
        self.type = type_name
        self.definition = None

    def __getattr__(self, name):
        if not name.startswith("setBy"):
            raise AttributeError(name)

        def setter(*args):
            self.definition = (name, args)
            return True

        return setter


class FakeSketches:
    def __init__(self, component):
        self._component = component
        self._items = []

    @property
    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]

    def add(self, plane):
        if plane is None:
            raise ValueError("a sketch needs a plane")
        sketch = FakeSketch(self._component, plane, "Sketch%d" % (len(self._items) + 1))
        self._items.append(sketch)
        self._component.design.record(sketch)
        return sketch


class _SketchCurveCollection:
    def __init__(self, sketch, type_name):
        self._sketch = sketch
        self._type = type_name

    def _make(self, **attrs):
        curve = Obj(self._type, parentSketch=self._sketch, isConstruction=False, isFixed=False,
                    isReference=False, isFullyConstrained=False, **attrs)
        self._sketch.curves.append(curve)
        return curve

    def _point(self, value):
        """A SketchPoint for either a SketchPoint or a Point3D argument."""
        if value is None:
            raise ValueError("a point is required")
        if getattr(value, "objectType", "").endswith("SketchPoint"):
            return value
        return self._sketch.sketchPoints.add(value)

    # SketchLines
    def addByTwoPoints(self, start, end):
        return self._make(startSketchPoint=self._point(start), endSketchPoint=self._point(end),
                          geometry=Obj("Line3D", curveType=Curve3DTypes.Line3DCurveType))

    # SketchCircles
    def addByCenterRadius(self, center, radius):
        return self._make(centerSketchPoint=self._point(center), radius=float(radius),
                          area=math.pi * float(radius) ** 2, closed=True,
                          geometry=Obj("Circle3D", curveType=Curve3DTypes.Circle3DCurveType))

    # SketchArcs
    def addByThreePoints(self, start, middle, end):
        start_point, end_point = self._point(start), self._point(end)
        centre = self._sketch.sketchPoints.add(Point3D.create(
            (start_point.geometry.x + end_point.geometry.x) / 2.0,
            (start_point.geometry.y + end_point.geometry.y) / 2.0, 0.0))
        return self._make(startSketchPoint=start_point, endSketchPoint=end_point,
                          centerSketchPoint=centre, pointOnArc=middle,
                          geometry=Obj("Arc3D", curveType=Curve3DTypes.Arc3DCurveType))

    # SketchEllipses
    def add(self, *args):
        if self._type == "SketchEllipse":
            centre, major, minor = args
            return self._make(centerSketchPoint=self._point(centre), majorAxisPoint=major,
                              minorAxisPoint=minor, closed=True,
                              area=math.pi, geometry=Obj("Ellipse3D",
                                                         curveType=Curve3DTypes.Ellipse3DCurveType))
        points = list(args[0]) if args else []
        fit = [self._point(p) for p in points]
        return self._make(fitPoints=Coll(fit), isClosed=False,
                          geometry=Obj("NurbsCurve3D",
                                       curveType=Curve3DTypes.NurbsCurve3DCurveType))

    # SketchFixedSplines
    def addByNurbsCurve(self, curve):
        return self._make(nurbsCurve=curve, geometry=curve)


class _SketchCurves:
    def __init__(self, sketch):
        self.sketchLines = _SketchCurveCollection(sketch, "SketchLine")
        self.sketchCircles = _SketchCurveCollection(sketch, "SketchCircle")
        self.sketchArcs = _SketchCurveCollection(sketch, "SketchArc")
        self.sketchEllipses = _SketchCurveCollection(sketch, "SketchEllipse")
        self.sketchFittedSplines = _SketchCurveCollection(sketch, "SketchFittedSpline")
        self.sketchFixedSplines = _SketchCurveCollection(sketch, "SketchFixedSpline")


class _SketchPoints:
    def __init__(self, sketch):
        self._sketch = sketch
        self._items = []

    @property
    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]

    def add(self, position):
        point = Obj("SketchPoint", geometry=position, parentSketch=self._sketch,
                    isFixed=False, isReference=False)
        self._items.append(point)
        return point


class _Constraints:
    def __init__(self, sketch):
        self._sketch = sketch
        self.calls = []

    def __getattr__(self, name):
        if not name.startswith("add"):
            raise AttributeError(name)

        def constrain(*entities):
            if any(e is None for e in entities):
                raise ValueError("a constraint entity is missing")
            self.calls.append((name, entities))
            return Obj(name[3:] + "Constraint")

        return constrain


class _Dimensions:
    """Only the dimension kinds the importer is expected to be able to create."""

    SIGNATURES = {"addDistanceDimension": 4, "addOffsetDimension": 3,
                  "addDiameterDimension": 2, "addRadialDimension": 2,
                  "addAngularDimension": 3, "addConcentricCircleDimension": 3,
                  "addEllipseMajorRadiusDimension": 2, "addEllipseMinorRadiusDimension": 2}

    def __init__(self, sketch):
        self._sketch = sketch
        self.calls = []

    def __getattr__(self, name):
        expected = self.SIGNATURES.get(name)
        if expected is None:
            raise AttributeError(name)

        def dimension(*args):
            if len(args) != expected:
                raise TypeError("%s takes %d arguments, got %d" % (name, expected, len(args)))
            design = self._sketch.parentComponent.design
            created = Obj("SketchDimension", isDriving=True)
            created.parameter = design.parameter(None, "1 cm", 1.0, created)
            self.calls.append((name, args, created))
            return created

        return dimension


class FakeSketch:
    def __init__(self, component, plane, name):
        self.objectType = "adsk::fusion::Sketch"
        self.entityToken = "sketch:" + name
        self.parentComponent = component
        self.referencePlane = plane
        self.name = name
        self.isVisible = True
        # Fusion decides a new sketch's own axes; a mock plane can say what they are.
        self.transform = Matrix3D(getattr(plane, "sketchTransform", IDENTITY))
        self.curves = []
        self.sketchPoints = _SketchPoints(self)
        self.sketchPoints.add(Point3D.create(0.0, 0.0, 0.0))  # every sketch has an origin
        self.sketchCurves = _SketchCurves(self)
        self.geometricConstraints = _Constraints(self)
        self.sketchDimensions = _Dimensions(self)

    @property
    def profiles(self):
        """One profile per closed curve, which is all the importer's matching needs."""
        found = []
        for curve in self.curves:
            if not getattr(curve, "closed", False):
                continue
            loop = Obj("ProfileLoop", isOuter=True,
                       profileCurves=Coll([Obj("ProfileCurve", sketchEntity=curve)]))
            profile = Obj("Profile", parentSketch=self, profileLoops=Coll([loop]))
            profile.area = getattr(curve, "area", 1.0)
            found.append(profile)
        return Coll(found)


class _ExtrudeInput:
    def __init__(self, profile, operation):
        self.profile = profile
        self.operation = operation
        self.extent = None
        self.startExtent = None
        self.taperAngle = None
        self.participantBodies = None

    def setDistanceExtent(self, symmetric, distance):
        self.extent = ("distance", bool(symmetric), distance)

    def setTwoSidesDistanceExtent(self, one, two):
        self.extent = ("twoSides", one, two)

    def setSymmetricExtent(self, distance, full_length):
        self.extent = ("symmetric", distance, bool(full_length))

    def setAllExtent(self, direction):
        self.extent = ("all", direction)

    def setOneSideToExtent(self, entity, chained):
        if entity is None:
            raise ValueError("to-entity extent needs an entity")
        self.extent = ("toEntity", entity, bool(chained))


class _Extrudes:
    def __init__(self, component):
        self._component = component

    def createInput(self, profile, operation):
        if profile is None:
            raise ValueError("an extrude needs a profile")
        return _ExtrudeInput(profile, operation)

    def add(self, feature_input):
        if feature_input.extent is None:
            raise ValueError("an extrude needs an extent")
        design = self._component.design
        feature = Obj("ExtrudeFeature", name="Extrude%d" % (len(design.history) + 1),
                      parentComponent=self._component, isSuppressed=False)
        area = getattr(feature_input.profile, "area", 1.0)
        length = 1.0
        if feature_input.extent[0] == "distance":
            length = value_of(design, feature_input.extent[2])
        elif feature_input.extent[0] == "symmetric":
            length = value_of(design, feature_input.extent[1])
        elif feature_input.extent[0] == "twoSides":
            length = sum(value_of(design, v) for v in feature_input.extent[1:])
        body = make_box(self._component, "Body%d" % (self._component.bRepBodies.count + 1))
        body.physicalProperties = types.SimpleNamespace(volume=area * length, area=area * 2)
        self._component.bRepBodies.add(body)
        feature.bodies = Coll([body])
        feature.input = feature_input
        design.parameter(None, "%g cm" % length, length, feature, "AlongDistance")
        design.record(feature)
        return feature


class _EdgeSetInputs:
    def __init__(self):
        self.sets = []

    def addConstantRadiusEdgeSet(self, edges, radius, chain):
        if edges is None or edges.count == 0:
            raise ValueError("an edge set needs edges")
        self.sets.append(("constant", edges, radius, chain))
        return True

    def addVariableRadiusEdgeSet(self, edges, start_radius, end_radius, chain):
        self.sets.append(("variable", edges, start_radius, end_radius, chain))
        return True

    def addChordLengthEdgeSet(self, edges, chord, chain):
        self.sets.append(("chord", edges, chord, chain))
        return True


class _FilletInput:
    def __init__(self):
        self.edgeSetInputs = _EdgeSetInputs()


class _Fillets:
    def __init__(self, component):
        self._component = component

    def createInput(self):
        return _FilletInput()

    def add(self, feature_input):
        if not feature_input.edgeSetInputs.sets:
            raise ValueError("a fillet needs an edge set")
        design = self._component.design
        feature = Obj("FilletFeature", name="Fillet%d" % (len(design.history) + 1),
                      parentComponent=self._component, isSuppressed=False,
                      bodies=Coll([]), input=feature_input)
        design.parameter(None, "1 mm", 0.1, feature, "Radius")
        design.record(feature)
        return feature


class _BaseFeature:
    def __init__(self, component):
        self.objectType = "adsk::fusion::BaseFeature"
        self.name = "Base1"
        self.component = component
        self.editing = False
        self.finished = False

    def startEdit(self):
        self.editing = True
        return True

    def finishEdit(self):
        self.editing = False
        self.finished = True
        return True


class _BaseFeatures:
    def __init__(self, component):
        self._component = component

    def add(self):
        feature = _BaseFeature(self._component)
        self._component.baseFeatureList.append(feature)
        self._component.design.record(feature)
        return feature


class _Joints:
    def __init__(self, component, as_built=False):
        self._component = component
        self._as_built = as_built
        self._items = []

    @property
    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i]

    def createInput(self, *args):
        if any(a is None for a in args[:2]):
            raise ValueError("a joint needs two sides")
        return _JointInput(args)

    def add(self, feature_input):
        if feature_input.motion is None:
            raise ValueError("a joint needs a motion")
        joint = Obj("AsBuiltJoint" if self._as_built else "Joint",
                    name="Joint%d" % (len(self._items) + 1), isSuppressed=False)
        joint.input = feature_input
        self._items.append(joint)
        self._component.design.record(joint)
        return joint


class _JointInput:
    def __init__(self, sides):
        self.sides = sides
        self.motion = None
        self.offset = None
        self.angle = None
        self.isFlipped = False

    def __getattr__(self, name):
        if not name.startswith("setAs"):
            raise AttributeError(name)

        def motion(*args):
            self.motion = (name, args)
            return True

        return motion


class _FeatureInput:
    """Records what a builder set on a feature input.

    createInput's own arguments are checked for arity, since that is the part most
    likely to be written wrong against the real API; later setters are recorded as they
    come, under their own name.
    """

    def __init__(self, args):
        self.args = args
        self.set = {}
        self.calls = []

    def __setattr__(self, name, value):
        if name in ("args", "set", "calls"):
            object.__setattr__(self, name, value)
        else:
            self.set[name] = value

    def __getattr__(self, name):
        if name.startswith(("set", "add")):
            def call(*args):
                self.calls.append((name, args))
                return True
            return call
        if name in self.set:
            return self.set[name]
        raise AttributeError(name)


class _RecordingFeatures:
    """A feature collection whose createInput takes a fixed number of arguments."""

    def __init__(self, component, type_name, arity, creates_body=False, create_name="createInput"):
        self._component = component
        self._type = type_name
        self._arity = arity
        self._creates_body = creates_body
        self._create_name = create_name

    def __getattr__(self, name):
        # createInput, createInput2, createSimpleInput, ... all land here.
        if not name.startswith("create"):
            raise AttributeError(name)

        def create(*args):
            if name != self._create_name:
                raise AttributeError("%s has no %s" % (self._type, name))
            if len(args) != self._arity:
                raise TypeError("%s.%s takes %d arguments, got %d"
                                % (self._type, name, self._arity, len(args)))
            if any(a is None for a in args):
                raise ValueError("%s.%s was given a missing entity" % (self._type, name))
            return _FeatureInput(args)

        return create

    def add(self, feature_input):
        design = self._component.design
        feature = Obj(self._type, name="%s%d" % (self._type.replace("Feature", ""),
                                                 len(design.history) + 1),
                      parentComponent=self._component, isSuppressed=False,
                      input=feature_input)
        bodies = []
        if self._creates_body:
            body = make_box(self._component, "Body%d" % (self._component.bRepBodies.count + 1))
            self._component.bRepBodies.add(body)
            bodies.append(body)
        feature.bodies = Coll(bodies)
        design.parameter(None, "1 cm", 1.0, feature)
        design.record(feature)
        return feature


class _Features:
    """The feature collections the importer is expected to be able to drive.

    A collection that is not here raises AttributeError, which is what the importer
    reports as a feature it could not build — the same way an older Fusion without a
    given API would behave.
    """

    def __init__(self, component):
        self.extrudeFeatures = _Extrudes(component)
        self.filletFeatures = _Fillets(component)
        self.baseFeatures = _BaseFeatures(component)
        self.revolveFeatures = _RecordingFeatures(component, "RevolveFeature", 3,
                                                  creates_body=True)
        self.sweepFeatures = _RecordingFeatures(component, "SweepFeature", 3, creates_body=True)
        self.loftFeatures = _RecordingFeatures(component, "LoftFeature", 1, creates_body=True)
        self.chamferFeatures = _RecordingFeatures(component, "ChamferFeature", 0,
                                                  create_name="createInput2")
        self.shellFeatures = _RecordingFeatures(component, "ShellFeature", 2)
        self.draftFeatures = _RecordingFeatures(component, "DraftFeature", 3)
        self.thickenFeatures = _RecordingFeatures(component, "ThickenFeature", 5,
                                                  creates_body=True)
        self.offsetFacesFeatures = _RecordingFeatures(component, "OffsetFacesFeature", 2)
        self.combineFeatures = _RecordingFeatures(component, "CombineFeature", 2)
        self.splitBodyFeatures = _RecordingFeatures(component, "SplitBodyFeature", 3)
        self.mirrorFeatures = _RecordingFeatures(component, "MirrorFeature", 2,
                                                 creates_body=True)
        self.moveFeatures = _RecordingFeatures(component, "MoveFeature", 2)
        self.scaleFeatures = _RecordingFeatures(component, "ScaleFeature", 3)
        self.rectangularPatternFeatures = _RecordingFeatures(
            component, "RectangularPatternFeature", 5, creates_body=True)
        self.circularPatternFeatures = _RecordingFeatures(
            component, "CircularPatternFeature", 2, creates_body=True)
        self.holeFeatures = _RecordingFeatures(component, "HoleFeature", 1,
                                               create_name="createSimpleInput")


class FakeComponent:
    def __init__(self, design, name):
        self.objectType = "adsk::fusion::Component"
        self.entityToken = "comp:" + name
        self.design = design
        self.name = name
        self.partNumber = ""
        self.description = ""
        self.bRepBodies = Coll([])
        self.occurrences = FakeOccurrences(self)
        self.childOccurrencesList = []
        self.baseFeatureList = []
        self.sketches = FakeSketches(self)
        self.features = _Features(self)
        self.constructionPlanes = FakeConstructionCollection(self, "ConstructionPlane")
        self.constructionAxes = FakeConstructionCollection(self, "ConstructionAxis")
        self.constructionPoints = FakeConstructionCollection(self, "ConstructionPoint")
        self.joints = _Joints(self)
        self.asBuiltJoints = _Joints(self, as_built=True)
        self.jointOrigins = Coll([])
        for attribute, plane_name in (("xYConstructionPlane", "XY Plane"),
                                      ("xZConstructionPlane", "XZ Plane"),
                                      ("yZConstructionPlane", "YZ Plane")):
            setattr(self, attribute, Obj("ConstructionPlane", name=plane_name, component=self))
        for attribute, axis_name in (("xConstructionAxis", "X Axis"),
                                     ("yConstructionAxis", "Y Axis"),
                                     ("zConstructionAxis", "Z Axis")):
            setattr(self, attribute, Obj("ConstructionAxis", name=axis_name, component=self))
        self.originConstructionPoint = Obj("ConstructionPoint", name="Origin", component=self)


class FakeImportManager:
    def __init__(self):
        self.imported = []

    def createSTEPImportOptions(self, path):
        return {"step": path}

    def importToTarget2(self, options, target):
        self.imported.append((options["step"], target))
        body = make_box(target, "Imported%d" % len(self.imported))
        target.bRepBodies.add(body)
        return Coll([body])


class FakeDocument:
    def __init__(self):
        self.objectType = "adsk::core::Document"
        self.name = "Untitled"
        self.design = FakeDesign()
        self.closed = False

        class Products:
            def __init__(self, design):
                self._design = design

            def itemByProductType(self, product_type):
                return self._design if product_type == "DesignProductType" else None

        self.products = Products(self.design)

    def close(self, save):
        self.closed = True
        return True


class FakeDocuments:
    def __init__(self):
        self.created = []

    def add(self, document_type):
        document = FakeDocument()
        self.created.append(document)
        return document


class FakeApp:
    """A Fusion session the importer can build a design in."""

    def __init__(self):
        self.objectType = "adsk::core::Application"
        self.version = "2.0.test"
        self.documents = FakeDocuments()
        self.importManager = FakeImportManager()
        self.activeDocument = None
        self.userInterface = FakeUserInterface()
