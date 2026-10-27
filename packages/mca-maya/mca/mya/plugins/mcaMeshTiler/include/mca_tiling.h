// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// The tiling maths, with no Maya in it.
//
// Everything here is a pure function over plain data so it can be unit tested
// without a DCC. The Maya shell converts at the boundary. This is the same split
// mcaPhysicsChain uses, and it is the reason that plug-in's solver could be
// checked 44 ways before it was ever loaded into a viewport.

#ifndef MCA_TILING_H
#define MCA_TILING_H

#include <cstddef>
#include <vector>

namespace mca {

struct Vec3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;

    Vec3() = default;
    Vec3(double x_, double y_, double z_) : x(x_), y(y_), z(z_) {}

    double operator[](int axis) const { return axis == 0 ? x : (axis == 1 ? y : z); }
    double& operator[](int axis) { return axis == 0 ? x : (axis == 1 ? y : z); }
};

/// Which of the tile's own axes points away from the surface it sits on.
///
/// The tool this replaces hard-coded Y, and parameterised the other two as
/// `u = remap(z)`, `v = remap(x)`. That is kept as the default so existing tiles
/// behave identically, but it is now something you can read rather than
/// something you have to infer from the source.
enum class UpAxis { X = 0, Y = 1, Z = 2 };

/// Which axes carry the surface parameters for a given up axis, in the order
/// the original used: the third axis supplies u, the first supplies v.
///
/// Y up gives (u, v) = (z, x), matching the original exactly.
void parameterAxes(UpAxis up, int& uAxis, int& vAxis);

/// A tile, reduced to what tiling actually needs.
struct TileParameterisation {
    /// Per vertex, position across the face in 0..1.
    std::vector<double> u;
    std::vector<double> v;
    /// Per vertex, distance off the face before scaling.
    std::vector<double> height;
    /// The tile's footprint, used to decide how much a face's area should
    /// scale it.
    double baseArea = 0.0;
};

/// Map every tile vertex to a surface parameter and a height.
///
/// The tile is measured by its own bounding box: the two axes across the surface
/// are remapped to 0..1, and the up axis is taken as-is so that a tile modelled
/// one unit tall stays one unit tall at height 1.
///
/// A degenerate axis - a completely flat tile, or one with a single vertex -
/// would divide by zero, so it maps to 0.5 rather than producing NaNs that then
/// spread through every stencil evaluation.
TileParameterisation parameteriseTile(const std::vector<Vec3>& points, UpAxis up);

/// How much to scale a tile sitting on a face of the given area.
///
/// Area goes as the square of scale, so the factor is the square root of the
/// ratio. `blend` fades between no scaling and full, which is what the original
/// exposed as `areaScale`.
///
/// Returns 1.0 for a non-positive base area rather than dividing by it.
double areaScaleFactor(double faceArea, double baseArea, double blend);

/// Rotate a face's vertex order by whole steps.
///
/// This is how a tile gets turned on a particular face: the face's corners are
/// relabelled, so the tile's u and v land on different edges. Negative and
/// out-of-range steps wrap rather than reading off the end, which the original
/// did not guard.
void rotateFaceVertices(std::vector<int>& vertexIds, int steps);

/// A fingerprint of a mesh's topology.
///
/// The point is to notice changes that preserve counts. The tool this replaces
/// compared vertex, edge and face totals, so an edge flip or a face reorder left
/// its cached stencil table evaluating against topology that no longer existed -
/// silently, and only visible as tiles in slightly wrong places.
///
/// FNV-1a over the face sizes and the vertex ids. Cheap enough to run every
/// evaluation, which is the only way a cache key is any use.
std::size_t hashTopology(const std::vector<int>& faceVertexCounts,
                         const std::vector<int>& faceVertexIds);

/// True when every face has exactly four vertices.
///
/// Worth knowing explicitly: a target that is already all quads needs no
/// refinement, and refining it anyway would quadruple the face count for
/// nothing.
bool isAllQuads(const std::vector<int>& faceVertexCounts);

/// How many faces are not quads, for reporting.
int nonQuadCount(const std::vector<int>& faceVertexCounts);

}  // namespace mca

#endif  // MCA_TILING_H
