#include "fission/kernel/occt/Native.h"

namespace fission::kernel {

Shape::Shape() = default;

Shape::Shape(std::shared_ptr<const Impl> impl) : m_impl(std::move(impl)) {}

bool Shape::isNull() const { return !m_impl || m_impl->shape.IsNull(); }

namespace occt {

Shape wrap(const TopoDS_Shape& shape) {
    return Shape(std::make_shared<const Shape::Impl>(Shape::Impl{shape}));
}

const TopoDS_Shape& native(const Shape& shape) {
    static const TopoDS_Shape empty;
    return shape.impl() ? shape.impl()->shape : empty;
}

} // namespace occt
} // namespace fission::kernel
