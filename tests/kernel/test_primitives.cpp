#include "fission/kernel/Booleans.h"
#include "fission/kernel/Error.h"
#include "fission/kernel/Primitives.h"
#include "fission/kernel/Properties.h"

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

using namespace fission::kernel;
using Catch::Matchers::WithinRel;

TEST_CASE("Box has expected volume, area and faces", "[kernel]") {
    const Shape box = makeBox(10.0, 20.0, 30.0);
    REQUIRE_FALSE(box.isNull());
    CHECK_THAT(volume(box), WithinRel(6000.0, 1e-9));
    CHECK_THAT(surfaceArea(box), WithinRel(2.0 * (200.0 + 300.0 + 600.0), 1e-9));
    CHECK(faceCount(box) == 6);
}

TEST_CASE("Box rejects non-positive dimensions", "[kernel]") {
    CHECK_THROWS_AS(makeBox(0.0, 1.0, 1.0), KernelError);
    CHECK_THROWS_AS(makeBox(1.0, -1.0, 1.0), KernelError);
}

TEST_CASE("Boolean operations on overlapping boxes", "[kernel]") {
    // Two 10 mm cubes overlapping by 5 mm in X: overlap volume 500.
    const Shape a = makeBox(10.0, 10.0, 10.0);
    const Shape b = makeBox(10.0, 10.0, 10.0, {5.0, 0.0, 0.0});

    CHECK_THAT(volume(fuse(a, b)), WithinRel(1500.0, 1e-9));
    CHECK_THAT(volume(cut(a, b)), WithinRel(500.0, 1e-9));
    CHECK_THAT(volume(common(a, b)), WithinRel(500.0, 1e-9));
}

TEST_CASE("Null shape properties are zero", "[kernel]") {
    const Shape empty;
    CHECK(empty.isNull());
    CHECK(volume(empty) == 0.0);
    CHECK(faceCount(empty) == 0);
    CHECK_THROWS_AS(fuse(empty, makeBox(1.0, 1.0, 1.0)), KernelError);
}
