// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// mcaRBFSolver: interpolate an N-dimensional key to an M-dimensional value.
//
// A driven key with more than one dimension on each side. A regular driven key
// maps one float to one float; this maps a whole vector to a whole vector and
// blends smoothly between the poses you gave it. Drive a shoulder's blendshapes
// from the arm's aim vector, a colour from a position, a set of corrective
// weights from several joints at once.
//
// The maths is in mca_rbf.h and has no Maya in it, so it is tested off-DCC.
// This file is the Maya shell: attributes in, solve, values out.
//
// On attribute names
// ------------------
// The long names are the ones the tool this replaces used - nInput, poses,
// nKey, mValue, mOutput, rbfMode, blendShapeMode - so a scene saved against the
// old node reconnects to this one without rewiring. They are not the names we
// would choose; `blendShapeMode` in particular says what it was for rather than
// what it does, which is to make the outputs sum to one. The Attribute Editor
// template shows better labels.
//
// Two departures worth knowing about
// ----------------------------------
// **NDimension and MDimension are read, not trusted.** The original made you
// type the dimensions in and believed you. Here the real dimensions come from
// the data - the number of nInput elements, and the length of each pose's key
// and value - and the typed values are only used to say so when they disagree.
//
// **distanceMode 0 now means Euclidean.** In the original it was labelled
// Euclidean and was not: it summed |d| to the power of the dimension count and
// took that root, which is the p-norm with p set to N. That is correct for 1D
// and 2D keys and wrong for everything above, including the 3D aim vector its
// own documentation used as the example. The old behaviour is still available,
// as its own mode named for what it actually is.

#ifndef MCA_RBF_SOLVER_H
#define MCA_RBF_SOLVER_H

#include <maya/MPxNode.h>
#include <maya/MTypeId.h>
#include <maya/MObject.h>
#include <maya/MStatus.h>
#include <maya/MDataBlock.h>
#include <maya/MPlug.h>

#include <cstddef>
#include <string>
#include <vector>

#include "mca_rbf.h"

class McaRBFSolver : public MPxNode {
public:
    static void* creator();
    static MStatus initialize();

    static const MString kNodeName;
    static const MTypeId kNodeId;

    MStatus compute(const MPlug& plug, MDataBlock& data) override;

    // --- the system ---------------------------------------------------------- //

    /// The key being interpolated at. N-dimensional.
    static MObject aInput;
    /// The poses. Each carries a key and the value that key should produce.
    static MObject aPoses;
    static MObject aPoseState;
    static MObject aPoseKey;
    static MObject aPoseValue;
    /// The interpolated value. M-dimensional.
    static MObject aOutput;

    // --- how it interpolates --------------------------------------------------- //

    static MObject aDistanceMode;
    static MObject aKernel;
    static MObject aScale;
    static MObject aNormalise;
    /// Added to the matrix diagonal. Zero passes exactly through every pose; a
    /// small value trades that for stability, and is what makes two poses at the
    /// same key solvable instead of a division by a pivot near zero.
    static MObject aRegularisation;
    /// Shift and scale the outputs so they are non-negative and sum to one.
    /// Named `blendShapeMode` because that is what the original called it.
    static MObject aWeightsSumToOne;

    // --- read, not trusted ------------------------------------------------------ //

    /// The original's NDimension and MDimension. Kept so old scenes load; the
    /// real dimensions are taken from the data.
    static MObject aStatedKeyDimension;
    static MObject aStatedValueDimension;

private:
    /// The factorised system. Rebuilt when anything it was built from changes.
    mca::RbfSolver solver_;
    /// A fingerprint of the poses and settings the solver was built from.
    std::size_t systemKey_ = 0u;
    /// Set when the last rebuild failed, so the failure is reported once rather
    /// than on every frame of playback.
    bool reported_ = false;

    MStatus rebuild(MDataBlock& data);
};

#endif  // MCA_RBF_SOLVER_H
