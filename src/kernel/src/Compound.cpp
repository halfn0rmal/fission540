#include "fission/kernel/Compound.h"

#include "fission/kernel/occt/Native.h"

#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>

namespace fission::kernel {

Shape makeCompound(const std::vector<Shape>& shapes) {
    BRep_Builder builder;
    TopoDS_Compound compound;
    builder.MakeCompound(compound);
    for (const Shape& s : shapes) {
        if (!s.isNull()) {
            builder.Add(compound, occt::native(s));
        }
    }
    return occt::wrap(compound);
}

} // namespace fission::kernel
