"""Resolves f540x references against the geometry the importer has rebuilt.

Fusion entity tokens are only meaningful inside the document they came from, so the
exporter stores B-rep references as geometric signatures (see docs/formats/f540x.md).
Here each signature is matched against the design being rebuilt.

A signature that does not match within tolerance resolves to None and is reported;
it is never rebound to whatever geometry happened to be closest, because a fillet
silently moving to a different edge is far worse than a feature that fails to import.
"""

from .api import by_name, distance, iterate, probe, relative_difference

# Fusion's internal unit is cm. Rebuilt geometry comes out of the same kernel from the
# same inputs, so matches are near-exact; the tolerance covers accumulated arithmetic.
POINT_TOLERANCE = 1.0e-4
SIZE_TOLERANCE = 1.0e-3

ORIGIN_PLANES = {"XY": "xYConstructionPlane", "XZ": "xZConstructionPlane",
                 "YZ": "yZConstructionPlane"}
ORIGIN_AXES = {"X": "xConstructionAxis", "Y": "yConstructionAxis", "Z": "zConstructionAxis"}


class Resolver:
    """Looks up the Fusion object a reference describes.

    `owner` supplies the maps the importer builds as it goes: components, occurrences,
    sketches, sketch entities, and a report to record misses in.
    """

    def __init__(self, owner):
        self.owner = owner

    # -- entry point ------------------------------------------------------------

    def resolve(self, ref, context=None):
        """Fusion object for a reference, or None (recorded in the report).

        A list of references resolves to a list with the misses dropped.
        """
        if ref is None:
            return None
        if isinstance(ref, (list, tuple)):
            return [r for r in (self.resolve(r, context) for r in ref) if r is not None]
        if not isinstance(ref, dict):
            return None
        kind = ref.get("kind")
        handler = getattr(self, "_" + str(kind), None)
        if handler is None:
            self.miss(ref, "reference kind '%s' is not supported" % kind)
            return None
        try:
            found = handler(ref, context)
        except Exception as error:
            self.miss(ref, "%s: %s" % (type(error).__name__, error))
            return None
        if found is None:
            self.miss(ref, "no match in the rebuilt geometry")
        return found

    def resolve_all(self, refs, context=None):
        """Always a list, whether the schema gave one reference or several."""
        if refs is None:
            return []
        if isinstance(refs, dict):
            found = self.resolve(refs, context)
            return [found] if found is not None else []
        return self.resolve(refs, context) or []

    def miss(self, ref, why):
        kind = ref.get("kind") if isinstance(ref, dict) else "?"
        where = ref.get("body") or ref.get("name") or ref.get("sketch") or ""
        self.owner.report.issue("unresolved %s reference %s" % (kind, where), why)

    # -- component lookup -------------------------------------------------------

    def component(self, component_id, context=None):
        return self.owner.components.get(component_id) or context or self.owner.root

    def bodies(self, ref, context):
        """Candidate bodies for a B-rep reference: the named one, else all in the component."""
        component = self.component(ref.get("component"), context)
        if component is None:
            return []
        collection = probe(component, "bRepBodies")
        named = by_name(collection, ref.get("body"))
        return [named] if named is not None else iterate(collection)

    # -- B-rep ------------------------------------------------------------------

    def _best(self, candidates, score, tolerance):
        """Candidate with the lowest score, if that score is within tolerance.

        Returns (object, score, runner_up_score) so callers can report near-misses.
        """
        best, best_score, second = None, float("inf"), float("inf")
        for candidate in candidates:
            value = score(candidate)
            if value < best_score:
                best, best_score, second = candidate, value, best_score
            elif value < second:
                second = value
        if best is None or best_score > tolerance:
            return None, best_score, second
        return best, best_score, second

    def _face(self, ref, context):
        wanted_surface = ref.get("surface")
        centroid, area = ref.get("centroid"), ref.get("area")

        def score(face):
            if wanted_surface is not None:
                surface = probe(probe(face, "geometry"), "surfaceType")
                name = self.owner.surface_name(surface)
                if name is not None and name != wanted_surface:
                    return float("inf")
            if area is not None and relative_difference(probe(face, "area"), area) > SIZE_TOLERANCE:
                return float("inf")
            return distance(self.owner.coords(probe(face, "centroid")), centroid)

        faces = [f for body in self.bodies(ref, context) for f in iterate(probe(body, "faces"))]
        found, best, _second = self._best(faces, score, POINT_TOLERANCE)
        if found is None and best != float("inf"):
            self.owner.report.note("closest face was %.6f cm away (tolerance %g)"
                                   % (best, POINT_TOLERANCE))
        return found

    def _edge(self, ref, context):
        wanted_curve = ref.get("curve")
        start, end, length = ref.get("start"), ref.get("end"), ref.get("length")

        def score(edge):
            if wanted_curve is not None:
                curve = probe(probe(edge, "geometry"), "curveType")
                name = self.owner.curve_name(curve)
                if name is not None and name != wanted_curve:
                    return float("inf")
            if length is not None and relative_difference(probe(edge, "length"), length) > SIZE_TOLERANCE:
                return float("inf")
            a = self.owner.coords(probe(probe(edge, "startVertex"), "geometry"))
            b = self.owner.coords(probe(probe(edge, "endVertex"), "geometry"))
            # An edge's direction is not meaningful here, so accept either orientation.
            return min(distance(a, start) + distance(b, end),
                       distance(a, end) + distance(b, start))

        edges = [e for body in self.bodies(ref, context) for e in iterate(probe(body, "edges"))]
        found, best, _second = self._best(edges, score, 2 * POINT_TOLERANCE)
        if found is None and best != float("inf"):
            self.owner.report.note("closest edge was %.6f cm away (tolerance %g)"
                                   % (best, 2 * POINT_TOLERANCE))
        return found

    def _vertex(self, ref, context):
        wanted = ref.get("point")
        vertices = [v for body in self.bodies(ref, context)
                    for v in iterate(probe(body, "vertices"))]
        found, _best, _second = self._best(
            vertices,
            lambda v: distance(self.owner.coords(probe(v, "geometry")), wanted),
            POINT_TOLERANCE)
        return found

    def _body(self, ref, context):
        component = self.component(ref.get("component"), context)
        return by_name(probe(component, "bRepBodies"), ref.get("body"))

    # -- sketch -----------------------------------------------------------------

    def _sketchEntity(self, ref, _context):
        return self.owner.entities.get(ref.get("entity"))

    def _sketch(self, ref, _context):
        return self.owner.sketches.get(ref.get("sketch"))

    def _profile(self, ref, _context):
        return self.owner.find_profile(ref.get("sketch"), ref.get("loops"))

    # -- construction geometry --------------------------------------------------

    def _construction(self, ref, context, origins, collection_name):
        component = self.component(ref.get("component"), context)
        if component is None:
            return None
        name = ref.get("name")
        attribute = origins.get(name)
        if attribute is not None:
            return probe(component, attribute)
        return by_name(probe(component, collection_name), name)

    def _constructionPlane(self, ref, context):
        return self._construction(ref, context, ORIGIN_PLANES, "constructionPlanes")

    def _constructionAxis(self, ref, context):
        return self._construction(ref, context, ORIGIN_AXES, "constructionAxes")

    def _constructionPoint(self, ref, context):
        component = self.component(ref.get("component"), context)
        if ref.get("name") == "Origin":
            return probe(component, "originConstructionPoint")
        return by_name(probe(component, "constructionPoints"), ref.get("name"))

    # -- everything else --------------------------------------------------------

    def _occurrence(self, ref, _context):
        return self.owner.occurrences.get(ref.get("occurrence"))

    def _jointOrigin(self, ref, context):
        component = self.component(ref.get("component"), context)
        return by_name(probe(component, "jointOrigins"), ref.get("name"))

    def _parameter(self, ref, _context):
        return by_name(probe(self.owner.design, "allParameters"), ref.get("name"))

    def _unknown(self, ref, _context):
        self.miss(ref, "the exporter could not describe this entity (type %s)" % ref.get("type"))
        return None
