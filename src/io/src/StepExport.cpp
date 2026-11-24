#include "fission/io/StepExport.h"

#include "fission/io/ZipArchive.h"
#include "fission/kernel/occt/Native.h"

#include <IFSelect_ReturnStatus.hxx>
#include <Interface_Static.hxx>
#include <STEPControl_Writer.hxx>

namespace fission::io {

void exportStep(const kernel::Shape& shape, const std::filesystem::path& path) {
    if (shape.isNull()) {
        throw IoError("exportStep: empty shape");
    }
    STEPControl_Writer writer;
    Interface_Static::SetCVal("write.step.schema", "AP214IS");
    Interface_Static::SetCVal("write.step.unit", "MM");
    if (writer.Transfer(kernel::occt::native(shape), STEPControl_AsIs) != IFSelect_RetDone) {
        throw IoError("exportStep: transfer failed");
    }
    if (writer.Write(path.string().c_str()) != IFSelect_RetDone) {
        throw IoError("exportStep: cannot write " + path.string());
    }
}

} // namespace fission::io
