// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_subdiv.h"

#include <algorithm>

#include <cmath>

namespace mca {

namespace {

using Descriptor = OpenSubdiv::Far::TopologyDescriptor;
using Refiner = OpenSubdiv::Far::TopologyRefiner;
using RefinerFactory = OpenSubdiv::Far::TopologyRefinerFactory<Descriptor>;
using SdcOptions = OpenSubdiv::Sdc::Options;
using LimitTable = OpenSubdiv::Far::LimitStencilTable;
using LimitTableFactory = OpenSubdiv::Far::LimitStencilTableFactory;
using LocationArray = LimitTableFactory::LocationArray;
using PtexIndices = OpenSubdiv::Far::PtexIndices;

/// Crease and corner at 10 stop behaving below this, and it is what the tool
/// being replaced used. Kept rather than reduced because tiles authored against
/// its behaviour should still land in the same place.
constexpr int kMaxRefinementLevel = 10;

/// What OpenSubdiv interpolates when asked for positions or normals. The
/// interface is fixed by the library: Clear() then AddWithWeight() per stencil.
struct Triple {
    double value[3] = {0.0, 0.0, 0.0};

    void Clear(void* = nullptr) { value[0] = value[1] = value[2] = 0.0; }

    void AddWithWeight(const Triple& source, double weight) {
        value[0] += weight * source.value[0];
        value[1] += weight * source.value[1];
        value[2] += weight * source.value[2];
    }
};

struct Single {
    double value = 0.0;

    void Clear(void* = nullptr) { value = 0.0; }

