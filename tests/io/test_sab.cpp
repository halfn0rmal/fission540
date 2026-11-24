// Builds a minimal ASM BinaryFile4 blob in memory (a 1 cm cube, laid out the way Fusion
// writes it, see docs/formats/f3d.md) and checks the reader end to end. Real .f3d files
// can't be committed, so this is what CI runs.

#include "fission/io/F3dImport.h"
#include "fission/io/Sab.h"
#include "fission/kernel/Properties.h"

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

#include <array>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <utility>
#include <vector>

using namespace fission;
using Catch::Matchers::WithinAbs;
using Catch::Matchers::WithinRel;

namespace {

class SabWriter {
public:
    SabWriter() {
        const char magic[] = "ASM BinaryFile4";
        m_buf.insert(m_buf.end(), magic, magic + 15);
        raw<std::int64_t>(22900);
        raw<std::int32_t>(0);
        raw<std::int32_t>(0);
        str("Fission540 test");
        str("ASM 229.10.0.65535 NT");
        str("Mon Jan  1 00:00:00 2024");
        dbl(10.0); // mm per unit (cm)
        dbl(1e-6);
        dbl(1e-10);
    }

    template <typename T> void raw(T v) {
        std::uint8_t bytes[sizeof(T)];
        std::memcpy(bytes, &v, sizeof(T));
        m_buf.insert(m_buf.end(), bytes, bytes + sizeof(T));
    }
    void tag(std::uint8_t t) { m_buf.push_back(t); }
    void name(std::uint8_t t, const std::string& s) {
        tag(t);
        m_buf.push_back(static_cast<std::uint8_t>(s.size()));
        m_buf.insert(m_buf.end(), s.begin(), s.end());
    }
    void ident(const std::string& s) { name(0x0D, s); }
    void subident(const std::string& s) { name(0x0E, s); }
    void str(const std::string& s) { name(0x07, s); }
    void lng(std::int32_t v) { tag(0x04); raw(v); }
    void dbl(double v) { tag(0x06); raw(v); }
    void ref(int v) { tag(0x0C); raw<std::int32_t>(v); }
    void flag(bool v) { tag(v ? 0x0A : 0x0B); }
    void xyz(std::uint8_t t, const std::array<double, 3>& p) {
        tag(t);
        for (double c : p) {
            raw(c);
        }
    }
    void pos(const std::array<double, 3>& p) { xyz(0x13, p); }
    void vec(const std::array<double, 3>& p) { xyz(0x14, p); }
    void end() { tag(0x11); }
    // Every entity starts with: attrib, history id, unused ref.
    void common() {
        ref(-1);
        lng(-1);
        ref(-1);
    }

