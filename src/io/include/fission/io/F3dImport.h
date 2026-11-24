#pragma once

#include "fission/kernel/Shape.h"

#include <array>
#include <cstdint>
#include <filesystem>
#include <span>
#include <string>
#include <vector>

namespace fission::io {

// One placed occurrence of a component.
struct F3dInstance {
    std::string component;
    // Row-major 4x4, translation (m[3], m[7], m[11]) in millimetres.
    std::array<double, 16> transform{};
};

struct F3dImportResult {
    kernel::Shape shape; // compound of all placed bodies, in millimetres
    int blobs = 0;       // B-rep blobs read (each converted once)
    int bodies = 0;      // bodies kept across blobs (per blob, not per instance)
    int solids = 0;
    int faces = 0;
    int skippedFaces = 0;
    int ignoredBodies = 0; // feature-cache / sketch bodies in the blobs that were not imported
    std::vector<F3dInstance> instances;
    std::vector<std::string> warnings;
};

// Imports the B-rep geometry of a Fusion 360 .f3d design, with every component
// occurrence placed by its transform. Parametric history and sketches are not decoded
// yet (docs/formats/f3d.md).
F3dImportResult importF3d(const std::filesystem::path& path);

// Imports a single ShapeManager B-rep blob (.smb).
F3dImportResult importAsmBlob(std::span<const std::uint8_t> data);

} // namespace fission::io
