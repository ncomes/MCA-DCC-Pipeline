// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_physics_chain.h"

#include <maya/MFnPlugin.h>
#include <maya/MGlobal.h>

namespace {
const char* kVendor = "Mechanical Art Studios";
const char* kVersion = "0.1.0";
const char* kRequiredApi = "Any";
}  // namespace

MStatus initializePlugin(MObject obj) {
    MFnPlugin plugin(obj, kVendor, kVersion, kRequiredApi);

    MStatus status = plugin.registerNode(McaPhysicsChain::kNodeName, McaPhysicsChain::kNodeId,
                                         McaPhysicsChain::creator, McaPhysicsChain::initialize);
    if (!status) {
        status.perror("registerNode mcaPhysicsChain");
        return status;
    }
    return MS::kSuccess;
}

MStatus uninitializePlugin(MObject obj) {
    MFnPlugin plugin(obj);

    MStatus status = plugin.deregisterNode(McaPhysicsChain::kNodeId);
    if (!status) {
        status.perror("deregisterNode mcaPhysicsChain");
        return status;
    }
    return MS::kSuccess;
}
