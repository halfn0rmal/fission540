// Imports every .f3d in $FISSION_F3D_SAMPLES (local only; design files are never committed).
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
        const io::F3dImportResult result = io::importF3d(entry.path());
        for (const auto& w : result.warnings) {
            UNSCOPED_INFO("warning: " << w);
        }
        CHECK(result.skippedFaces == 0);
        CHECK(result.solids > 0);
        CHECK(kernel::isValid(result.shape));
        const double volume = kernel::volume(result.shape);
        CHECK(volume > 0.0);
        if (auto it = expected.find(name); it != expected.end()) {
            CHECK_THAT(volume, Catch::Matchers::WithinRel(it->second, 1e-4));
        }
    }
    CHECK(files > 0);
}
