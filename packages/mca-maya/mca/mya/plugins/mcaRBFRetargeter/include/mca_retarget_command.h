// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// mcaRetargetShapes: rebuild one mesh's blendshapes on another mesh.
//
// You have a head with forty correctives and a second head with the same
// topology and different proportions. This rebuilds all forty on the second
// head.
//
// The maths is in mca_retarget.h and has no Maya in it, so it is tested
// off-DCC. This file is the Maya shell: gather meshes, solve, make the new
// shapes, and be undoable.
//
// Named flags, not argument order
// -------------------------------
// The tool this replaces had no flags at all - its newSyntax() set a minimum
// and maximum object count and added nothing else, so every call was
// positional:
//
//     retargetShapes(source, shapes, target, useSphere, fromIds, toIds)
//
// Order was the only thing keeping it straight, there was no -help, and adding
// a parameter shifted every index after it. (It also declared a maximum of five
// objects while its argument parser accepted six, so whether the sixth was
// reachable at all is an open question.)
//
// Here the solver vertices come from the SELECTION, which is how an artist
// picks them anyway, and everything else is a named flag.

#ifndef MCA_RETARGET_COMMAND_H
#define MCA_RETARGET_COMMAND_H

#include <maya/MPxCommand.h>
#include <maya/MSyntax.h>
#include <maya/MArgList.h>
#include <maya/MObject.h>
#include <maya/MObjectArray.h>
#include <maya/MString.h>
#include <maya/MStringArray.h>
#include <maya/MDagModifier.h>

#include <vector>

#include "mca_retarget.h"

class McaRetargetShapes : public MPxCommand {
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

    MString sourceName_;
    MString targetName_;
    MStringArray shapeNames_;

    mca::RetargetOptions options_;
    std::vector<int> solverVertices_;

    /// The transforms made by the last run, so undo can take them away again.
    MObjectArray created_;
};

#endif  // MCA_RETARGET_COMMAND_H
