// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_pose_skinner_command.h"

#include <maya/MFnPlugin.h>

MStatus initializePlugin(MObject obj) {
    MFnPlugin plugin(obj, "Mechanical Art Studios", "1.0", "Any");
    return plugin.registerCommand(McaPoseSkinner::kCommandName, McaPoseSkinner::creator,
                                  McaPoseSkinner::newSyntax);
}

MStatus uninitializePlugin(MObject obj) {
    MFnPlugin plugin(obj);
    return plugin.deregisterCommand(McaPoseSkinner::kCommandName);
}
