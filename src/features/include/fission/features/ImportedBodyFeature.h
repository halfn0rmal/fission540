#pragma once

#include "fission/core/Feature.h"

namespace fission::features {

// Fixed (non-parametric) geometry brought in from another file, e.g. a Fusion .f3d or STEP.
// Added as separate bodies alongside whatever the timeline has built so far.
class ImportedBodyFeature : public core::Feature {
public:
    ImportedBodyFeature(std::string id, std::string name, kernel::Shape shape, std::string source);

    [[nodiscard]] std::string typeName() const override { return "Import"; }
    [[nodiscard]] const std::string& source() const { return m_source; }

protected:
    kernel::Shape execute(const kernel::Shape& input) override;

private:
    kernel::Shape m_shape;
    std::string m_source;
};

} // namespace fission::features
