#pragma once

#include "fission/kernel/Shape.h"

#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <vector>

namespace fission::io {

struct F3dImportResult {
    kernel::Shape shape; // compound of all bodies, in millimetres
    int blobs = 0;       // B-rep blobs read
    int bodies = 0;
    int solids = 0;
    int faces = 0;
    int skippedFaces = 0;
    std::vector<std::string> warnings;
};

// Imports the B-rep geometry of a Fusion 360 .f3d design.
// Parametric history, sketches and component placement are not decoded yet
// (docs/formats/f3d.md); each component's bodies are imported in their stored position.
F3dImportResult importF3d(const std::filesystem::path& path);

// Imports a single ShapeManager B-rep blob (.smb).
F3dImportResult importAsmBlob(std::span<const std::uint8_t> data);

} // namespace fission::io
