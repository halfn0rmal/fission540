#include "fission/kernel/Primitives.h"

#include "fission/kernel/Error.h"
#include "fission/kernel/occt/Native.h"

#include <BRepPrimAPI_MakeBox.hxx>
#include <Standard_Failure.hxx>
#include <gp_Pnt.hxx>

namespace fission::kernel {

Shape makeBox(double dx, double dy, double dz, Point3 origin) {
    if (dx <= 0.0 || dy <= 0.0 || dz <= 0.0) {
        throw KernelError("makeBox: dimensions must be positive");
    }
    try {
        BRepPrimAPI_MakeBox maker(gp_Pnt(origin.x, origin.y, origin.z), dx, dy, dz);
        return occt::wrap(maker.Shape());
    } catch (const Standard_Failure& e) {
        throw KernelError(std::string("makeBox: ") + e.GetMessageString());
    }
}

} // namespace fission::kernel
