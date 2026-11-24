// fission-f3d2step: convert the geometry of a Fusion 360 .f3d to STEP and report what was read.
//
//   fission-f3d2step design.f3d [out.step]

#include "fission/io/F3dImport.h"
#include "fission/io/StepExport.h"
#include "fission/io/ZipArchive.h"
#include "fission/kernel/Properties.h"

#include <cstdio>
#include <exception>
#include <filesystem>

int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s design.f3d [out.step]\n", argv[0]);
        return 2;
    }
    try {
        const std::filesystem::path in = argv[1];
        const auto result = fission::io::importF3d(in);
        std::printf("blobs=%d bodies=%d solids=%d faces=%d skipped_faces=%d volume_mm3=%.6f\n",
                    result.blobs, result.bodies, result.solids, result.faces, result.skippedFaces,
                    fission::kernel::volume(result.shape));
        for (const auto& w : result.warnings) {
            std::printf("warning: %s\n", w.c_str());
        }
        if (argc >= 3) {
            fission::io::exportStep(result.shape, argv[2]);
            std::printf("wrote %s\n", argv[2]);
        }
        return result.skippedFaces == 0 ? 0 : 1;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        return 2;
    }
}
