#include "fission/features/BoxFeature.h"

#include "fission/kernel/Booleans.h"
#include "fission/kernel/Error.h"

namespace fission::features {

BoxFeature::BoxFeature(std::string id, std::string name, Params params)
    : core::Feature(std::move(id), std::move(name)), m_params(params) {}

kernel::Shape BoxFeature::execute(const kernel::Shape& input) {
    kernel::Shape box = kernel::makeBox(m_params.dx, m_params.dy, m_params.dz, m_params.origin);
    if (input.isNull()) {
        if (m_params.operation != BodyOperation::Join) {
            throw kernel::KernelError("No body to cut or intersect");
        }
        return box;
    }
    switch (m_params.operation) {
    case BodyOperation::Join:
        return kernel::fuse(input, box);
    case BodyOperation::Cut:
        return kernel::cut(input, box);
    case BodyOperation::Intersect:
        return kernel::common(input, box);
    }
    return input;
}

} // namespace fission::features
