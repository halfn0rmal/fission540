#include "fission/core/Document.h"

namespace fission::core {

void Document::recompute() { m_body = m_timeline.recompute(); }

std::string Document::nextFeatureId() { return "f" + std::to_string(m_nextId++); }

} // namespace fission::core
