#pragma once

#include "fission/kernel/Shape.h"

#include <vector>

namespace fission::kernel {

// Groups shapes without merging them (separate bodies). Null shapes are skipped.
Shape makeCompound(const std::vector<Shape>& shapes);

} // namespace fission::kernel
