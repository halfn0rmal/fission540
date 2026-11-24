#include "AsmToOcct.h"

#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_Circle.hxx>
#include <Geom_ConicalSurface.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Geom_Ellipse.hxx>
#include <Geom_Line.hxx>
#include <Geom_Plane.hxx>
#include <Geom_SphericalSurface.hxx>
#include <Geom_ToroidalSurface.hxx>
#include <ShapeFix_Face.hxx>
#include <ShapeFix_Shape.hxx>
#include <Standard_Failure.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Trsf.hxx>

#include <algorithm>
#include <cmath>
#include <map>
#include <numbers>
#include <set>
#include <unordered_map>

namespace fission::io::detail {
namespace {

using sab::Record;
using sab::SabError;
using sab::Token;
using sab::TokenKind;

// Field positions (after the class identifiers). See docs/formats/f3d.md.
namespace field {
constexpr std::size_t kFirst = 3; // [0] attrib, [1] history id, [2] unused
namespace body { constexpr std::size_t lump = 3, transform = 5; }
namespace lump { constexpr std::size_t next = 3, shell = 4; }
namespace shell { constexpr std::size_t next = 3, face = 5; }
namespace face { constexpr std::size_t next = 3, loop = 4, surface = 7, sense = 8; }
namespace loop { constexpr std::size_t next = 3, coedge = 4; }
namespace coedge { constexpr std::size_t next = 3, partner = 5, edge = 6, sense = 7; }
namespace edge { constexpr std::size_t start = 3, startParam = 4, end = 5, endParam = 6, curve = 8, sense = 9; }
namespace vertex { constexpr std::size_t point = 5; }
namespace point { constexpr std::size_t position = 3; }
} // namespace field

// Sequential reader over a record's values.
class Cursor {
public:
    Cursor(const Record& rec, std::size_t start) : m_rec(rec), m_pos(start) {}

    const Token& next() {
        if (m_pos >= m_rec.values.size()) {
            throw SabError(m_rec.type + ": record too short");
        }
        return m_rec.values[m_pos++];
    }
    [[nodiscard]] const Token& peek() const {
        if (m_pos >= m_rec.values.size()) {
            throw SabError(m_rec.type + ": record too short");
        }
        return m_rec.values[m_pos];
    }
    [[nodiscard]] std::size_t pos() const { return m_pos; }
    void seek(std::size_t pos) { m_pos = pos; }

    double num() { return next().number(); }
    long count() { return static_cast<long>(std::lround(num())); }

    bool flag() {
        const Token& t = next();
        if (t.kind == TokenKind::True) {
            return true;
        }
        if (t.kind == TokenKind::False) {
            return false;
        }
        if (t.kind == TokenKind::String) {
            return t.s == "reversed" || t.s == "true";
        }
        throw SabError(m_rec.type + ": expected flag");
    }

    gp_XYZ xyz() {
        const Token& t = next();
        if (t.kind != TokenKind::Position && t.kind != TokenKind::Vector) {
            throw SabError(m_rec.type + ": expected position/vector");
        }
        return {t.d[0], t.d[1], t.d[2]};
    }
    gp_Pnt pnt() { return gp_Pnt(xyz()); }
    gp_Vec vec() { return gp_Vec(xyz()); }
    gp_Dir dir() {
        const gp_XYZ v = xyz();
        if (v.Modulus() < 1e-300) {
            throw SabError(m_rec.type + ": zero direction");
        }
        return gp_Dir(v);
    }

