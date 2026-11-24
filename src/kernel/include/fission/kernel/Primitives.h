#pragma once

#include "fission/kernel/Shape.h"

namespace fission::kernel {

struct Point3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

// Axis-aligned box with its minimum corner at `origin`. Sizes are in mm and must be > 0.
Shape makeBox(double dx, double dy, double dz, Point3 origin = {});

} // namespace fission::kernel
