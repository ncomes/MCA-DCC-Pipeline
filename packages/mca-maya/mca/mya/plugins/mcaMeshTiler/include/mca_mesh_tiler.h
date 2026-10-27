// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// mcaMeshTiler: repeat one mesh across the surface of another.
//
// A tile mesh is copied onto every face of a target mesh and conformed to the
// target's OpenSubdiv LIMIT SURFACE rather than to its polygons - so the tiles
// follow the smooth shape a low-poly target implies instead of faceting along
// its cage. Scales, feathers, armour plates, chainmail, brickwork, panelling.
//
// The maths is in mca_tiling.h and has no Maya in it, so it is tested off-DCC.
// This file is the Maya shell: attributes in, OpenSubdiv, mesh out.
//
// How it works, briefly
// ---------------------
// Evaluating "where does every tile vertex sit on the limit surface" is a sparse
// matrix multiply against the target's control points, and OpenSubdiv will build
// that matrix for us as a LimitStencilTable. Building it is expensive and only
// depends on TOPOLOGY, so it is cached and rebuilt when the topology changes -
// which makes moving the target cheap and re-meshing it costly, the right way
// round for a rig.
//
// Two departures from the tool this replaces
// ------------------------------------------
// **Any topology, not only quads.** The original collected faces with exactly
// four vertices and silently dropped everything else, so a triangulated target
// produced an empty mesh and no message. Catmull-Clark makes every face a quad
// at refinement level one, and we are already building the refiner, so triangles
// and n-gons cost nothing to support.
//
// **The tile's orientation is stated, not assumed.** The original parameterised
// the tile by its bounding box in XZ with Y as the height off the surface, and
// nothing anywhere said so. That is still the default, but it is now an
// attribute you can read.

#ifndef MCA_MESH_TILER_H
#define MCA_MESH_TILER_H

#include <maya/MPxNode.h>
#include <maya/MTypeId.h>
#include <maya/MObject.h>
#include <maya/MStatus.h>
#include <maya/MDataBlock.h>
#include <maya/MPlug.h>

#include <memory>
#include <string>
#include <vector>

#include "mca_tiling.h"
#include "mca_subdiv.h"

class McaMeshTiler : public MPxNode {
public:
    static void* creator();
    static MStatus initialize();

    static const MString kNodeName;
    static const MTypeId kNodeId;

    MStatus compute(const MPlug& plug, MDataBlock& data) override;

    // --- meshes ------------------------------------------------------------ //

    /// The mesh that gets repeated.
    static MObject aTileMesh;
    /// The surface it is repeated across.
    static MObject aTargetMesh;
    /// One mesh holding every tile.
    static MObject aOutMesh;

    // --- placement --------------------------------------------------------- //

    /// Which tile axis points away from the surface. Default Y, which is what
    /// the tool this replaces assumed without saying.
    static MObject aTileUpAxis;
    /// Multiplies the tile's height off the surface.
    static MObject aHeight;
    /// Added to the tile's height off the surface.
    static MObject aHeightOffset;
    /// Blend towards scaling each tile by the square root of its face's area,
    /// so tiles on a stretched face grow to match. 0 is off.
    static MObject aAreaScale;
    /// Per face, how many steps to rotate that face's tile. Sparse array.
    static MObject aFaceRotation;
    /// Brings the world-space result into the output's own space. Connect the
    /// output transform's worldInverseMatrix.
    static MObject aWorldToOutput;

    // --- surface ----------------------------------------------------------- //

    /// How the limit surface behaves at open boundaries.
    static MObject aBoundaryInterpolation;
    /// Where tile normals come from: the face, the limit surface, or its
    /// derivatives.
    static MObject aNormalMode;
    /// Use the crease and corner values authored on the target mesh.
    static MObject aUseMeshCreases;
    /// A single sharpness applied to every edge. The original's `crease`, which
    /// was never per-edge despite the name.
    static MObject aCreaseSharpness;
    /// A single sharpness applied to every vertex. The original's `corner`.
    static MObject aCornerSharpness;

    // --- tiles -------------------------------------------------------------- //

    /// How many tiles fit across each face, and down it. 1 x 1 stretches one
    /// tile over the whole face, which is all the tool this replaces could do.
    static MObject aTilesU;
    static MObject aTilesV;
    /// Copy the tile's UV sets onto the output.
    static MObject aCopyUVs;
    /// Refine non-quad faces into quads rather than skipping them.
    static MObject aRefineNonQuads;

private:
    /// Everything derived from the tile mesh. Rebuilt when the tile changes.
    mca::TileParameterisation tile_;
    /// The tile's own topology, repeated once per tile to build the output.
    std::vector<int> tileCounts_;
    std::vector<int> tileVertexIds_;
    int tileVertexCount_ = 0;

    /// One of the tile's UV sets, in the shape MFnMesh wants it back in.
    ///
    /// `counts` is per face - the number of UVs assigned to that face, which is
    /// 0 for a face nobody mapped - and `ids` is the flat run of indices those
    /// counts walk through. That is exactly what getAssignedUVs hands out and
    /// what assignUVs takes, so an unmapped face survives the round trip
    /// instead of being given a bogus corner of the texture.
    struct TileUVSet {
        std::string name;
        std::vector<float> u;
        std::vector<float> v;
        std::vector<int> counts;
        std::vector<int> ids;
    };
    std::vector<TileUVSet> tileUVs_;

    /// Everything derived from the target's topology, including the stencil
    /// table. Rebuilt when that topology changes - see topologyKey_.
    mca::SubdivCache subdiv_;

    /// The output mesh's topology, which only changes when the tile or the
    /// target topology does.
    MObject outMeshData_;
    unsigned int outVertexCount_ = 0u;

    /// A fingerprint of the target's topology.
    ///
    /// The tool this replaces compared vertex, edge and face COUNTS, so any
    /// change that preserved them - an edge flip, a reorder - left the stencil
    /// table silently evaluating against topology that no longer existed.
    std::size_t topologyKey_ = 0u;
    std::size_t tileKey_ = 0u;

    MStatus rebuildTile(MDataBlock& data);
    MStatus rebuildSubdiv(MDataBlock& data, MObject targetMesh);
    MStatus rebuildOutputTopology(bool copyUVs);
    MStatus copyTileUVs(MObject outMesh, int tiles);
};

#endif  // MCA_MESH_TILER_H
