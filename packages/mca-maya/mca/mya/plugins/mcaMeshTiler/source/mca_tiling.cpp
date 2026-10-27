// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_tiling.h"

#include <algorithm>
#include <cmath>

namespace mca {

void parameterAxes(UpAxis up, int& uAxis, int& vAxis) {
    // Y up gives (u, v) = (z, x), which is what the original hard-coded. The
    // other two follow the same rotation so a tile modelled for one axis reads
    // the same way when re-authored for another.
    switch (up) {
        case UpAxis::X:
            uAxis = 1;  // y
            vAxis = 2;  // z
            break;
        case UpAxis::Z:
            uAxis = 0;  // x
            vAxis = 1;  // y
            break;
        case UpAxis::Y:
        default:
            uAxis = 2;  // z
            vAxis = 0;  // x
            break;
    }
}

namespace {

/// Remap into 0..1, or to the middle when there is nothing to remap.
double normalise(double value, double low, double high) {
    const double span = high - low;
    // A flat tile is a legitimate thing to hand this - a single quad of card,
    // for instance, has no thickness. Dividing by its zero span would put NaNs
    // into the stencil parameters, and a NaN parameter poisons every vertex the
    // limit surface evaluates, not just this one.
    if (span < 1e-12) {
        return 0.5;
    }
    return (value - low) / span;
}

}  // namespace

TileParameterisation parameteriseTile(const std::vector<Vec3>& points, UpAxis up) {
    TileParameterisation out;
    const std::size_t count = points.size();
    out.u.resize(count, 0.5);
    out.v.resize(count, 0.5);
    out.height.resize(count, 0.0);

    if (count == 0u) {
        return out;
    }

    int uAxis = 2;
    int vAxis = 0;
    parameterAxes(up, uAxis, vAxis);
    const int upAxis = static_cast<int>(up);

    Vec3 low = points[0];
    Vec3 high = points[0];
    for (const Vec3& point : points) {
        for (int axis = 0; axis < 3; ++axis) {
            low[axis] = std::min(low[axis], point[axis]);
            high[axis] = std::max(high[axis], point[axis]);
        }
    }

    for (std::size_t index = 0u; index < count; ++index) {
        out.u[index] = normalise(points[index][uAxis], low[uAxis], high[uAxis]);
        out.v[index] = normalise(points[index][vAxis], low[vAxis], high[vAxis]);
        // Height is NOT normalised. A tile modelled one unit tall should stand
        // one unit off the surface at height 1, whatever its footprint.
        out.height[index] = points[index][upAxis];
    }

    out.baseArea = (high[uAxis] - low[uAxis]) * (high[vAxis] - low[vAxis]);
    return out;
}

double areaScaleFactor(double faceArea, double baseArea, double blend) {
    if (baseArea <= 1e-12 || faceArea < 0.0) {
        return 1.0;
    }
    // Area is the square of scale, so the scale that matches an area ratio is
    // its square root.
    const double scale = std::sqrt(faceArea / baseArea);
    const double clamped = std::max(0.0, std::min(1.0, blend));
    return 1.0 + (scale - 1.0) * clamped;
}

void rotateFaceVertices(std::vector<int>& vertexIds, int steps) {
    const int count = static_cast<int>(vertexIds.size());
    if (count <= 1) {
        return;
    }
    // Wrap rather than read off the end. The original indexed with a bare
    // modulo, which is negative in C++ for negative operands - so a negative
    // rotation indexed backwards out of the array.
    int shift = steps % count;
    if (shift < 0) {
        shift += count;
    }
    if (shift == 0) {
        return;
    }
    std::rotate(vertexIds.begin(), vertexIds.begin() + shift, vertexIds.end());
}

std::size_t hashTopology(const std::vector<int>& faceVertexCounts,
                         const std::vector<int>& faceVertexIds) {
    // FNV-1a. Not cryptographic, and does not need to be: the question is only
    // "is this the same topology as last evaluation", and the cost of a false
    // match is a stale stencil table while the cost of a false miss is a rebuild.
    std::size_t hash = 1469598103934665603ull;
    const auto mix = [&hash](std::size_t value) {
        hash ^= value;
        hash *= 1099511628211ull;
    };

    mix(faceVertexCounts.size());
    for (int value : faceVertexCounts) {
        mix(static_cast<std::size_t>(value));
    }
    mix(faceVertexIds.size());
    for (int value : faceVertexIds) {
        mix(static_cast<std::size_t>(value));
    }
    return hash;
}

bool isAllQuads(const std::vector<int>& faceVertexCounts) {
    for (int count : faceVertexCounts) {
        if (count != 4) {
            return false;
        }
    }
    return true;
}

int nonQuadCount(const std::vector<int>& faceVertexCounts) {
    int total = 0;
    for (int count : faceVertexCounts) {
        if (count != 4) {
            ++total;
        }
    }
    return total;
}

}  // namespace mca
