// Imports the committed sample in tests/data/f3d, and every .f3d in $FISSION_F3D_SAMPLES
// (local designs that are not committed):
//
//   FISSION_F3D_SAMPLES=~/f3d-samples ctest --preset release -R f3d
//
// Optional expected volumes: a file `volumes.txt` in the same folder with lines
// `<file name> <volume in mm^3>` (from Fusion: Inspect > Properties).

#include "fission/io/F3dImport.h"
#include "fission/kernel/Properties.h"

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <string>

using namespace fission;
namespace fs = std::filesystem;

namespace {

std::string joinWarnings(const io::F3dImportResult& result) {
    std::string out;
    for (const auto& w : result.warnings) {
        out += "
  warning: " + w;
    }
    return out;
}

// Checks that hold for every design the importer supports.
io::F3dImportResult importAndCheck(const fs::path& path) {
    INFO(path.filename().string());
    io::F3dImportResult result = io::importF3d(path);
    INFO(joinWarnings(result));
    CHECK(result.skippedFaces == 0);
    CHECK(result.solids > 0);
    CHECK(kernel::isValid(result.shape));
    CHECK(kernel::volume(result.shape) > 0.0);
    return result;
}

} // namespace

// Single-component design from Fusion's local cache (2025 build). Body count is what the
// current-body heuristic selects (docs/formats/f3d.md), not yet checked against Fusion.
TEST_CASE("Import committed .f3d sample", "[io][f3d]") {
    const fs::path path = fs::path(FISSION_TEST_DATA_DIR) / "f3d" / "TJ-AshTrayDelete.f3d";
    REQUIRE(fs::is_regular_file(path));
    const io::F3dImportResult result = importAndCheck(path);
    INFO(joinWarnings(result));
    CHECK(result.blobs == 1);
    CHECK(result.bodies == 5);
    CHECK(result.solids == 5);
    REQUIRE(result.instances.size() == 1);
    CHECK(result.instances[0].component == "Part Number");
}

TEST_CASE("Import local .f3d samples", "[io][f3d]") {
    const char* dir = std::getenv("FISSION_F3D_SAMPLES");
    if (dir == nullptr || !fs::is_directory(dir)) {
        SKIP("FISSION_F3D_SAMPLES not set");
    }

    std::map<std::string, double> expected;
    if (std::ifstream in(fs::path(dir) / "volumes.txt"); in) {
        std::string line;
        while (std::getline(in, line)) {
            std::istringstream ss(line);
            std::string name;
            double volume = 0.0;
            if (ss >> name >> volume) {
                expected[name] = volume;
            }
        }
    }

    int files = 0;
    for (const auto& entry : fs::directory_iterator(dir)) {
        if (entry.path().extension() != ".f3d") {
            continue;
        }
        ++files;
        const std::string name = entry.path().filename().string();
        INFO(name);
        const io::F3dImportResult result = importAndCheck(entry.path());
        INFO(joinWarnings(result));
        if (auto it = expected.find(name); it != expected.end()) {
            CHECK_THAT(kernel::volume(result.shape), Catch::Matchers::WithinRel(it->second, 1e-4));
        }
    }
    CHECK(files > 0);
}
