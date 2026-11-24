#include "fission/core/Document.h"
#include "fission/features/BoxFeature.h"
#include "fission/kernel/Properties.h"

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

#include <memory>

using namespace fission;
using Catch::Matchers::WithinRel;
using features::BodyOperation;
using features::BoxFeature;

namespace {

BoxFeature& addBox(core::Document& doc, double size, kernel::Point3 origin,
                   BodyOperation op = BodyOperation::Join) {
    BoxFeature::Params params;
    params.dx = params.dy = params.dz = size;
    params.origin = origin;
    params.operation = op;
    auto& feature = doc.timeline().insert(
        std::make_unique<BoxFeature>(doc.nextFeatureId(), "Box", params));
    return static_cast<BoxFeature&>(feature);
}

} // namespace

TEST_CASE("Timeline computes features in order", "[core]") {
    core::Document doc;
    addBox(doc, 10.0, {});
    addBox(doc, 10.0, {5.0, 0.0, 0.0}, BodyOperation::Cut);
    doc.recompute();

    CHECK_THAT(kernel::volume(doc.body()), WithinRel(500.0, 1e-9));
    CHECK(doc.timeline().at(0).state() == core::FeatureState::Ok);
    CHECK(doc.timeline().at(1).state() == core::FeatureState::Ok);
}

TEST_CASE("Rollback marker excludes later features", "[core]") {
    core::Document doc;
    addBox(doc, 10.0, {});
    addBox(doc, 10.0, {5.0, 0.0, 0.0}, BodyOperation::Cut);

    doc.timeline().setMarker(1);
    doc.recompute();
    CHECK_THAT(kernel::volume(doc.body()), WithinRel(1000.0, 1e-9));

    // A feature added while rolled back goes in at the marker.
    addBox(doc, 10.0, {0.0, 0.0, 10.0});
    CHECK(doc.timeline().marker() == 2);
    doc.timeline().setMarker(doc.timeline().size());
    doc.recompute();
    // (cube + stacked cube) minus half of the bottom cube.
    CHECK_THAT(kernel::volume(doc.body()), WithinRel(1500.0, 1e-9));
}

TEST_CASE("Suppressed features are skipped", "[core]") {
    core::Document doc;
    addBox(doc, 10.0, {});
    addBox(doc, 10.0, {5.0, 0.0, 0.0}, BodyOperation::Cut).setSuppressed(true);
    doc.recompute();
    CHECK_THAT(kernel::volume(doc.body()), WithinRel(1000.0, 1e-9));
}

TEST_CASE("Failing feature is marked and leaves the body unchanged", "[core]") {
    core::Document doc;
    addBox(doc, 10.0, {}, BodyOperation::Cut); // nothing to cut yet
    doc.recompute();
    CHECK(doc.timeline().at(0).state() == core::FeatureState::Error);
    CHECK_FALSE(doc.timeline().at(0).errorMessage().empty());
    CHECK(doc.body().isNull());
}

TEST_CASE("Timeline move and remove keep the marker consistent", "[core]") {
    core::Document doc;
    addBox(doc, 10.0, {});
    addBox(doc, 10.0, {20.0, 0.0, 0.0});
    addBox(doc, 10.0, {40.0, 0.0, 0.0});
    REQUIRE(doc.timeline().marker() == 3);

    doc.timeline().remove(0);
    CHECK(doc.timeline().size() == 2);
    CHECK(doc.timeline().marker() == 2);

    doc.timeline().move(1, 0);
    doc.recompute();
    CHECK_THAT(kernel::volume(doc.body()), WithinRel(2000.0, 1e-9));
}
