#include "fission/core/Timeline.h"

#include <algorithm>
#include <stdexcept>

namespace fission::core {

namespace {
std::ptrdiff_t offset(std::size_t index) { return static_cast<std::ptrdiff_t>(index); }
} // namespace

Feature& Timeline::insert(std::unique_ptr<Feature> feature) {
    if (!feature) {
        throw std::invalid_argument("Timeline::insert: null feature");
    }
    auto it = m_features.insert(m_features.begin() + offset(m_marker), std::move(feature));
    ++m_marker;
    return **it;
}

void Timeline::remove(std::size_t index) {
    if (index >= m_features.size()) {
        throw std::out_of_range("Timeline::remove");
    }
    m_features.erase(m_features.begin() + offset(index));
    if (m_marker > index) {
        --m_marker;
    }
}

void Timeline::move(std::size_t from, std::size_t to) {
    if (from >= m_features.size() || to >= m_features.size()) {
        throw std::out_of_range("Timeline::move");
    }
    auto feature = std::move(m_features[from]);
    m_features.erase(m_features.begin() + offset(from));
    m_features.insert(m_features.begin() + offset(to), std::move(feature));
}

void Timeline::setMarker(std::size_t marker) { m_marker = std::min(marker, m_features.size()); }

kernel::Shape Timeline::recompute() {
    kernel::Shape body;
    for (std::size_t i = 0; i < m_marker; ++i) {
        Feature& feature = *m_features[i];
        if (!feature.isSuppressed()) {
            body = feature.compute(body);
        }
    }
    return body;
}

} // namespace fission::core