    // Interval: two bounds, each `true <value>` (bounded) or `false` (unbounded).
    void interval() {
        for (int i = 0; i < 2; ++i) {
            if (flag()) {
                (void)num();
            }
        }
    }

private:
    const Record& m_rec;
    std::size_t m_pos;
};

struct CurveInfo {
    Handle(Geom_Curve) curve;
    double paramScale = 1.0; // OCCT param = ACIS param * scale + shift
    double paramShift = 0.0;
    bool reversed = false;
};

// Reads an ACIS bs3_curve ('nubs' / 'nurbs') starting at the cursor (just after the keyword).
Handle(Geom_BSplineCurve) readBs3Curve(Cursor& c, bool rational) {
    const int degree = static_cast<int>(c.count());
    (void)c.next(); // closure: open / closed / periodic
    const long knotCount = c.count();
    if (degree < 1 || knotCount < 2 || knotCount > 100000) {
        throw SabError("bs3_curve: bad header");
    }
    TColStd_Array1OfReal knots(1, static_cast<int>(knotCount));
    TColStd_Array1OfInteger mults(1, static_cast<int>(knotCount));
    int multSum = 0;
    for (int i = 1; i <= knotCount; ++i) {
        knots(i) = c.num();
        mults(i) = static_cast<int>(c.count());
        multSum += mults(i);
    }
    // ACIS stores end multiplicity = degree; OCCT needs degree + 1.
    const int poleCount = multSum - degree + 1;
    if (mults(1) == degree) {
        mults(1) = degree + 1;
    }
    if (mults(static_cast<int>(knotCount)) == degree) {
        mults(static_cast<int>(knotCount)) = degree + 1;
    }
    if (poleCount < degree + 1) {
        throw SabError("bs3_curve: inconsistent pole count");
    }
    TColgp_Array1OfPnt poles(1, poleCount);
    TColStd_Array1OfReal weights(1, poleCount);
    for (int i = 1; i <= poleCount; ++i) {
        const double x = c.num();
        const double y = c.num();
        const double z = c.num();
        poles(i) = gp_Pnt(x, y, z);
        weights(i) = rational ? c.num() : 1.0;
    }
    if (rational) {
        return new Geom_BSplineCurve(poles, weights, knots, mults, degree);
    }
    return new Geom_BSplineCurve(poles, knots, mults, degree);
}

class Converter {
public:
    Converter(const sab::Document& doc, ConversionStats& stats, BodySelection selection)
        : m_doc(doc), m_stats(stats), m_selection(selection) {}

    TopoDS_Shape run() {
        BRep_Builder builder;
        TopoDS_Compound all;
        builder.MakeCompound(all);

        bool requireClosed = false;
        std::vector<int> candidates = selectBodies(requireClosed);
        for (int index : candidates) {
            const ConversionStats before = m_stats;
            TopoDS_Shape b = body(index);
            const bool hasSolid = !b.IsNull() && TopExp_Explorer(b, TopAbs_SOLID).More();
            if (b.IsNull() || (requireClosed && !hasSolid)) {
                // Roll back the counters for a body we are not keeping.
                m_stats.solids = before.solids;
                m_stats.faces = before.faces;
                m_stats.skippedFaces = before.skippedFaces;
                m_stats.skippedEdges = before.skippedEdges;
                continue;
            }
            builder.Add(all, b);
            ++m_stats.bodies;
        }
        int bodyRecords = 0;
        for (std::size_t i = 0; i < m_doc.records.size(); ++i) {
            bodyRecords += m_doc.records[i].type == "body" ? 1 : 0;
        }
        m_stats.ignoredBodies = bodyRecords - m_stats.bodies;
        if (m_stats.sewedShells > 0) {
            m_stats.warnings.push_back(std::to_string(m_stats.sewedShells) +
                                       " shell(s) closed by sewing");
        }
        for (const auto& [type, n] : m_unsupported) {
            m_stats.warnings.push_back("unsupported " + type + " (" + std::to_string(n) + ")");
        }
        if (std::abs(m_doc.mmPerUnit - 1.0) < 1e-12) {
            return all;
        }
        gp_Trsf toMm;
        toMm.SetScale(gp::Origin(), m_doc.mmPerUnit);
        return BRepBuilderAPI_Transform(all, toMm, true).Shape();
    }

private:
    bool isBody(int index) const {
        return index >= 0 && static_cast<std::size_t>(index) < m_doc.records.size() &&
               m_doc.records[static_cast<std::size_t>(index)].type == "body";
    }

    // True if the entity's attribute chain holds a Timestamp_attrib_def attribute.
    bool hasTimestamp(int index) const {
        std::set<int> seen;
        int a = refAt(rec(index), 0);
        while (a >= 0 && seen.insert(a).second && static_cast<std::size_t>(a) < m_doc.records.size()) {
            const Record& attr = rec(a);
            for (const Token& t : attr.values) {
                if (t.kind == TokenKind::String && t.s == "Timestamp_attrib_def") {
                    return true;
                }
            }
            if (attr.values.size() <= 3 || attr.values[3].kind != TokenKind::Ref) {
                break;
            }
            a = static_cast<int>(attr.values[3].i); // next attribute
        }
        return false;
    }

