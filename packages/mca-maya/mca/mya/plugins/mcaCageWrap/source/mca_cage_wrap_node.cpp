// MCA-DCC Pipeline - the mcaCageWrap deformer node.
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_cage_wrap_node.h"

#include <cmath>

#include <maya/MFnMatrixAttribute.h>
#include <maya/MFnMesh.h>
#include <maya/MFnNumericAttribute.h>
#include <maya/MFnTypedAttribute.h>
#include <maya/MGlobal.h>
#include <maya/MIntArray.h>
#include <maya/MPointArray.h>

#include "mca_node_ids.h"

namespace mca {

MTypeId CageWrapNode::id(nodeId(kCageWrapNode));
MString CageWrapNode::nodeName("mcaCageWrap");

MObject CageWrapNode::aRestCage;
MObject CageWrapNode::aRestCageMatrix;
MObject CageWrapNode::aCage;
MObject CageWrapNode::aCageMatrix;
MObject CageWrapNode::aStretch;
MObject CageWrapNode::aRebind;
MObject CageWrapNode::aThreads;
MObject CageWrapNode::aWorstRestError;
MObject CageWrapNode::aPointsOutside;
MObject CageWrapNode::aTermCount;
MObject CageWrapNode::aPointsRebound;

void* CageWrapNode::creator() {
    return new CageWrapNode();
}

MStatus CageWrapNode::initialize() {
    MFnTypedAttribute typed;
    MFnNumericAttribute numeric;
    MFnMatrixAttribute matrix;

    aRestCage = typed.create("restCage", "rc", MFnData::kMesh);
    typed.setStorable(true);

    aRestCageMatrix = matrix.create("restCageMatrix", "rcm");
    matrix.setStorable(true);

    aCage = typed.create("cage", "cg", MFnData::kMesh);
    typed.setStorable(true);

    aCageMatrix = matrix.create("cageMatrix", "cgm");
    matrix.setStorable(true);

    aStretch = numeric.create("stretch", "st", MFnNumericData::kDouble, 0.0);
    numeric.setKeyable(true);
    numeric.setMin(0.0);
    numeric.setMax(1.0);

    aRebind = numeric.create("rebind", "rb", MFnNumericData::kBoolean, false);
    numeric.setKeyable(false);

    aThreads = numeric.create("threads", "th", MFnNumericData::kInt, 0);
    numeric.setMin(0);

    // Read-only, written by the bind. A deformer that measures itself has to have
    // somewhere to put the measurement, and an output attribute is the one place a
    // script can read it from without a command of its own.
    aWorstRestError = numeric.create("worstRestError", "wre", MFnNumericData::kDouble, 0.0);
    numeric.setWritable(false);
    numeric.setStorable(false);

    aPointsOutside = numeric.create("pointsOutside", "pso", MFnNumericData::kInt, 0);
    numeric.setWritable(false);
    numeric.setStorable(false);

    aTermCount = numeric.create("weightsKept", "wk", MFnNumericData::kInt, 0);
    numeric.setWritable(false);
    numeric.setStorable(false);

    aPointsRebound = numeric.create("pointsRebound", "psr", MFnNumericData::kInt, 0);
    numeric.setWritable(false);
    numeric.setStorable(false);

    MObject inputs[] = {aRestCage, aRestCageMatrix, aCage,        aCageMatrix,
                        aStretch,  aRebind,         aThreads};
    for (MObject& attribute : inputs) {
        addAttribute(attribute);
        attributeAffects(attribute, outputGeom);
    }
    MObject reports[] = {aWorstRestError, aPointsOutside, aTermCount,
                         aPointsRebound};
    for (MObject& attribute : reports) {
        addAttribute(attribute);
    }

    return MS::kSuccess;
}

MStatus CageWrapNode::makeWeightsPaintable() {
    // NOT called from initialize(). That runs in the middle of registerNode, before the
    // node type exists, so `makePaintable` tries to instantiate one and Maya logs
    // "Unable to create the node (mcaCageWrap)" on every load. The reference plug-in
    // does exactly this and has logged that warning for years.
    return MGlobal::executeCommand("makePaintable -attrType multiFloat -sm deformer " +
                                   nodeName + " weights;");
}

MStatus CageWrapNode::installAttributeEditorTemplate() {
    MString command;
    command += "global proc AE" + nodeName + "Template(string $nodeName)\n";
    command += "{\n";
    command += "  editorTemplate -beginScrollLayout;\n";
    command += "    editorTemplate -beginLayout \"Cage\" -collapse 0;\n";
    command += "      editorTemplate -addControl \"stretch\";\n";
    command += "      editorTemplate -addControl \"envelope\";\n";
    command += "    editorTemplate -endLayout;\n";
    command += "    editorTemplate -beginLayout \"What The Bind Measured\" -collapse 0;\n";
    command += "      editorTemplate -addControl \"worstRestError\";\n";
    command += "      editorTemplate -addControl \"pointsOutside\";\n";
    command += "      editorTemplate -addControl \"pointsRebound\";\n";
    command += "      editorTemplate -addControl \"weightsKept\";\n";
    command += "    editorTemplate -endLayout;\n";
    command += "    editorTemplate -beginLayout \"Advanced\" -collapse 1;\n";
    command += "      editorTemplate -addControl \"rebind\";\n";
    command += "      editorTemplate -addControl \"threads\";\n";
    command += "      editorTemplate -addControl \"nodeState\";\n";
    command += "    editorTemplate -endLayout;\n";
    command += "    editorTemplate -suppress \"restCage\";\n";
    command += "    editorTemplate -suppress \"cage\";\n";
    command += "    editorTemplate -suppress \"restCageMatrix\";\n";
    command += "    editorTemplate -suppress \"cageMatrix\";\n";
    command += "    editorTemplate -addExtraControls;\n";
    command += "  editorTemplate -endScrollLayout;\n";
    command += "}\n";
    return MGlobal::executeCommand(command);
}

double CageWrapNode::fingerprintOf(const cage::Cage& shape) {
    // Not a hash for security, just something that moves when any cage point does.
    double total = 0.0;
    for (size_t index = 0; index < shape.points.size(); ++index) {
        const cage::Vec3& point = shape.points[index];
        const double weight = static_cast<double>(index + 1);
        total += weight * (point.x * 1.7 + point.y * 2.3 - point.z * 3.1);
    }
    return total;
}

MStatus CageWrapNode::readCage(MDataBlock& block, MObject& attribute, MObject& matrixAttribute,
                               std::vector<cage::Triangle>& triangles, cage::Cage& out,
                               std::string* problem) {
    MStatus status;
    MObject mesh = block.inputValue(attribute, &status).asMesh();
    if (status != MS::kSuccess || mesh.isNull()) {
        if (problem) {
            *problem = "Nothing is connected to the cage.";
        }
        return MS::kInvalidParameter;
    }

    const MMatrix toWorld = block.inputValue(matrixAttribute, &status).asMatrix();

    MFnMesh shape(mesh, &status);
    if (status != MS::kSuccess) {
        if (problem) {
            *problem = "The cage is not a mesh.";
        }
        return MS::kInvalidParameter;
    }

    MPointArray points;
    shape.getPoints(points, MSpace::kObject);

    out.points.resize(points.length());
    for (unsigned int index = 0; index < points.length(); ++index) {
        const MPoint world = points[index] * toWorld;
        out.points[index] = cage::Vec3(world.x, world.y, world.z);
    }

    if (triangles.empty()) {
        // Triangulated here rather than demanded of the artist. The reference refuses
        // a cage with a quad in it and tells them to triangulate the whole thing,
        // which is a chore that also changes the cage they modelled.
        MIntArray perFace;
        MIntArray indices;
        if (shape.getTriangles(perFace, indices) != MS::kSuccess || indices.length() < 3) {
            if (problem) {
                *problem = "The cage could not be triangulated.";
            }
            return MS::kInvalidParameter;
        }
        triangles.reserve(indices.length() / 3);
        for (unsigned int index = 0; index + 2 < indices.length(); index += 3) {
            triangles.push_back(cage::Triangle(indices[index], indices[index + 1],
                                               indices[index + 2]));
        }
    }

    out.triangles = triangles;
    if (problem) {
        problem->clear();
    }
    return MS::kSuccess;
}

MStatus CageWrapNode::deform(MDataBlock& block, MItGeometry& iterator,
                             const MMatrix& geometryMatrix, unsigned int multiIndex) {
    MStatus status;

    const double envelope = static_cast<double>(block.inputValue(this->envelope).asFloat());
    if (std::fabs(envelope) < 1e-12) {
        return MS::kSuccess;
    }

    const double stretch = block.inputValue(aStretch).asDouble();
    const bool rebind = block.inputValue(aRebind).asBool();
    const int threads = block.inputValue(aThreads).asInt();

    Bound& held = bound_[multiIndex];

    std::string problem;
    std::vector<cage::Triangle> restTriangles = held.triangles;
    cage::Cage restCage;
    if (readCage(block, aRestCage, aRestCageMatrix, restTriangles, restCage, &problem) !=
        MS::kSuccess) {
        if (!held.complained) {
            MGlobal::displayWarning(nodeName + ": " + problem.c_str());
            held.complained = true;
        }
        return MS::kSuccess;  // pass the geometry through untouched rather than fail
    }

    // Has anything happened that means the bind is no longer about this cage?
    //
    // Checked rather than left to a button. The reference caches the rest cage the
    // first time it evaluates and keeps it until somebody flips `refresh`, so editing
    // the cage afterwards silently deforms against the old one - which looks like the
    // deformer being wrong rather than stale.
    const double fingerprint = fingerprintOf(restCage);
    const size_t meshPoints = static_cast<size_t>(iterator.count());
    const bool stale = held.bind.weights.empty() || rebind ||
                       held.cagePoints != restCage.vertexCount() ||
                       held.meshPoints != meshPoints ||
                       std::fabs(held.restFingerprint - fingerprint) > 1e-9;

    if (stale) {
        std::string trouble;
        if (!cage::checkCage(restCage, &trouble)) {
            if (!held.complained) {
                MGlobal::displayWarning(nodeName + ": " + trouble.c_str());
                held.complained = true;
            }
            return MS::kSuccess;
        }

        MPointArray restPoints;
        iterator.allPositions(restPoints, MSpace::kObject);

        std::vector<cage::Vec3> world(restPoints.length());
        for (unsigned int index = 0; index < restPoints.length(); ++index) {
            const MPoint point = restPoints[index] * geometryMatrix;
            world[index] = cage::Vec3(point.x, point.y, point.z);
        }

        cage::BindOptions options;
        options.threads = threads;

        if (!cage::bind(restCage, world, options, held.bind, &trouble)) {
            if (!held.complained) {
                MGlobal::displayWarning(nodeName + ": " + trouble.c_str());
                held.complained = true;
            }
            held.bind = cage::Bind();
            return MS::kSuccess;
        }

        held.triangles = restTriangles;
        held.cagePoints = restCage.vertexCount();
        held.meshPoints = meshPoints;
        held.restFingerprint = fingerprint;
        held.complained = false;

        block.outputValue(aWorstRestError).setDouble(held.bind.worstRestError);
        block.outputValue(aPointsOutside).setInt(held.bind.exteriorCount);
        block.outputValue(aTermCount).setInt(static_cast<int>(held.bind.termCount));
        block.outputValue(aPointsRebound).setInt(held.bind.healedCount);

        MString said = nodeName + ": bound " ;
        said += static_cast<int>(meshPoints);
        said += " point(s) to a cage of ";
        said += static_cast<int>(restCage.triangleCount());
        said += " triangle(s). Worst rest error ";
        said += held.bind.worstRestError;
        said += "; ";
        said += held.bind.exteriorCount;
        said += " point(s) outside the cage, ";
        said += held.bind.healedCount;
        said += " rebound to their closest face. Holding ";
        said += static_cast<int>(held.bind.termCount * sizeof(float) / 1024);
        said += " KB of weights.";
        MGlobal::displayInfo(said);
    }

    std::vector<cage::Triangle> movedTriangles = held.triangles;
    cage::Cage movedCage;
    if (readCage(block, aCage, aCageMatrix, movedTriangles, movedCage, &problem) !=
        MS::kSuccess) {
        if (!held.complained) {
            MGlobal::displayWarning(nodeName + ": " + problem.c_str());
            held.complained = true;
        }
        return MS::kSuccess;
    }

    cage::ApplyOptions options;
    options.stretch = stretch;
    options.threads = threads;

    std::vector<cage::Vec3> moved;
    if (!cage::apply(held.bind, movedCage, options, moved, &problem)) {
        if (!held.complained) {
            MGlobal::displayWarning(nodeName + ": " + problem.c_str());
            held.complained = true;
        }
        return MS::kSuccess;
    }

    const MMatrix toObject = geometryMatrix.inverse();

    for (iterator.reset(); !iterator.isDone(); iterator.next()) {
        const unsigned int index = static_cast<unsigned int>(iterator.index());
        if (index >= moved.size()) {
            continue;
        }

        const double painted = static_cast<double>(weightValue(block, multiIndex, index));
        const double blend = envelope * painted;
        if (std::fabs(blend) < 1e-12) {
            continue;
        }

        const MPoint was = iterator.position(MSpace::kObject);
        const MPoint became =
            MPoint(moved[index].x, moved[index].y, moved[index].z) * toObject;
        iterator.setPosition(was + (became - was) * blend, MSpace::kObject);
    }

    return MS::kSuccess;
}

}  // namespace mca
