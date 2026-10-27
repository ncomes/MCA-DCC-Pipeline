// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// mcaPoseSkinner: solve joint weights from a mesh that deforms.
//
// You have a face driven by forty blendshapes and a skeleton that has to
// reproduce it in an engine, or a cloth cache that has to become joints and
// weights. Pose the rig, sample it, and this works out the skinning.
//
// The maths is in mca_pose_skin.h and has no Maya in it, so it is tested
// off-DCC. This file is the Maya shell: sample the scene at the frames given,
// solve, hand the weights back, optionally write them into a skinCluster, and be
// undoable.
//
// How it is called
// ----------------
//     mcaPoseSkinner -mesh "head_geoShape"
//                    -joint "jaw" -joint "cheek_l" ...
//                    -restFrame 0 -frame 1 -frame 2 ...
//                    -maxInfluences 8 -locality 32
//                    -applyTo "skinCluster1";
//
// The result is one flat double array with a version number in front of it. A
// command result cannot carry a structure, and the alternative - the storage node
// the tool this replaces used, with eighteen attributes that had to exist before
// the command would run, and an error message per missing one - moves the problem
// rather than solving it. The layout is documented next to the code that fills it
// in and is parsed once, in poseskinner_api.py.
//
// Undo
// ----
// The tool this replaces said, in its undoIt, "I dont care about undo because the
// storageNode will be deleted in the python undo" - and set skin weights outside
// the undo queue. Ours records the weights it is about to overwrite and puts them
// back, so the whole thing is one undoable step like any other Maya operation.

#ifndef MCA_POSE_SKINNER_COMMAND_H
#define MCA_POSE_SKINNER_COMMAND_H

#include <maya/MArgList.h>
#include <maya/MDagPath.h>
#include <maya/MDoubleArray.h>
#include <maya/MIntArray.h>
#include <maya/MObject.h>
#include <maya/MPxCommand.h>
#include <maya/MString.h>
#include <maya/MStringArray.h>
#include <maya/MSyntax.h>
#include <maya/MTime.h>

#include <vector>

#include "mca_pose_skin.h"

class McaPoseSkinner : public MPxCommand {
public:
    static void* creator();
    static MSyntax newSyntax();
    static const MString kCommandName;

    MStatus doIt(const MArgList& args) override;
    MStatus redoIt() override;
    MStatus undoIt() override;
    bool isUndoable() const override { return true; }

private:
    MStatus gather(const MArgList& args);
    MStatus sample(mca::PoseSkinInput& input, MString& problem);

    /// Additive mode: fill `input.baseline`, `donorPoint` and `donorWeight` from the
    /// skinCluster already on the mesh.
    ///
    /// Done here rather than in Python because it needs the existing weights and every
    /// existing influence's world matrix on every frame - tens of megabytes on a face -
    /// and passing that through a command flag is not a thing anybody should do.
    MStatus sampleExistingSkin(mca::PoseSkinInput& input, MString& problem);
    MStatus applyWeights(const mca::PoseSkinResult& result, MString& problem);

    /// Additive mode's write-back: add the solved joints as influences, take what they
    /// earned out of the donors, and leave every other influence bit-identical.
    MStatus applyAdditiveWeights(const mca::PoseSkinResult& result, MString& problem);

    MString meshName_;
    MStringArray jointNames_;
    MString applyToName_;
    MString candidateSkinName_;

    /// Additive mode: the influences of the existing skin that give up weight.
    ///
    /// Non-empty turns the mode on. Everything not named here keeps the weight it
    /// has, exactly, which is the point of naming them at all.
    MStringArray donorNames_;
    MDoubleArray frames_;
    double restFrame_ = 0.0;
    bool restFrameGiven_ = false;
    std::vector<int> vertexSubset_;
    bool wantVertexError_ = false;
    bool wantBones_ = false;

    mca::PoseSkinOptions options_;

    /// Filled by redoIt so undoIt can put the skinCluster back exactly.
    MObject skinCluster_;
    MDagPath skinnedPath_;
    MObject skinnedComponent_;
    MIntArray appliedInfluences_;
    MDoubleArray previousWeights_;
    bool appliedWeights_ = false;
};

#endif  // MCA_POSE_SKINNER_COMMAND_H
