// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// The OpenSubdiv side of the tiler: build a limit-surface evaluator for a mesh,
// then push control points through it.
//
// Ownership
// ---------
// Everything here is owned by a vector or a unique_ptr, which is the whole
// point. The tool this replaces hand-rolled a `PointerHolder` that deleted every
// buffer it held without clearing its own vector, and was then destroyed - so
// each buffer was deleted twice. Every one of them was allocated with `new[]`
// and freed with plain `delete`, which is undefined behaviour on top. Faced with
// a crash, its author commented out the deletes of the refiner and the stencil
// table entirely:
//
//     //delete refiner_ptr ; // CRASH ?
//
// leaking both on every topology change. The crash was never in those two.
//
// The descriptor's buffers only need to outlive the factory call that reads
// them - the refiner copies the topology it is given - so they are locals here
// rather than members, and the question of freeing them does not arise.
//
// Tiles and ptex faces
// --------------------
// A tile is placed per PTEX FACE rather than per quad. Catmull-Clark turns an
// n-sided face into n quads, and ptex indexes exactly those, so a quad yields
// one tile, a triangle three, an n-gon n - with no special case anywhere. This
// is what makes the tiler work on any topology; the original collected faces
// with exactly four vertices and silently dropped the rest.
//
// Filling a face with several tiles
// ---------------------------------
// One tile per face means the tile is STRETCHED to whatever size that face is,
// which is all the original could do: a big face got a big tile and the only
// way to change that was to re-mesh the target.
//
// `tilesU` and `tilesV` cut each ptex face into a grid of cells and put a tile
// in each one. It costs nothing structurally - a cell is just the tile's own
// (u, v) squeezed into a sub-rectangle before it goes to the stencil factory -
// and it is easier here than it would have been in the original, because every
// ptex face is already a unit square whatever the face it came from. Triangles
// and n-gons fill the same way quads do.
//
// The counts are FIXED rather than derived from face area on purpose. Sizing
// tiles in world units would make the tile count depend on the target's
// geometry, so a deforming rig would change the output mesh's topology
// mid-animation - which breaks caching, Alembic export and shader assignment.

#ifndef MCA_SUBDIV_H
#define MCA_SUBDIV_H

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

#include "mca_tiling.h"

// OpenSubdiv leans on the alternative operator spellings, which MSVC does not
// define without this.
#include <iso646.h>
#include <opensubdiv/far/topologyDescriptor.h>
#include <opensubdiv/far/topologyRefiner.h>
#include <opensubdiv/far/stencilTableFactory.h>
#include <opensubdiv/far/ptexIndices.h>

namespace mca {

/// How the limit surface behaves where the mesh has an open boundary.
enum class BoundaryMode { EdgeOnly = 0, EdgeAndCorner = 1 };

/// Sharpness to apply when building the refiner.
///
/// The two uniform values are the original's `crease` and `corner`, which were
/// applied to every edge and every vertex despite their names. They are kept for
/// compatibility, but the per-element arrays are what a mesh's own creasing
/// feeds into, and those are what most people actually want.
struct SharpnessOptions {
    BoundaryMode boundary = BoundaryMode::EdgeAndCorner;

    float uniformCrease = 0.0f;
    float uniformCorner = 0.0f;

    /// Pairs of vertex ids, two per creased edge.
    std::vector<int> creaseVertexPairs;
    /// One weight per creased edge.
    std::vector<float> creaseWeights;

    std::vector<int> cornerVertexIds;
    std::vector<float> cornerWeights;
};

/// A built limit-surface evaluator for one mesh topology.
///
/// Building is expensive and depends only on topology; evaluating is a sparse
/// matrix multiply and depends only on control point values. That split is why
/// moving a rig is cheap and re-meshing it is not, which is the right way round.
class SubdivCache {
public:
    SubdivCache();
    ~SubdivCache();

    SubdivCache(const SubdivCache&) = delete;
    SubdivCache& operator=(const SubdivCache&) = delete;
    SubdivCache(SubdivCache&&) noexcept;
    SubdivCache& operator=(SubdivCache&&) noexcept;

    /// Build the refiner and the limit stencil table.
    ///
    /// `tileS` and `tileT` are the tile's surface parameters, one pair per tile
    /// vertex; they are evaluated at every cell of every ptex face.
    ///
    /// :param tilesU: Cells across each face. 1 stretches one tile over it.
    /// :param tilesV: Cells down each face.
    /// :return: false with `error` filled in, rather than throwing - this is
    ///     called from a Maya compute, where an exception is not useful.
    bool build(int vertexCount,
               const std::vector<int>& faceVertexCounts,
               const std::vector<int>& faceVertexIds,
               const SharpnessOptions& sharpness,
               const std::vector<float>& tileS,
               const std::vector<float>& tileT,
               int tilesU,
               int tilesV,
               std::string& error);

    void clear();

    bool valid() const { return limitTable_ != nullptr; }

    /// Number of tiles placed: ptex faces times tilesU times tilesV.
    int tileCount() const { return tileCount_; }
    /// Tiles per ptex face, i.e. tilesU * tilesV.
    int tilesPerFace() const { return tilesPerFace_; }
    int verticesPerTile() const { return verticesPerTile_; }
    /// tileCount() * verticesPerTile()
    std::size_t sampleCount() const;

    /// Which original mesh face each tile came from. Same length as tileCount().
    const std::vector<int>& tileSourceFaces() const { return tileSourceFaces_; }

    /// Limit-surface positions for every tile vertex.
    bool evaluatePoints(const std::vector<Vec3>& controlPoints, std::vector<Vec3>& out) const;

    /// Any per-vertex vector pushed through the same stencils - used for
    /// normals in Phong mode.
    bool evaluateVectors(const std::vector<Vec3>& controlVectors,
                         std::vector<Vec3>& out) const;

    /// Any per-vertex scalar, used for area scaling.
    bool evaluateScalars(const std::vector<double>& controlValues,
                         std::vector<double>& out) const;

    /// Surface normals from the limit surface's own derivatives, which is more
    /// faithful than interpolating vertex normals but costs two more
    /// evaluations.
    bool evaluateNormals(const std::vector<Vec3>& controlPoints,
                         std::vector<Vec3>& out) const;

private:
    std::unique_ptr<OpenSubdiv::Far::TopologyRefiner> refiner_;
    std::unique_ptr<const OpenSubdiv::Far::LimitStencilTable> limitTable_;

    int tileCount_ = 0;
    int tilesPerFace_ = 1;
    int verticesPerTile_ = 0;
    int controlVertexCount_ = 0;
    std::vector<int> tileSourceFaces_;
};

}  // namespace mca

#endif  // MCA_SUBDIV_H
