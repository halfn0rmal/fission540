#pragma once

#include <memory>

namespace fission::kernel {

// Immutable handle to a B-rep shape. Cheap to copy (shared ownership).
// The kernel implementation behind it is private to this module; the rest of
// the application must only use the operations declared in fission/kernel/*.h.
class Shape {
public:
    struct Impl;

    Shape();
    explicit Shape(std::shared_ptr<const Impl> impl);

    [[nodiscard]] bool isNull() const;
    [[nodiscard]] const Impl* impl() const { return m_impl.get(); }

private:
    std::shared_ptr<const Impl> m_impl;
};

} // namespace fission::kernel