    const std::vector<std::uint8_t>& bytes() const { return m_buf; }

private:
    std::vector<std::uint8_t> m_buf;
};

using P3 = std::array<double, 3>;

// Unit cube in model units (cm).
std::vector<std::uint8_t> makeCubeBlob() {
    // Record indices.
    constexpr int kBody = 1, kLump = 2, kShell = 3, kFace0 = 4, kLoop0 = 10, kCoedge0 = 16,
                  kEdge0 = 40, kVertex0 = 52, kPoint0 = 60, kCurve0 = 68, kSurface0 = 80;

    auto corner = [](int v) { return P3{double(v & 1), double((v >> 1) & 1), double((v >> 2) & 1)}; };

    // Edges: from vertex a to vertex b along +axis.
    std::vector<std::pair<int, int>> edges;
    std::map<std::pair<int, int>, int> edgeIndex;
    for (int v = 0; v < 8; ++v) {
        for (int axis = 0; axis < 3; ++axis) {
            if (!(v & (1 << axis))) {
                const int w = v | (1 << axis);
                edgeIndex[{v, w}] = static_cast<int>(edges.size());
                edges.emplace_back(v, w);
            }
        }
    }

    // Faces: axis k at side s, corners counter-clockwise about the outward normal.
    struct Face {
        P3 normal;
        P3 u;
        std::array<int, 4> corners;
    };
    std::vector<Face> faces;
    for (int k = 0; k < 3; ++k) {
        for (int s = 0; s < 2; ++s) {
            int a = (k + 1) % 3, b = (k + 2) % 3; // a x b = +k
            if (s == 0) {
                std::swap(a, b); // a x b = -k
            }
            auto vtx = [&](int i, int j) { return (s << k) | (i << a) | (j << b); };
            Face f{};
            f.normal[k] = s ? 1.0 : -1.0;
            f.u[a] = 1.0;
            f.corners = {vtx(0, 0), vtx(1, 0), vtx(1, 1), vtx(0, 1)};
            faces.push_back(f);
        }
    }

    SabWriter w;
    // 0: header
    w.ident("asmheader");
    w.ref(-1);
    w.lng(-1);
    w.str("229.10.0.65535");
    w.end();
    // 1: body
    w.ident("body");
    w.common();
    w.ref(kLump);
    w.ref(-1);
    w.ref(-1);
    w.end();
    // 2: lump
    w.ident("lump");
    w.common();
    w.ref(-1);
    w.ref(kShell);
    w.ref(kBody);
    w.end();
    // 3: shell
    w.ident("shell");
    w.common();
    w.ref(-1);
    w.ref(-1);
    w.ref(kFace0);
    w.ref(-1);
    w.ref(kLump);
    w.end();
    // faces
    for (int f = 0; f < 6; ++f) {
        w.ident("face");
        w.common();
        w.ref(f < 5 ? kFace0 + f + 1 : -1);
        w.ref(kLoop0 + f);
        w.ref(kShell);
        w.ref(-1);
        w.ref(kSurface0 + f);
        w.flag(false);
        w.flag(false);
        w.end();
    }
    // loops
    for (int f = 0; f < 6; ++f) {
        w.ident("loop");
        w.common();
        w.ref(-1);
        w.ref(kCoedge0 + 4 * f);
        w.ref(kFace0 + f);
        w.end();
    }
    // coedges
    for (int f = 0; f < 6; ++f) {
        for (int i = 0; i < 4; ++i) {
            const int from = faces[f].corners[i];
            const int to = faces[f].corners[(i + 1) % 4];
            const bool reversed = from > to;
            const int e = edgeIndex.at(reversed ? std::pair{to, from} : std::pair{from, to});
            w.ident("coedge");
            w.common();
            w.ref(kCoedge0 + 4 * f + (i + 1) % 4);
            w.ref(kCoedge0 + 4 * f + (i + 3) % 4);
            w.ref(-1);
            w.ref(kEdge0 + e);
            w.flag(reversed);
            w.ref(kLoop0 + f);
            w.lng(0);
            w.ref(-1);
            w.end();
        }
    }
    // edges
    for (std::size_t e = 0; e < edges.size(); ++e) {
        w.ident("edge");
        w.common();
        w.ref(kVertex0 + edges[e].first);
        w.dbl(0.0);
        w.ref(kVertex0 + edges[e].second);
        w.dbl(1.0);
        w.ref(-1);
        w.ref(kCurve0 + static_cast<int>(e));
        w.flag(false);
        w.str("convex");
        w.end();
    }
    // vertices
    for (int v = 0; v < 8; ++v) {
        w.ident("vertex");
        w.common();
        w.ref(kEdge0);
        w.lng(0);
        w.ref(kPoint0 + v);
        w.end();
    }
    // points
    for (int v = 0; v < 8; ++v) {
        w.ident("point");
        w.common();
        w.pos(corner(v));
        w.end();
    }
    // straight curves
    for (const auto& [a, b] : edges) {
        const P3 pa = corner(a), pb = corner(b);
        w.subident("straight");
        w.ident("curve");
        w.common();
        w.pos(pa);
        w.vec({pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]});
        w.flag(false);
        w.flag(false);
        w.end();
    }
    // planes
    for (const Face& f : faces) {
        w.subident("plane");
        w.ident("surface");
        w.common();
        w.pos(corner(f.corners[0]));
        w.vec(f.normal);
        w.vec(f.u);
        for (int i = 0; i < 5; ++i) {
            w.flag(false);
        }
        w.end();
    }
    w.subident("End");
    w.subident("of");
    w.subident("ASM");
    w.ident("data");
    w.end();
    return w.bytes();
}

} // namespace

TEST_CASE("SAB parser reads header and records", "[io]") {
    const auto blob = makeCubeBlob();
    const io::sab::Document doc = io::sab::parse(blob);
    CHECK(doc.version == 22900);
    CHECK(doc.product == "Fission540 test");
    CHECK(doc.mmPerUnit == 10.0);
    REQUIRE(doc.records.size() == 86);
    CHECK(doc.records[0].type == "asmheader");
    CHECK(doc.records[1].type == "body");
    CHECK(doc.records[68].type == "straight-curve");
    CHECK(doc.records[80].type == "plane-surface");
}

TEST_CASE("SAB parser rejects bad data", "[io]") {
    const std::vector<std::uint8_t> junk = {'n', 'o', 'p', 'e'};
    CHECK_THROWS_AS(io::sab::parse(junk), io::sab::SabError);

    auto blob = makeCubeBlob();
    blob.resize(blob.size() / 2);
    CHECK_THROWS_AS(io::sab::parse(blob), io::sab::SabError);
}

TEST_CASE("ASM cube converts to a valid 10 mm solid", "[io]") {
    const auto blob = makeCubeBlob();
    const io::F3dImportResult result = io::importAsmBlob(blob);
    CHECK(result.bodies == 1);
    CHECK(result.solids == 1);
    CHECK(result.faces == 6);
    CHECK(result.skippedFaces == 0);
    CHECK(kernel::isValid(result.shape));
    CHECK(kernel::faceCount(result.shape) == 6);
    CHECK_THAT(kernel::volume(result.shape), WithinRel(1000.0, 1e-6));
    CHECK_THAT(kernel::surfaceArea(result.shape), WithinRel(600.0, 1e-6));
}
