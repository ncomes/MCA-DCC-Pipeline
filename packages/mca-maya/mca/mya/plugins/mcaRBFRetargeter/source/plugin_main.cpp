// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_retarget_command.h"

#include <maya/MFnPlugin.h>

MStatus initializePlugin(MObject obj) {
    MFnPlugin plugin(obj, "Mechanical Art Studios", "1.0", "Any");
    return plugin.registerCommand(McaRetargetShapes::kCommandName,
                                  McaRetargetShapes::creator,
                                  McaRetargetShapes::newSyntax);
}

MStatus uninitializePlugin(MObject obj) {
    MFnPlugin plugin(obj);
    return plugin.deregisterCommand(McaRetargetShapes::kCommandName);
}
