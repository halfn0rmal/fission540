#pragma once

#include "fission/kernel/Shape.h"

namespace fission::kernel {

Shape fuse(const Shape& a, const Shape& b);
Shape cut(const Shape& a, const Shape& tool);
Shape common(const Shape& a, const Shape& b);

} // namespace fission::kernel
