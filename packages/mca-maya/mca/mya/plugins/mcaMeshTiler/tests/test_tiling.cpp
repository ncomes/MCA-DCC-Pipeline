// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// Off-DCC tests for the tiling maths. No Maya, no licence, no viewport.
//
// Build and run with tests/run_tests.bat, or by hand:
//     cl /EHsc /std:c++17 /I..\include test_tiling.cpp ..\source\mca_tiling.cpp

#include "mca_tiling.h"

#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

namespace {

int gChecks = 0;
int gFailures = 0;

void check(const std::string& label, bool condition, const std::string& detail = "") {
    ++gChecks;
    if (!condition) {
        ++gFailures;
        std::printf("FAIL  %s%s%s\n", label.c_str(), detail.empty() ? "" : "  |  ",
                    detail.c_str());
    }
}

void checkClose(const std::string& label, double got, double want, double tolerance = 1e-9) {
    const bool ok = std::fabs(got - want) <= tolerance;
    check(label, ok, ok ? "" : ("got " + std::to_string(got) + ", want " + std::to_string(want)));
}

/// A unit tile lying flat in XZ, one unit tall in Y - the shape the original
/// assumed without documenting.
std::vector<mca::Vec3> flatTile() {
    return {
        mca::Vec3(0.0, 0.0, 0.0),
        mca::Vec3(2.0, 0.0, 0.0),
        mca::Vec3(2.0, 0.0, 4.0),
        mca::Vec3(0.0, 0.0, 4.0),
        mca::Vec3(1.0, 1.0, 2.0),  // a peak, one unit up
    };
}

void testParameterisation() {
    const auto points = flatTile();
    const auto tile = mca::parameteriseTile(points, mca::UpAxis::Y);

    check("every vertex gets a parameter", tile.u.size() == points.size() &&
                                               tile.v.size() == points.size() &&
                                               tile.height.size() == points.size());

    // Y up means u comes from z and v comes from x.
    checkClose("u is 0 at the minimum z", tile.u[0], 0.0);
    checkClose("u is 1 at the maximum z", tile.u[2], 1.0);
    checkClose("v is 0 at the minimum x", tile.v[0], 0.0);
    checkClose("v is 1 at the maximum x", tile.v[1], 1.0);
    checkClose("the peak sits halfway in v", tile.v[4], 0.5);

    // Height is deliberately NOT normalised: a tile modelled one unit tall
    // stands one unit off the surface at height 1.
    checkClose("height is taken as modelled", tile.height[4], 1.0);
    checkClose("a vertex on the surface has no height", tile.height[0], 0.0);

    checkClose("base area is the footprint", tile.baseArea, 8.0);  // 4 in z by 2 in x

    for (std::size_t i = 0; i < points.size(); ++i) {
        check("u stays inside 0..1", tile.u[i] >= 0.0 && tile.u[i] <= 1.0);
        check("v stays inside 0..1", tile.v[i] >= 0.0 && tile.v[i] <= 1.0);
    }
}

void testOtherUpAxes() {
    int uAxis = -1;
    int vAxis = -1;
    mca::parameterAxes(mca::UpAxis::Y, uAxis, vAxis);
    check("Y up reads u from z and v from x", uAxis == 2 && vAxis == 0);
    mca::parameterAxes(mca::UpAxis::X, uAxis, vAxis);
    check("X up uses the other two axes", uAxis != 0 && vAxis != 0 && uAxis != vAxis);
    mca::parameterAxes(mca::UpAxis::Z, uAxis, vAxis);
    check("Z up uses the other two axes", uAxis != 2 && vAxis != 2 && uAxis != vAxis);

    // The same tile stood on its side should parameterise the same way.
    std::vector<mca::Vec3> standing = {
        mca::Vec3(0.0, 0.0, 0.0),
        mca::Vec3(0.0, 2.0, 0.0),
        mca::Vec3(0.0, 2.0, 4.0),
        mca::Vec3(0.0, 0.0, 4.0),
        mca::Vec3(1.0, 1.0, 2.0),
    };
    const auto tile = mca::parameteriseTile(standing, mca::UpAxis::X);
    checkClose("height comes off the chosen up axis", tile.height[4], 1.0);
    checkClose("base area is still the footprint", tile.baseArea, 8.0);
}

void testDegenerateTile() {
    // A completely flat tile has no extent on one axis. Dividing by that span
    // would put NaNs into the stencil parameters, and one NaN parameter poisons
    // the whole limit-surface evaluation rather than just its own vertex.
    std::vector<mca::Vec3> flat = {
        mca::Vec3(0.0, 0.0, 0.0),
        mca::Vec3(0.0, 0.0, 1.0),
    };
    const auto tile = mca::parameteriseTile(flat, mca::UpAxis::Y);
    for (double value : tile.v) {
        check("a zero-extent axis maps to the middle, not NaN",
              !std::isnan(value) && std::fabs(value - 0.5) < 1e-12);
    }

    const auto empty = mca::parameteriseTile({}, mca::UpAxis::Y);
    check("an empty tile is handled", empty.u.empty() && empty.height.empty());
}

void testAreaScale() {
    checkClose("a face the size of the tile does not scale it",
               mca::areaScaleFactor(8.0, 8.0, 1.0), 1.0);
    // Area is the square of scale, so four times the area is twice the size.
    checkClose("four times the area doubles the tile",
               mca::areaScaleFactor(32.0, 8.0, 1.0), 2.0);
    checkClose("blend 0 disables it entirely",
               mca::areaScaleFactor(32.0, 8.0, 0.0), 1.0);
    checkClose("blend 0.5 goes halfway",
               mca::areaScaleFactor(32.0, 8.0, 0.5), 1.5);
    checkClose("a degenerate tile does not divide by zero",
               mca::areaScaleFactor(32.0, 0.0, 1.0), 1.0);
    checkClose("blend above 1 is clamped",
               mca::areaScaleFactor(32.0, 8.0, 5.0), 2.0);
}

void testFaceRotation() {
    const std::vector<int> original = {10, 11, 12, 13};

    std::vector<int> once = original;
    mca::rotateFaceVertices(once, 1);
    check("one step moves every corner along", once == std::vector<int>({11, 12, 13, 10}));

    std::vector<int> back = original;
    mca::rotateFaceVertices(back, -1);
    // The original used a bare modulo, which is negative in C++ for negative
    // operands - so a negative rotation indexed backwards out of the array.
    check("a negative step wraps rather than reading off the end",
          back == std::vector<int>({13, 10, 11, 12}));

    std::vector<int> full = original;
    mca::rotateFaceVertices(full, 4);
    check("a full turn is the identity", full == original);

    std::vector<int> over = original;
    mca::rotateFaceVertices(over, 5);
    check("more than a full turn wraps", over == std::vector<int>({11, 12, 13, 10}));

    std::vector<int> single = {7};
    mca::rotateFaceVertices(single, 3);
    check("a one-vertex face is left alone", single == std::vector<int>({7}));

    std::vector<int> none;
    mca::rotateFaceVertices(none, 2);
    check("an empty face is left alone", none.empty());

    std::vector<int> triangle = {1, 2, 3};
    mca::rotateFaceVertices(triangle, 1);
    check("rotation is not quad-specific", triangle == std::vector<int>({2, 3, 1}));
}

void testTopologyHash() {
    const std::vector<int> counts = {4, 4};
    const std::vector<int> ids = {0, 1, 2, 3, 3, 2, 4, 5};

    check("the same topology hashes the same",
          mca::hashTopology(counts, ids) == mca::hashTopology(counts, ids));

    // The whole reason this exists: the tool being replaced compared vertex,
    // edge and face COUNTS, so a change that preserved them left its cached
    // stencil table evaluating against topology that no longer existed.
    std::vector<int> flipped = ids;
    std::swap(flipped[1], flipped[3]);
    check("an edge flip changes the hash even though the counts match",
          mca::hashTopology(counts, ids) != mca::hashTopology(counts, flipped));

    std::vector<int> reordered = {3, 2, 4, 5, 0, 1, 2, 3};
    check("reordering faces changes the hash",
          mca::hashTopology(counts, ids) != mca::hashTopology(counts, reordered));

    const std::vector<int> triCounts = {3, 5};
    check("different face sizes change the hash",
          mca::hashTopology(counts, ids) != mca::hashTopology(triCounts, ids));

    check("an empty mesh has a stable hash",
          mca::hashTopology({}, {}) == mca::hashTopology({}, {}));
}

void testQuadDetection() {
    check("all quads is recognised", mca::isAllQuads({4, 4, 4}));
    check("a triangle is not a quad", !mca::isAllQuads({4, 3, 4}));
    check("an n-gon is not a quad", !mca::isAllQuads({4, 6}));
    check("an empty mesh is trivially all quads", mca::isAllQuads({}));

    check("non-quads are counted", mca::nonQuadCount({4, 3, 4, 6, 4}) == 2);
    check("an all-quad mesh counts zero", mca::nonQuadCount({4, 4}) == 0);
}

}  // namespace

int main() {
    testParameterisation();
    testOtherUpAxes();
    testDegenerateTile();
    testAreaScale();
    testFaceRotation();
    testTopologyHash();
    testQuadDetection();

    std::printf("\n%d/%d checks passed.\n", gChecks - gFailures, gChecks);
    return gFailures == 0 ? 0 : 1;
}
