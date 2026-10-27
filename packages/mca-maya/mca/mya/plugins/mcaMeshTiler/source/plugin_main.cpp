// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_mesh_tiler.h"

#include <maya/MFnPlugin.h>

MStatus initializePlugin(MObject object) {
    MFnPlugin plugin(object, "Mechanical Art Studios", "1.0", "Any");

    MStatus status = plugin.registerNode(McaMeshTiler::kNodeName, McaMeshTiler::kNodeId,
                                         McaMeshTiler::creator, McaMeshTiler::initialize);
    if (!status) {
        status.perror("registerNode mcaMeshTiler");
        return status;
    }
    return status;
}

MStatus uninitializePlugin(MObject object) {
    MFnPlugin plugin(object);

    MStatus status = plugin.deregisterNode(McaMeshTiler::kNodeId);
    if (!status) {
        status.perror("deregisterNode mcaMeshTiler");
        return status;
    }
    return status;
}
