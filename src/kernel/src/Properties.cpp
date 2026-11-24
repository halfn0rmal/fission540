#include "fission/kernel/Properties.h"

#include "fission/kernel/occt/Native.h"

#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>

namespace fission::kernel {

double volume(const Shape& shape) {
    if (shape.isNull()) {
        return 0.0;
    }
    GProp_GProps props;
    BRepGProp::VolumeProperties(occt::native(shape), props);
    return props.Mass();
}

double surfaceArea(const Shape& shape) {
    if (shape.isNull()) {
        return 0.0;
    }
    GProp_GProps props;
    BRepGProp::SurfaceProperties(occt::native(shape), props);
    return props.Mass();
}

int faceCount(const Shape& shape) {
    int count = 0;
    for (TopExp_Explorer it(occt::native(shape), TopAbs_FACE); it.More(); it.Next()) {
        ++count;
    }
    return count;
}

int solidCount(const Shape& shape) {
    int count = 0;
    for (TopExp_Explorer it(occt::native(shape), TopAbs_SOLID); it.More(); it.Next()) {
        ++count;
    }
    return count;
}

bool isValid(const Shape& shape) {
    if (shape.isNull()) {
        return false;
    }
    return BRepCheck_Analyzer(occt::native(shape)).IsValid();
}

} // namespace fission::kernel
