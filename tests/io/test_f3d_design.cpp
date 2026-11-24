// Synthetic MetaStream/BulkStream pair laid out as observed in Fusion files
// (docs/formats/f3d.md): one component with a B-rep blob and two occurrences of it,
// one at identity and one rotated + translated.

#include "fission/io/F3dDesign.h"

#include <catch2/catch_test_macros.hpp>

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

using namespace fission::io;

namespace {

class Buf {
public:
    void u8(std::uint8_t v) { m_b.push_back(v); }
    void u32(std::uint32_t v) { raw(&v, 4); }
    void u64(std::uint64_t v) { raw(&v, 8); }
    void f64(double v) { raw(&v, 8); }
    void ascii(const std::string& s) { raw(s.data(), s.size()); }
    void zeros(std::size_t n) { m_b.insert(m_b.end(), n, 0); }
    void utf16(const std::string& s) {
        u32(static_cast<std::uint32_t>(s.size()));
        for (char c : s) {
            u8(static_cast<std::uint8_t>(c));
            u8(0);
        }
    }
    // u32 n, n ASCII digits (class version tag), u64 id
    void header(const std::string& tag, std::uint64_t id) {
        u32(static_cast<std::uint32_t>(tag.size()));
        ascii(tag);
        u64(id);
    }
    void ref(std::uint64_t id, std::size_t trailing = 2) {
        u8(1);
        u64(id);
        zeros(trailing);
    }
    void type(const std::string& cls, const std::string& parent, std::uint32_t index,
              const std::string& module, const std::vector<std::uint64_t>& ids) {
        u32(36);
        ascii(cls);
        u32(36);
        ascii(parent);
        u32(index);
        u32(static_cast<std::uint32_t>(module.size()));
        ascii(module);
        u32(static_cast<std::uint32_t>(ids.size()));
        for (auto id : ids) {
            u64(id);
        }
    }
    const std::vector<std::uint8_t>& bytes() const { return m_b; }

private:
    void raw(const void* p, std::size_t n) {
        auto* c = static_cast<const std::uint8_t*>(p);
        m_b.insert(m_b.end(), c, c + n);
    }
    std::vector<std::uint8_t> m_b;
};

const std::string kParent = "6370B480-4C9F-4AF3-A8DD-D364B7AF7275";
const std::string kBlob = "0123abcd-0000-4000-8000-0123456789ab";

void occurrence(Buf& b, std::uint64_t id, std::uint64_t component, const double* matrix) {
    b.header("341", id);
    b.zeros(6);
    b.u32(9);
    b.ascii("Transform");
    b.u8(0);
    b.ref(id, 3);
    b.ref(component);
    b.utf16("1_1234");
    b.u8(0);
    b.ref(component);
    if (matrix == nullptr) {
        b.u8(1); // identity
    } else {
        b.u8(0);
        for (int i = 0; i < 16; ++i) {
            b.f64(matrix[i]);
        }
    }
    b.zeros(9);
}

// Rotation 90 degrees about Z, translation (1, 2, 3) cm.
const double kMoved[16] = {0, -1, 0, 1, 1, 0, 0, 2, 0, 0, 1, 3, 0, 0, 0, 1};

std::pair<std::vector<std::uint8_t>, std::vector<std::uint8_t>> makeSegment() {
    Buf meta;
    meta.header("23", 0); // unrelated leading bytes
    meta.type(f3d::kComponentClass, kParent, 1, "Fusion", {0x10});
    meta.type(f3d::kBodyContainerClass, kParent, 2, "Body", {0x20});
    meta.type(f3d::kOccurrenceClass, kParent, 3, "Component", {0x30, 0x31});

    Buf bulk;
    bulk.zeros(16);
    bulk.header("312", 0x10);
    bulk.zeros(4);
    bulk.utf16("Widget");
    bulk.zeros(8);
    bulk.header("316", 0x20);
    bulk.zeros(12);
    bulk.ref(0x10);
    bulk.utf16("BREP." + kBlob + ".smbh"); // history blob must be ignored
    bulk.utf16("BREP." + kBlob + ".smb");
    bulk.zeros(8);
    occurrence(bulk, 0x30, 0x10, nullptr);
    occurrence(bulk, 0x31, 0x10, kMoved);
    return {meta.bytes(), bulk.bytes()};
}

} // namespace

TEST_CASE("Type table lists classes with their objects", "[io][f3d]") {
    const auto [meta, bulk] = makeSegment();
    const auto types = f3d::parseTypeTable(meta);
    REQUIRE(types.size() == 3);
    CHECK(types[0].classGuid == f3d::kComponentClass);
    CHECK(types[0].module == "Fusion");
    CHECK(types[2].module == "Component");
    CHECK(types[2].objectIds == std::vector<std::uint64_t>{0x30, 0x31});
}

TEST_CASE("Object headers are found by id", "[io][f3d]") {
    const auto [meta, bulk] = makeSegment();
    const auto h = f3d::findObjectHeader(bulk, 0x20);
    REQUIRE(h.has_value());
    CHECK(bulk[*h] == 3);
    CHECK(!f3d::findObjectHeader(bulk, 0x99).has_value());
}

TEST_CASE("Design decodes components, blobs and occurrence placement", "[io][f3d]") {
    const auto [meta, bulk] = makeSegment();
    const f3d::Design d = f3d::parseDesign(meta, bulk);
    CHECK(d.warnings.empty());

    REQUIRE(d.components.size() == 1);
    CHECK(d.components[0].name == "Widget");
    CHECK(d.components[0].blobGuid == kBlob);

    REQUIRE(d.occurrences.size() == 2);
    CHECK(d.occurrences[0].component == 0x10);
    CHECK(d.occurrences[0].identity);

    const f3d::Occurrence& moved = d.occurrences[1];
    CHECK_FALSE(moved.identity);
    for (int i = 0; i < 16; ++i) {
        CHECK(moved.matrix[i] == kMoved[i]);
    }
}
