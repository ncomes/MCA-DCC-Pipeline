// MCA-DCC Pipeline - mcaCageWrap plug-in entry points.
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include <maya/MFnPlugin.h>

#include "mca_cage_wrap_node.h"

MStatus initializePlugin(MObject object) {
    MFnPlugin plugin(object, "Mechanical Art Studios", "1.0", "Any");

    MStatus status = plugin.registerNode(mca::CageWrapNode::nodeName, mca::CageWrapNode::id,
                                         mca::CageWrapNode::creator,
                                         mca::CageWrapNode::initialize, MPxNode::kDeformerNode);
    if (!status) {
        status.perror("registerNode mcaCageWrap");
        return status;
    }

    mca::CageWrapNode::makeWeightsPaintable();
    mca::CageWrapNode::installAttributeEditorTemplate();
    return status;
}

MStatus uninitializePlugin(MObject object) {
    MFnPlugin plugin(object);

    MStatus status = plugin.deregisterNode(mca::CageWrapNode::id);
    if (!status) {
        status.perror("deregisterNode mcaCageWrap");
        return status;
    }
    return status;
}