    std::vector<int> selectBodies(bool& requireClosed) const {
        std::vector<int> result;
        const int count = static_cast<int>(m_doc.records.size());
        if (m_selection == BodySelection::All || m_doc.entityCount <= 1 ||
            m_doc.entityCount > count) {
            for (int i = 0; i < count; ++i) {
                if (isBody(i)) {
                    result.push_back(i);
                }
            }
            return result;
        }
        // Newer files tag design bodies with a timestamp attribute: take the tagged
        // top-level bodies. Untagged bodies are feature caches and sketch profiles.
        for (int i = 1; i < m_doc.entityCount; ++i) {
            if (isBody(i) && hasTimestamp(i)) {
                result.push_back(i);
            }
        }
        if (!result.empty()) {
            return result;
        }
        // Older files have no tags: current bodies are saved first (leading run of
        // top-level body records); keep the closed ones to drop sketch profile sheets.
        for (int i = 1; i < m_doc.entityCount && isBody(i); ++i) {
            result.push_back(i);
        }
        requireClosed = true;
        return result;
    }

    const Record& rec(int index) const {
        if (index < 0 || static_cast<std::size_t>(index) >= m_doc.records.size()) {
            throw SabError("reference out of range: " + std::to_string(index));
        }
        return m_doc.records[static_cast<std::size_t>(index)];
    }

    static int refAt(const Record& r, std::size_t i) {
        if (i >= r.values.size() || r.values[i].kind != TokenKind::Ref) {
            throw SabError(r.type + ": expected reference at field " + std::to_string(i));
        }
        return static_cast<int>(r.values[i].i);
    }

    static bool flagAt(const Record& r, std::size_t i) {
        Cursor c(r, i);
        return c.flag();
    }

    static double numAt(const Record& r, std::size_t i) {
        if (i >= r.values.size()) {
            throw SabError(r.type + ": record too short");
        }
        return r.values[i].number();
    }

    // Follows a `next` chain starting at `first`, guarding against cycles.
    template <typename Fn> void chain(int first, std::size_t nextField, Fn&& fn) const {
        std::set<int> seen;
        for (int i = first; i >= 0 && seen.insert(i).second; i = refAt(rec(i), nextField)) {
            fn(i);
        }
    }

    void unsupported(const std::string& type) { ++m_unsupported[type]; }

    TopoDS_Vertex vertex(int index) {
        if (auto it = m_vertices.find(index); it != m_vertices.end()) {
            return it->second;
        }
        const Record& pointRec = rec(refAt(rec(index), field::vertex::point));
        Cursor c(pointRec, field::point::position);
        TopoDS_Vertex v;
        BRep_Builder().MakeVertex(v, c.pnt(), m_doc.resabs);
        m_vertices.emplace(index, v);
        return v;
    }

    CurveInfo curve(int index) {
        const Record& r = rec(index);
        Cursor c(r, field::kFirst);
        CurveInfo info;
        if (r.type == "straight-curve") {
            const gp_Pnt root = c.pnt();
            const gp_Vec d = c.vec();
            info.curve = new Geom_Line(root, gp_Dir(d));
            info.paramScale = d.Magnitude();
        } else if (r.type == "ellipse-curve") {
            const gp_Pnt centre = c.pnt();
            const gp_Dir normal = c.dir();
            const gp_Vec major = c.vec();
            const double ratio = c.num();
            const double rMajor = major.Magnitude();
            if (std::abs(ratio - 1.0) < 1e-12) {
                info.curve = new Geom_Circle(gp_Ax2(centre, normal, gp_Dir(major)), rMajor);
            } else if (ratio < 1.0) {
                info.curve =
                    new Geom_Ellipse(gp_Ax2(centre, normal, gp_Dir(major)), rMajor, rMajor * ratio);
            } else {
                // OCCT needs major >= minor: swap axes, which shifts the parameter by -pi/2.
                const gp_Dir minorDir = normal.Crossed(gp_Dir(major));
                info.curve =
                    new Geom_Ellipse(gp_Ax2(centre, normal, minorDir), rMajor * ratio, rMajor);
                info.paramShift = -std::numbers::pi / 2.0;
            }
        } else if (r.type == "intcurve-curve") {
            info.reversed = c.flag();
            // Use the stored B-spline approximation inside the subtype block.
            for (std::size_t i = c.pos(); i < r.values.size(); ++i) {
                const Token& t = r.values[i];
                if (t.kind != TokenKind::String && t.kind != TokenKind::Ident) {
                    continue;
                }
                if (t.s == "nubs" || t.s == "nurbs") {
                    Cursor bs(r, i + 1);
                    info.curve = readBs3Curve(bs, t.s == "nurbs");
                    break;
                }
                if (t.s == "nullbs") {
                    break;
                }
            }
            if (info.curve.IsNull()) {
                unsupported("intcurve without approximation");
            }
        } else {
            unsupported(r.type);
        }
        return info;
    }