    void AddWithWeight(const Single& source, double weight) {
        value += weight * source.value;
    }
};

void toTriples(const std::vector<Vec3>& source, std::vector<Triple>& out) {
    out.resize(source.size());
    for (std::size_t index = 0u; index < source.size(); ++index) {
        out[index].value[0] = source[index].x;
        out[index].value[1] = source[index].y;
        out[index].value[2] = source[index].z;
    }
}

}  // namespace

SubdivCache::SubdivCache() = default;
SubdivCache::~SubdivCache() = default;
SubdivCache::SubdivCache(SubdivCache&&) noexcept = default;
SubdivCache& SubdivCache::operator=(SubdivCache&&) noexcept = default;

std::size_t SubdivCache::sampleCount() const {
    return static_cast<std::size_t>(tileCount_) * static_cast<std::size_t>(verticesPerTile_);
}

void SubdivCache::clear() {
    // Order matters: the stencil table was built from the refiner, so it goes
    // first. unique_ptr does the rest, and there is no second destruction to
    // worry about because nothing else holds these.
    limitTable_.reset();
    refiner_.reset();
    tileCount_ = 0;
    tilesPerFace_ = 1;
    verticesPerTile_ = 0;
    controlVertexCount_ = 0;
    tileSourceFaces_.clear();
}

bool SubdivCache::build(int vertexCount,
                        const std::vector<int>& faceVertexCounts,
                        const std::vector<int>& faceVertexIds,
                        const SharpnessOptions& sharpness,
                        const std::vector<float>& tileS,
                        const std::vector<float>& tileT,
                        int tilesU,
                        int tilesV,
                        std::string& error) {
    clear();

    if (vertexCount <= 0 || faceVertexCounts.empty()) {
        error = "The target mesh has no faces to tile.";
        return false;
    }
    if (tileS.empty() || tileS.size() != tileT.size()) {
        error = "The tile has no vertices to place.";
        return false;
    }

    // These buffers only have to outlive the factory call below - the refiner
    // copies the topology it is handed - so they are locals. That is the whole
    // reason this file has no pointer-holder and no lifetime question.
    std::vector<int> uniformCornerIds;
    std::vector<float> uniformCornerWeights;
    std::vector<int> creasePairs = sharpness.creaseVertexPairs;
    std::vector<float> creaseWeights = sharpness.creaseWeights;
    std::vector<int> cornerIds = sharpness.cornerVertexIds;
    std::vector<float> cornerWeights = sharpness.cornerWeights;

    // The uniform dials are additive: a mesh with its own creasing keeps it and
    // the dial sharpens everything else on top.
    if (sharpness.uniformCorner > 1e-6f) {
        uniformCornerIds.resize(static_cast<std::size_t>(vertexCount));
        uniformCornerWeights.assign(static_cast<std::size_t>(vertexCount),
                                    sharpness.uniformCorner);
        for (int index = 0; index < vertexCount; ++index) {
            uniformCornerIds[static_cast<std::size_t>(index)] = index;
        }
        cornerIds = uniformCornerIds;
        cornerWeights = uniformCornerWeights;
    }

    Descriptor descriptor;
    descriptor.numVertices = vertexCount;
    descriptor.numFaces = static_cast<int>(faceVertexCounts.size());
    descriptor.numVertsPerFace = faceVertexCounts.data();
    descriptor.vertIndicesPerFace = faceVertexIds.data();

    if (!creaseWeights.empty() && creasePairs.size() == creaseWeights.size() * 2u) {
        descriptor.numCreases = static_cast<int>(creaseWeights.size());
        descriptor.creaseVertexIndexPairs = creasePairs.data();
        descriptor.creaseWeights = creaseWeights.data();
    }
    if (!cornerWeights.empty() && cornerIds.size() == cornerWeights.size()) {
        descriptor.numCorners = static_cast<int>(cornerWeights.size());
        descriptor.cornerVertexIndices = cornerIds.data();
        descriptor.cornerWeights = cornerWeights.data();
    }

    SdcOptions refinerOptions;
    refinerOptions.SetVtxBoundaryInterpolation(
        sharpness.boundary == BoundaryMode::EdgeOnly
            ? SdcOptions::VTX_BOUNDARY_EDGE_ONLY
            : SdcOptions::VTX_BOUNDARY_EDGE_AND_CORNER);

    refiner_.reset(RefinerFactory::Create(
        descriptor,
        RefinerFactory::Options(OpenSubdiv::Sdc::SCHEME_CATMARK, refinerOptions)));

    if (!refiner_) {
        // Almost always a topology the descriptor rejects: a vertex id outside
        // the mesh, or a face with fewer than three vertices.
        error = "OpenSubdiv could not build a refiner for this mesh. Check for degenerate "
                "faces or stray vertex indices.";
        clear();
        return false;
    }

    refiner_->RefineAdaptive(Refiner::AdaptiveOptions(kMaxRefinementLevel));

    // One tile per ptex face. A quad has one, a triangle three, an n-gon n -
    // so any topology works without a special case, and a triangulated target
    // stops producing an empty mesh with no explanation.
    const PtexIndices ptexIndices(*refiner_);
    const int ptexFaceCount = ptexIndices.GetNumFaces();
    if (ptexFaceCount <= 0) {
        error = "The target mesh produced no surface to tile.";
        clear();
        return false;
    }

    const int cellsU = std::max(1, tilesU);
    const int cellsV = std::max(1, tilesV);
    tilesPerFace_ = cellsU * cellsV;

    verticesPerTile_ = static_cast<int>(tileS.size());
    tileCount_ = ptexFaceCount * tilesPerFace_;
    controlVertexCount_ = vertexCount;

    // Remember which face each tile came from, so callers can report "3
    // triangles became 9 tiles" rather than leaving the count unexplained.
    // Every cell of a face reports that face.
    tileSourceFaces_.resize(static_cast<std::size_t>(tileCount_), 0);
    for (int face = 0; face < descriptor.numFaces; ++face) {
        const int first = ptexIndices.GetFaceId(face);
        const int sides = faceVertexCounts[static_cast<std::size_t>(face)];
        const int produced = (sides == 4) ? 1 : sides;
        for (int offset = 0; offset < produced; ++offset) {
            const int ptexFace = first + offset;
            if (ptexFace < 0 || ptexFace >= ptexFaceCount) {
                continue;
            }
            for (int cell = 0; cell < tilesPerFace_; ++cell) {
                tileSourceFaces_[static_cast<std::size_t>(ptexFace * tilesPerFace_ + cell)] =
                    face;
            }
        }
    }

    // The tile's own (u, v) squeezed into each cell of the grid. A ptex face is
    // a unit square whatever the polygon it came from, so this is the same
    // arithmetic for quads, triangles and n-gons.
    //
    // These arrays have to outlive the factory call below, because LocationArray
    // holds bare pointers into them - which is why they are named locals here
    // and not built inside the loop.
    std::vector<std::vector<float>> cellS(static_cast<std::size_t>(tilesPerFace_));
    std::vector<std::vector<float>> cellT(static_cast<std::size_t>(tilesPerFace_));
    for (int down = 0; down < cellsV; ++down) {
        for (int across = 0; across < cellsU; ++across) {
            const std::size_t cell = static_cast<std::size_t>(down * cellsU + across);
            cellS[cell].resize(tileS.size());
            cellT[cell].resize(tileT.size());
            for (std::size_t index = 0u; index < tileS.size(); ++index) {
                cellS[cell][index] =
                    (static_cast<float>(across) + tileS[index]) / static_cast<float>(cellsU);
                cellT[cell][index] =
                    (static_cast<float>(down) + tileT[index]) / static_cast<float>(cellsV);
            }
        }
    }

    std::vector<LocationArray> locations(static_cast<std::size_t>(tileCount_));
    for (int face = 0; face < ptexFaceCount; ++face) {
        for (int cell = 0; cell < tilesPerFace_; ++cell) {
            LocationArray& location =
                locations[static_cast<std::size_t>(face * tilesPerFace_ + cell)];
            location.ptexIdx = face;
            location.numLocations = verticesPerTile_;
            location.s = cellS[static_cast<std::size_t>(cell)].data();
            location.t = cellT[static_cast<std::size_t>(cell)].data();
        }
    }

    limitTable_.reset(LimitTableFactory::Create(*refiner_, locations));
    if (!limitTable_) {
        error = "OpenSubdiv could not build a limit stencil table for this mesh.";
        clear();
        return false;
    }

    return true;
}

bool SubdivCache::evaluatePoints(const std::vector<Vec3>& controlPoints,
                                 std::vector<Vec3>& out) const {
    return evaluateVectors(controlPoints, out);
}

bool SubdivCache::evaluateVectors(const std::vector<Vec3>& controlVectors,
                                  std::vector<Vec3>& out) const {
    if (!valid() || static_cast<int>(controlVectors.size()) != controlVertexCount_) {
        return false;
    }
    std::vector<Triple> control;
    toTriples(controlVectors, control);

    std::vector<Triple> samples(sampleCount());
    limitTable_->UpdateValues(control.data(), samples.data());

    out.resize(samples.size());
    for (std::size_t index = 0u; index < samples.size(); ++index) {
        out[index] = Vec3(samples[index].value[0], samples[index].value[1],
                          samples[index].value[2]);
    }
    return true;
}

bool SubdivCache::evaluateScalars(const std::vector<double>& controlValues,
                                  std::vector<double>& out) const {
    if (!valid() || static_cast<int>(controlValues.size()) != controlVertexCount_) {
        return false;
    }
    std::vector<Single> control(controlValues.size());
    for (std::size_t index = 0u; index < controlValues.size(); ++index) {
        control[index].value = controlValues[index];
    }

    std::vector<Single> samples(sampleCount());
    limitTable_->UpdateValues(control.data(), samples.data());

    out.resize(samples.size());
    for (std::size_t index = 0u; index < samples.size(); ++index) {
        out[index] = samples[index].value;
    }
    return true;
}

bool SubdivCache::evaluateNormals(const std::vector<Vec3>& controlPoints,
                                  std::vector<Vec3>& out) const {
    if (!valid() || static_cast<int>(controlPoints.size()) != controlVertexCount_) {
        return false;
    }
    std::vector<Triple> control;
    toTriples(controlPoints, control);

    const std::size_t count = sampleCount();
    std::vector<Triple> alongU(count);
    std::vector<Triple> alongV(count);
    limitTable_->UpdateDerivs(control.data(), alongU.data(), alongV.data());

    out.resize(count);
    for (std::size_t index = 0u; index < count; ++index) {
        const Triple& u = alongU[index];
        const Triple& v = alongV[index];
        Vec3 normal(u.value[1] * v.value[2] - u.value[2] * v.value[1],
                    u.value[2] * v.value[0] - u.value[0] * v.value[2],
                    u.value[0] * v.value[1] - u.value[1] * v.value[0]);

        const double length =
            std::sqrt(normal.x * normal.x + normal.y * normal.y + normal.z * normal.z);
        // A degenerate patch - two coincident corners, a collapsed face -
        // produces parallel derivatives and no normal. Zero is the honest
        // answer; dividing would spread NaNs into every tile vertex.
        if (length > 1e-12) {
            normal.x /= length;
            normal.y /= length;
            normal.z /= length;
        } else {
            normal = Vec3();
        }
        out[index] = normal;
    }
    return true;
}

}  // namespace mca
