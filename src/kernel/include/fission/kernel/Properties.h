#pragma once

#include "fission/kernel/Shape.h"

namespace fission::kernel {

double volume(const Shape& shape);
double surfaceArea(const Shape& shape);
int faceCount(const Shape& shape);

} // namespace fission::kernel