    // Returns a null edge if the edge has no supported curve.
    TopoDS_Edge edge(int index) {
        if (auto it = m_edges.find(index); it != m_edges.end()) {
            return it->second;
        }
        const Record& r = rec(index);
        const int startV = refAt(r, field::edge::start);
        const int endV = refAt(r, field::edge::end);
        const double startP = numAt(r, field::edge::startParam);
        const double endP = numAt(r, field::edge::endParam);
        const int curveRef = refAt(r, field::edge::curve);
        const bool reversed = flagAt(r, field::edge::sense);

        TopoDS_Edge e;
        if (curveRef < 0) {
            m_edges.emplace(index, e); // degenerate edge (e.g. cone apex)
            return e;
        }
        const CurveInfo info = curve(curveRef);
        if (info.curve.IsNull()) {
            ++m_stats.skippedEdges;
            m_edges.emplace(index, e);
            return e;
        }

        // Reversed edges use negated parameters on the curve (docs/formats/f3d.md).
        const bool negate = reversed != info.reversed;
        double a = negate ? -endP : startP;
        double b = negate ? -startP : endP;
        a = a * info.paramScale + info.paramShift;
        b = b * info.paramScale + info.paramShift;
        const TopoDS_Vertex va = vertex(negate ? endV : startV);
        const TopoDS_Vertex vb = vertex(negate ? startV : endV);

        BRep_Builder builder;
        builder.MakeEdge(e, info.curve, m_doc.resabs);
        builder.Add(e, va.Oriented(TopAbs_FORWARD));
        builder.Add(e, vb.Oriented(TopAbs_REVERSED));
        builder.Range(e, a, b);
        if (negate) {
            e.Reverse();
        }
        m_edges.emplace(index, e);
        return e;
    }

    Handle(Geom_Surface) surface(int index) {
        const Record& r = rec(index);
        Cursor c(r, field::kFirst);
        if (r.type == "plane-surface") {
            const gp_Pnt root = c.pnt();
            const gp_Dir normal = c.dir();
            const gp_Dir u = c.dir();
            return new Geom_Plane(gp_Ax3(root, normal, u));
        }
        if (r.type == "cone-surface") {
            const gp_Pnt origin = c.pnt();
            const gp_Dir axis = c.dir();
            const gp_Vec major = c.vec();
            const double ratio = c.num();
            c.interval();
            const double sinA = c.num();
            const double cosA = c.num();
            if (std::abs(ratio - 1.0) > 1e-9) {
                unsupported("elliptical cone/cylinder");
                return nullptr;
            }
            const gp_Ax3 ax(origin, axis, gp_Dir(major));
            const double radius = major.Magnitude();
            if (std::abs(sinA) < 1e-12) {
                return new Geom_CylindricalSurface(ax, radius);
            }
            return new Geom_ConicalSurface(ax, std::atan(sinA / cosA), radius);
        }
        if (r.type == "torus-surface") {
            const gp_Pnt centre = c.pnt();
            const gp_Dir axis = c.dir();
            const double major = c.num();
            const double minor = c.num();
            const gp_Dir u = c.dir();
            return new Geom_ToroidalSurface(gp_Ax3(centre, axis, u), std::abs(major),
                                            std::abs(minor));
        }
        if (r.type == "sphere-surface") {
            // Layout not yet verified against samples.
            const gp_Pnt centre = c.pnt();
            const double radius = c.num();
            const gp_Dir u = c.dir();
            const gp_Dir pole = c.dir();
            return new Geom_SphericalSurface(gp_Ax3(centre, pole, u), std::abs(radius));
        }
        unsupported(r.type);
        return nullptr;
    }

