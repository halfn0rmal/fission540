#include "fission/kernel/Booleans.h"

#include "fission/kernel/Error.h"
#include "fission/kernel/occt/Native.h"

#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <Standard_Failure.hxx>

namespace fission::kernel {
namespace {

template <typename Op>
Shape runBoolean(const char* name, const Shape& a, const Shape& b) {
    if (a.isNull() || b.isNull()) {
        throw KernelError(std::string(name) + ": null operand");
    }
    try {
        Op op(occt::native(a), occt::native(b));
        if (!op.IsDone() || op.HasErrors()) {
            throw KernelError(std::string(name) + ": operation failed");
        }
        return occt::wrap(op.Shape());
    } catch (const Standard_Failure& e) {
        throw KernelError(std::string(name) + ": " + e.GetMessageString());
    }
}

} // namespace

Shape fuse(const Shape& a, const Shape& b) { return runBoolean<BRepAlgoAPI_Fuse>("fuse", a, b); }

Shape cut(const Shape& a, const Shape& tool) {
    return runBoolean<BRepAlgoAPI_Cut>("cut", a, tool);
}

Shape common(const Shape& a, const Shape& b) {
    return runBoolean<BRepAlgoAPI_Common>("common", a, b);
}

} // namespace fission::kernel
