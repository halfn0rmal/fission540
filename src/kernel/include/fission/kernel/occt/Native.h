#pragma once

// Escape hatch to the OCCT representation. Only the viewer and kernel
// internals may include this; modelling code must stay kernel-agnostic.

#include "fission/kernel/Shape.h"

#include <TopoDS_Shape.hxx>

namespace fission::kernel {

struct Shape::Impl {
    TopoDS_Shape shape;
};

namespace occt {

Shape wrap(const TopoDS_Shape& shape);
const TopoDS_Shape& native(const Shape& shape);

} // namespace occt
} // namespace fission::kernel