    TopoDS_Face face(int index) {
        const Record& r = rec(index);
        Handle(Geom_Surface) surf = surface(refAt(r, field::face::surface));
        if (surf.IsNull()) {
            return {};
        }
        BRep_Builder builder;
        TopoDS_Face f;
        builder.MakeFace(f, surf, m_doc.resabs);

        chain(refAt(r, field::face::loop), field::loop::next, [&](int loopIndex) {
            TopoDS_Wire w;
            builder.MakeWire(w);
            bool complete = true;
            chain(refAt(rec(loopIndex), field::loop::coedge), field::coedge::next,
                  [&](int coedgeIndex) {
                      const Record& ce = rec(coedgeIndex);
                      TopoDS_Edge e = edge(refAt(ce, field::coedge::edge));
                      if (e.IsNull()) {
                          complete = false;
                          return;
                      }
                      if (flagAt(ce, field::coedge::sense)) {
                          e.Reverse();
                      }
                      builder.Add(w, e);
                  });
            w.Closed(complete);
            builder.Add(f, w);
        });

        if (flagAt(r, field::face::sense)) {
            f.Reverse();
        }
        ShapeFix_Face fix(f);
        fix.Perform();
        return fix.Face();
    }

    // True if every coedge of every face in the lump has a partner (a closed B-rep).
    bool shellsClosedInFile(int lumpIndex) const {
        bool closed = true;
        chain(refAt(rec(lumpIndex), field::lump::shell), field::shell::next, [&](int shellIndex) {
            chain(refAt(rec(shellIndex), field::shell::face), field::face::next, [&](int faceIndex) {
                chain(refAt(rec(faceIndex), field::face::loop), field::loop::next, [&](int loopIndex) {
                    chain(refAt(rec(loopIndex), field::loop::coedge), field::coedge::next,
                          [&](int coedgeIndex) {
                              if (refAt(rec(coedgeIndex), field::coedge::partner) < 0) {
                                  closed = false;
                              }
                          });
                });
            });
        });
        return closed;
    }

    // Edges used by only one face (seams and degenerate edges excluded).
    static int freeEdgeCount(const TopoDS_Shape& shape) {
        TopTools_IndexedDataMapOfShapeListOfShape map;
        TopExp::MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, map);
        int n = 0;
        for (int i = 1; i <= map.Extent(); ++i) {
            const TopoDS_Edge& e = TopoDS::Edge(map.FindKey(i));
            if (BRep_Tool::Degenerated(e) || map(i).Extent() != 1 ||
                BRep_Tool::IsClosed(e, TopoDS::Face(map(i).First()))) {
                continue;
            }
            ++n;
        }
        return n;
    }

    TopoDS_Shell sewShell(const TopoDS_Shell& shell) {
        const int freeBefore = freeEdgeCount(shell);
        BRepBuilderAPI_Sewing sewing(std::max(100.0 * m_doc.resabs, 1e-6));
        for (TopExp_Explorer ex(shell, TopAbs_FACE); ex.More(); ex.Next()) {
            sewing.Add(ex.Current());
        }
        sewing.Perform();
        const TopoDS_Shape sewed = sewing.SewedShape();
        TopExp_Explorer ex(sewed, TopAbs_SHELL);
        if (ex.More()) {
            const TopoDS_Shell result = TopoDS::Shell(ex.Current());
            ex.Next();
            if (!ex.More() && BRep_Tool::IsClosed(result)) {
                ++m_stats.sewedShells;
                return result;
            }
        }
        unsupported("shell left open: " + std::to_string(freeBefore) + " free edges, " +
                    std::to_string(freeEdgeCount(sewed)) + " after sewing");
        return shell;
    }

