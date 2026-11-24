#include "fission/features/ImportedBodyFeature.h"

#include "fission/kernel/Compound.h"
#include "fission/kernel/Error.h"

namespace fission::features {

ImportedBodyFeature::ImportedBodyFeature(std::string id, std::string name, kernel::Shape shape,
                                         std::string source)
    : core::Feature(std::move(id), std::move(name)), m_shape(std::move(shape)),
      m_source(std::move(source)) {}

kernel::Shape ImportedBodyFeature::execute(const kernel::Shape& input) {
    if (m_shape.isNull()) {
        throw kernel::KernelError("Imported geometry is empty");
    }
    if (input.isNull()) {
        return m_shape;
    }
    return kernel::makeCompound({input, m_shape});
}

} // namespace fission::features
