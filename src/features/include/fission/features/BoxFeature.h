#pragma once

#include "fission/core/Feature.h"
#include "fission/kernel/Primitives.h"

namespace fission::features {

enum class BodyOperation {
    Join,
    Cut,
    Intersect,
};

// Placeholder primitive used until sketch + extrude exist (Phases 1-2).
class BoxFeature : public core::Feature {
public:
    struct Params {
        double dx = 10.0;
        double dy = 10.0;
        double dz = 10.0;
        kernel::Point3 origin{};
        BodyOperation operation = BodyOperation::Join;
    };

    BoxFeature(std::string id, std::string name, Params params);

    [[nodiscard]] std::string typeName() const override { return "Box"; }

    [[nodiscard]] const Params& params() const { return m_params; }
    void setParams(const Params& params) { m_params = params; }

protected:
    kernel::Shape execute(const kernel::Shape& input) override;

private:
    Params m_params;
};

} // namespace fission::features
