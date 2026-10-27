// MCA-DCC Pipeline - the mcaCageWrap deformer node.
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#ifndef MCA_CAGE_WRAP_NODE_H
#define MCA_CAGE_WRAP_NODE_H

#include <map>
#include <string>
#include <vector>

#include <maya/MDataBlock.h>
#include <maya/MItGeometry.h>
#include <maya/MMatrix.h>
#include <maya/MObject.h>
#include <maya/MPxDeformerNode.h>
#include <maya/MStatus.h>
#include <maya/MTypeId.h>

#include "mca_cage_wrap.h"

namespace mca {

/// Deforms a mesh by a cage wrapped around it.
///
/// The maths lives in mca_cage_wrap.h and knows nothing about Maya. This is the part
/// that deals with Maya: which plug the cage comes from, what space everything is in,
/// when to rebind, and how to say what it measured.
class CageWrapNode : public MPxDeformerNode {
public:
    static void* creator();
    static MStatus initialize();
    static MStatus installAttributeEditorTemplate();

    /// Register the deformer's weights with the paint tool. Called after the node type
    /// is registered, never from `initialize`.
    static MStatus makeWeightsPaintable();

    static MTypeId id;
    static MString nodeName;

    MStatus deform(MDataBlock& block, MItGeometry& iterator, const MMatrix& geometryMatrix,
                   unsigned int multiIndex) override;

    // --- attributes --------------------------------------------------------- //

    /// The cage as it was modelled around the mesh. Connect the shape's `outMesh`.
    static MObject aRestCage;
    /// That shape's world matrix, so the cage can be parented and moved as a whole.
    static MObject aRestCageMatrix;

    /// The cage that moves. Usually the same mesh with a deformer or animation on it.
    static MObject aCage;
    /// Its world matrix.
    static MObject aCageMatrix;

    /// How much of the cage's stretch reaches the thickness of what it encloses.
    static MObject aStretch;

    /// Flip to rebind. Rarely needed - a changed rest cage is noticed on its own.
    static MObject aRebind;

    /// 0 lets it choose.
    static MObject aThreads;

    // --- what it measured, for whoever asks --------------------------------- //

    /// Worst distance between a point's rest position and where the bind puts it.
    static MObject aWorstRestError;
    /// Points that were outside the cage, or on it, and bound to their closest face.
    static MObject aPointsOutside;
    /// Weights kept after pruning.
    static MObject aTermCount;

    /// Points that were inside the cage but had to be rebound to their closest face.
    static MObject aPointsRebound;

private:
    /// One bind per geometry this deformer is on.
    struct Bound {
        cage::Bind bind;
        std::vector<cage::Triangle> triangles;  ///< the REST cage's triangulation, reused
        size_t cagePoints = 0;
        size_t meshPoints = 0;
        double restFingerprint = 0.0;
        bool complained = false;
    };

    std::map<unsigned int, Bound> bound_;

    /// Read a cage mesh into the maths layer's own types, in world space.
    ///
    /// :param triangles: when empty, the mesh is triangulated and this is filled;
    ///     when not, it is reused. The rest cage's triangulation is the one that
    ///     counts - reading it again from the deformed cage would let Maya pick a
    ///     different diagonal for a non-planar quad and silently pair the wrong
    ///     triangles together.
    static MStatus readCage(MDataBlock& block, MObject& attribute, MObject& matrixAttribute,
                            std::vector<cage::Triangle>& triangles, cage::Cage& out,
                            std::string* problem);

    /// A cheap number that changes when the rest cage does, so a rebind happens
    /// without anybody having to ask for one.
    static double fingerprintOf(const cage::Cage& cage);
};

}  // namespace mca

#endif  // MCA_CAGE_WRAP_NODE_H
