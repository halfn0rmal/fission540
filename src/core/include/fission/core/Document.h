#pragma once

#include "fission/core/Timeline.h"
#include "fission/kernel/Shape.h"

#include <string>

namespace fission::core {

class Document {
public:
    [[nodiscard]] Timeline& timeline() { return m_timeline; }
    [[nodiscard]] const Timeline& timeline() const { return m_timeline; }

    [[nodiscard]] const kernel::Shape& body() const { return m_body; }

    void recompute();

    // Unique feature id within this document, e.g. "f3".
    [[nodiscard]] std::string nextFeatureId();

private:
    Timeline m_timeline;
    kernel::Shape m_body;
    int m_nextId = 1;
};

} // namespace fission::core
