#pragma once

#include "fission/kernel/Shape.h"

#include <filesystem>

namespace fission::io {

// Writes `shape` (millimetres) as STEP AP214. Throws IoError on failure.
void exportStep(const kernel::Shape& shape, const std::filesystem::path& path);

} // namespace fission::io
