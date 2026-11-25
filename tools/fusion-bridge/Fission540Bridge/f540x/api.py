"""Thin helpers over the Fusion API, shared by the exporter and the importer.

Everything here tolerates objects that do not have the attribute being asked for:
the Fusion API raises on unsupported properties rather than returning null, and both
directions of the bridge probe objects whose exact type is only known at runtime.
Values are in Fusion's internal units throughout (cm, radians).
"""

import math

import adsk.core
import adsk.fusion


# ---- reading --------------------------------------------------------------------

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


def enum_value(enum_class, name, default=None):
    """An enum's API name -> its value (the inverse of enum_name)."""
    if enum_class is None or name is None:
        return default
    if isinstance(name, int):
        return name
    value = getattr(enum_class, name, None)
    return default if not isinstance(value, int) else value


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


def by_name(collection, name):
    """Item of a Fusion collection by name, by itemByName or by scanning."""
    if collection is None or name is None:
        return None
    try:
        found = collection.itemByName(name)
        if found is not None:
            return found
    except Exception:
        pass
    for item in iterate(collection):
        if probe(item, "name") == name:
            return item
    return None


# ---- writing ----------------------------------------------------------------------

def value_input(expression_or_number):
    """ValueInput from an expression string ("40 mm") or a number in internal units."""
    if expression_or_number is None:
        return None
    if isinstance(expression_or_number, str):
        return adsk.core.ValueInput.createByString(expression_or_number)
    return adsk.core.ValueInput.createByReal(float(expression_or_number))


def point3d(coords):
    if coords is None:
        return None
    x, y, z = (list(coords) + [0.0, 0.0, 0.0])[:3]
    return adsk.core.Point3D.create(float(x), float(y), float(z))


def vector3d(coords):
    if coords is None:
        return None
    x, y, z = (list(coords) + [0.0, 0.0, 0.0])[:3]
    return adsk.core.Vector3D.create(float(x), float(y), float(z))


def matrix3d(values):
    """Matrix3D from 16 row-major numbers (identity if values is None)."""
    m = adsk.core.Matrix3D.create()
    if values and len(values) == 16:
        try:
            m.setWithArray([float(v) for v in values])
        except Exception:
            pass
    return m


def object_collection(items):
    """ObjectCollection holding items (Nones dropped)."""
    collection = adsk.core.ObjectCollection.create()
    for item in items or []:
        if item is not None:
            collection.add(item)
    return collection


def nurbs_curve(data):
    """NurbsCurve3D from the schema's `nurbs` object, or None."""
    if not data:
        return None
    points = [point3d(p) for p in data.get("controlPoints") or []]
    knots = [float(k) for k in data.get("knots") or []]
    degree = data.get("degree")
    periodic = bool(data.get("periodic"))
    weights = data.get("weights")
    if not points or degree is None or not knots:
        return None
    if weights:
        return adsk.core.NurbsCurve3D.createRational(
            points, int(degree), knots, [float(w) for w in weights], periodic)
    return adsk.core.NurbsCurve3D.createNonRational(points, int(degree), knots, periodic)


# ---- geometry on plain lists ------------------------------------------------------
# Matrices are 16 row-major numbers, as Matrix3D.asArray() returns them; points are
# [x, y, z]. Doing this arithmetic in Python keeps it testable without Fusion.

IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def mat_apply(m, p):
    """Transform a point by a 4x4 row-major matrix."""
    if m is None or p is None:
        return p
    x, y, z = p[0], p[1], p[2]
    return [m[0] * x + m[1] * y + m[2] * z + m[3],
            m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11]]


def mat_multiply(a, b):
    """a * b, both 4x4 row-major."""
    if a is None:
        return b
    if b is None:
        return a
    out = [0.0] * 16
    for r in range(4):
        for c in range(4):
            out[r * 4 + c] = sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
    return out


def mat_rigid_inverse(m):
    """Inverse of a rigid (rotation + translation) matrix: R^T, -R^T t."""
    if m is None:
        return None
    r = [[m[0], m[1], m[2]], [m[4], m[5], m[6]], [m[8], m[9], m[10]]]
    t = [m[3], m[7], m[11]]
    inv_t = [-sum(r[k][i] * t[k] for k in range(3)) for i in range(3)]
    return [r[0][0], r[1][0], r[2][0], inv_t[0],
            r[0][1], r[1][1], r[2][1], inv_t[1],
            r[0][2], r[1][2], r[2][2], inv_t[2],
            0.0, 0.0, 0.0, 1.0]


def distance(a, b):
    if a is None or b is None:
        return float("inf")
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def add(a, b, scale=1.0):
    return [a[i] + b[i] * scale for i in range(3)]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def normalize(v):
    length = math.sqrt(sum(c * c for c in v))
    return None if length < 1e-12 else [c / length for c in v]


def relative_difference(a, b):
    """|a - b| scaled by the larger magnitude; inf if either is missing."""
    if a is None or b is None:
        return float("inf")
    scale = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / scale