    TopoDS_Shape lump(int index) {
        BRep_Builder builder;
        std::vector<TopoDS_Shell> shells;
        chain(refAt(rec(index), field::lump::shell), field::shell::next, [&](int shellIndex) {
            TopoDS_Shell sh;
            builder.MakeShell(sh);
            chain(refAt(rec(shellIndex), field::shell::face), field::face::next, [&](int faceIndex) {
                try {
                    TopoDS_Face f = face(faceIndex);
                    if (f.IsNull()) {
                        ++m_stats.skippedFaces;
                        return;
                    }
                    builder.Add(sh, f);
                    ++m_stats.faces;
                } catch (const Standard_Failure& e) {
                    ++m_stats.skippedFaces;
                    unsupported(std::string("face (") + e.GetMessageString() + ")");
                } catch (const SabError& e) {
                    ++m_stats.skippedFaces;
                    unsupported(std::string("face (") + e.what() + ")");
                }
            });
            shells.push_back(sh);
        });

        // A shell can come out open although every coedge has a partner in the file, when
        // per-face fixing replaced shared edges (e.g. seams on full cylinders). Sew it.
        if (shellsClosedInFile(index)) {
            for (TopoDS_Shell& s : shells) {
                if (!BRep_Tool::IsClosed(s)) {
                    s = sewShell(s);
                }
            }
        }

        TopoDS_Shape result;
        const bool allClosed = !shells.empty() &&
                               std::all_of(shells.begin(), shells.end(),
                                           [](const TopoDS_Shell& s) { return BRep_Tool::IsClosed(s); });
        if (allClosed) {
            TopoDS_Solid solid;
            builder.MakeSolid(solid);
            for (const TopoDS_Shell& s : shells) {
                builder.Add(solid, s);
            }
            result = solid;
            ++m_stats.solids;
        } else {
            TopoDS_Compound open;
            builder.MakeCompound(open);
            for (const TopoDS_Shell& s : shells) {
                builder.Add(open, s);
            }
            result = open;
        }

        // Builds pcurves, fixes tolerances and orients shells/solids consistently.
        ShapeFix_Shape fix(result);
        fix.Perform();
        return fix.Shape();
    }

    TopoDS_Shape body(int index) {
        const Record& r = rec(index);
        BRep_Builder builder;
        TopoDS_Compound comp;
        builder.MakeCompound(comp);
        chain(refAt(r, field::body::lump), field::lump::next, [&](int lumpIndex) {
            TopoDS_Shape l = lump(lumpIndex);
            if (!l.IsNull()) {
                builder.Add(comp, l);
            }
        });

        const int transformRef = refAt(r, field::body::transform);
        if (transformRef >= 0) {
            const gp_Trsf t = transform(rec(transformRef));
            if (t.Form() != gp_Identity) {
                return BRepBuilderAPI_Transform(comp, t, true).Shape();
            }
        }
        return comp;
    }

    gp_Trsf transform(const Record& r) {
        // Rows are the images of the X/Y/Z axes (row-vector convention), so they become
        // columns in OCCT's matrix. Only identity transforms have been seen in samples.
        Cursor c(r, field::kFirst - 1);
        const gp_XYZ x = c.xyz();
        const gp_XYZ y = c.xyz();
        const gp_XYZ z = c.xyz();
        const gp_XYZ t = c.xyz();
        const double s = c.num();
        const bool identity = x.IsEqual(gp_XYZ(1, 0, 0), 1e-12) && y.IsEqual(gp_XYZ(0, 1, 0), 1e-12) &&
                              z.IsEqual(gp_XYZ(0, 0, 1), 1e-12) && t.Modulus() < 1e-12 &&
                              std::abs(s - 1.0) < 1e-12;
        if (identity) {
            return {};
        }
        gp_Trsf trsf;
        trsf.SetValues(x.X() * s, y.X() * s, z.X() * s, t.X(), //
                       x.Y() * s, y.Y() * s, z.Y() * s, t.Y(), //
                       x.Z() * s, y.Z() * s, z.Z() * s, t.Z());
        unsupported("non-identity body transform (convention unverified)");
        return trsf;
    }

    const sab::Document& m_doc;
    ConversionStats& m_stats;
    BodySelection m_selection;
    std::unordered_map<int, TopoDS_Vertex> m_vertices;
    std::unordered_map<int, TopoDS_Edge> m_edges;
    std::map<std::string, int> m_unsupported;
};

} // namespace

TopoDS_Shape convertToOcct(const sab::Document& doc, ConversionStats& stats,
                           BodySelection selection) {
    return Converter(doc, stats, selection).run();
}

} // namespace fission::io::detail
