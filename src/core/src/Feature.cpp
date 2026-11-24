#include "fission/core/Feature.h"

#include <exception>

namespace fission::core {

Feature::Feature(std::string id, std::string name) : m_id(std::move(id)), m_name(std::move(name)) {}

kernel::Shape Feature::compute(const kernel::Shape& input) {
    try {
        kernel::Shape result = execute(input);
        m_state = FeatureState::Ok;
        m_error.clear();
        return result;
    } catch (const std::exception& e) {
        m_state = FeatureState::Error;
        m_error = e.what();
        return input;
    }
}

} // namespace fission::core
