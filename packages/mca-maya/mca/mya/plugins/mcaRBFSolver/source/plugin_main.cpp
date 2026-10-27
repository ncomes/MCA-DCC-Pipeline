// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_rbf_solver.h"

#include <maya/MFnPlugin.h>

MStatus initializePlugin(MObject obj) {
    MFnPlugin plugin(obj, "Mechanical Art Studios", "1.0", "Any");
    return plugin.registerNode(McaRBFSolver::kNodeName, McaRBFSolver::kNodeId,
                               McaRBFSolver::creator, McaRBFSolver::initialize);
}

MStatus uninitializePlugin(MObject obj) {
    MFnPlugin plugin(obj);
    return plugin.deregisterNode(McaRBFSolver::kNodeId);
}
