#pragma once

#include "fission/kernel/Shape.h"

namespace fission::kernel {

double volume(const Shape& shape);
double surfaceArea(const Shape& shape);
int faceCount(const Shape& shape);
int solidCount(const Shape& shape);

// True if the shape passes OCCT topology/geometry checks.
bool isValid(const Shape& shape);

} // namespace fission::kernel
