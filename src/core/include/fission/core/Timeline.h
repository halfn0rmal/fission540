#pragma once

#include "fission/core/Feature.h"
#include "fission/kernel/Shape.h"

#include <cstddef>
#include <memory>
#include <vector>

namespace fission::core {

// Ordered feature history with a rollback marker. Features at index >= marker
// exist but are not computed (rolling back the timeline).
class Timeline {
public:
    // Inserts at the marker position and advances the marker past the new feature.
    Feature& insert(std::unique_ptr<Feature> feature);
    void remove(std::size_t index);
    void move(std::size_t from, std::size_t to);

    [[nodiscard]] std::size_t size() const { return m_features.size(); }
    [[nodiscard]] Feature& at(std::size_t index) { return *m_features.at(index); }
    [[nodiscard]] const Feature& at(std::size_t index) const { return *m_features.at(index); }

    [[nodiscard]] std::size_t marker() const { return m_marker; }
    void setMarker(std::size_t marker);

    // Recomputes all active features before the marker and returns the final body.
    kernel::Shape recompute();

private:
    std::vector<std::unique_ptr<Feature>> m_features;
    std::size_t m_marker = 0;
};

} // namespace fission::core
