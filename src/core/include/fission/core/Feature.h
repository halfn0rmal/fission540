#pragma once

#include "fission/kernel/Shape.h"

#include <string>

namespace fission::core {

enum class FeatureState {
    NotComputed,
    Ok,
    Error,
};

// One entry in the design timeline. A feature takes the body produced by the
// features before it and returns the new body.
class Feature {
public:
    Feature(std::string id, std::string name);
    virtual ~Feature() = default;

    Feature(const Feature&) = delete;
    Feature& operator=(const Feature&) = delete;

    [[nodiscard]] const std::string& id() const { return m_id; }
    [[nodiscard]] const std::string& name() const { return m_name; }
    void setName(std::string name) { m_name = std::move(name); }

    // Short type label shown in the timeline, e.g. "Box" or "Extrude".
    [[nodiscard]] virtual std::string typeName() const = 0;

    [[nodiscard]] bool isSuppressed() const { return m_suppressed; }
    void setSuppressed(bool suppressed) { m_suppressed = suppressed; }

    [[nodiscard]] FeatureState state() const { return m_state; }
    [[nodiscard]] const std::string& errorMessage() const { return m_error; }

    // Runs the feature, recording state and error. Returns the resulting body,
    // or `input` unchanged if the feature failed.
    kernel::Shape compute(const kernel::Shape& input);

protected:
    // Implementations throw on failure.
    virtual kernel::Shape execute(const kernel::Shape& input) = 0;

private:
    std::string m_id;
    std::string m_name;
    bool m_suppressed = false;
    FeatureState m_state = FeatureState::NotComputed;
    std::string m_error;
};

} // namespace fission::core
