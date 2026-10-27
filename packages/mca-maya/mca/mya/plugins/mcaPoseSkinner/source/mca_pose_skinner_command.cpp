// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_pose_skinner_command.h"

#include <maya/MAnimControl.h>
#include <maya/MComputation.h>
#include <maya/MArgDatabase.h>
#include <maya/MDagPathArray.h>
#include <maya/MFnDagNode.h>
#include <maya/MFnDependencyNode.h>
#include <maya/MFnMatrixData.h>
#include <maya/MFnMesh.h>
#include <maya/MFnSingleIndexedComponent.h>
#include <maya/MFnSkinCluster.h>
#include <maya/MGlobal.h>
#include <maya/MItMeshVertex.h>
#include <maya/MMatrix.h>
#include <maya/MPlug.h>
#include <maya/MPointArray.h>
#include <maya/MSelectionList.h>

#include <algorithm>
#include <map>
#include <sstream>

namespace {

const char* kMeshShort = "-m";
const char* kMeshLong = "-mesh";
const char* kJointShort = "-j";
const char* kJointLong = "-joint";
const char* kFrameShort = "-f";
const char* kFrameLong = "-frame";
const char* kRestFrameShort = "-rf";
const char* kRestFrameLong = "-restFrame";
const char* kVertexShort = "-v";
const char* kVertexLong = "-vertex";
const char* kMaxInfluencesShort = "-mi";
const char* kMaxInfluencesLong = "-maxInfluences";
const char* kAffinityShort = "-af";
const char* kAffinityLong = "-affinity";
const char* kSmoothingShort = "-sm";
const char* kSmoothingLong = "-smoothing";
const char* kSmoothingRoundsShort = "-sr";
const char* kSmoothingRoundsLong = "-smoothingRounds";
const char* kLocalityShort = "-lo";
const char* kLocalityLong = "-locality";
const char* kGeodesicShort = "-ge";
const char* kGeodesicLong = "-geodesic";
const char* kIterationsShort = "-it";
const char* kIterationsLong = "-maxIterations";
const char* kSolveBonesShort = "-sb";
const char* kSolveBonesLong = "-solveBones";
const char* kRigidShort = "-rb";
const char* kRigidLong = "-rigidBones";
const char* kUpdateBindShort = "-ub";
const char* kUpdateBindLong = "-updateBindPose";
const char* kBreakShort = "-ib";
const char* kBreakLong = "-improvementBreak";
const char* kFloorShort = "-wf";
const char* kFloorLong = "-weightFloor";
const char* kPruneShort = "-pp";
const char* kPruneLong = "-prunePerStep";
const char* kHoldoutShort = "-ho";
const char* kHoldoutLong = "-holdout";
const char* kThreadsShort = "-th";
const char* kThreadsLong = "-threads";
const char* kApplyToShort = "-at";
const char* kApplyToLong = "-applyTo";
const char* kCandidateShort = "-cs";
const char* kCandidateLong = "-candidatesFrom";
const char* kVertexErrorShort = "-pe";
const char* kVertexErrorLong = "-perVertexError";
const char* kReturnBonesShort = "-rn";
const char* kReturnBonesLong = "-returnBones";
const char* kDonorShort = "-dn";
const char* kDonorLong = "-donor";

/// The mesh shape under a name that may be a transform or a shape.
MStatus meshPath(const MString& name, MDagPath& path, MString& problem) {
    MSelectionList list;
    if (!list.add(name)) {
        problem = "There is nothing called \"" + name + "\" in the scene.";
        return MS::kNotFound;
    }
    MDagPath found;
    if (!list.getDagPath(0, found)) {
        problem = "\"" + name + "\" is not a DAG object, so it cannot be a mesh.";
        return MS::kInvalidParameter;
    }
    if (found.hasFn(MFn::kTransform) && !found.hasFn(MFn::kMesh)) {
        // Take the first non-intermediate mesh under it, which is what an artist
        // means when they select a character and say "this mesh".
        unsigned int shapes = 0;
        found.numberOfShapesDirectlyBelow(shapes);
        for (unsigned int index = 0; index < shapes; ++index) {
            MDagPath candidate = found;
            candidate.extendToShapeDirectlyBelow(index);
            if (!candidate.hasFn(MFn::kMesh)) {
                continue;
            }
            if (MFnDagNode(candidate).isIntermediateObject()) {
                continue;
            }
            path = candidate;
            return MS::kSuccess;
        }
        problem = "\"" + name + "\" has no mesh shape under it.";
        return MS::kInvalidParameter;
    }
    if (!found.hasFn(MFn::kMesh)) {
        problem = "\"" + name + "\" is not a mesh.";
        return MS::kInvalidParameter;
    }
    path = found;
    return MS::kSuccess;
}

/// World-space points, read in a way that forces the DG to evaluate.
///
/// **`MFnMesh(dagPath).getPoints()` does not force evaluation, and that is a trap
/// with teeth.** Under parallel evaluation a shape recomputes when something pulls
/// on it - usually the viewport. A mesh that is HIDDEN has nobody pulling, so after
/// `setCurrentTime` its cached points are still the previous frame's, or the rest
/// frame's, for ever. Sampling it that way gives a solve a mesh that never moves;
/// the solve then fits that faithfully and reports a tiny error, because the error
/// it reports is measured against the samples it was given.
///
/// Hiding the source and looking at the result is exactly what an artist does with
/// this tool, so this is not a corner case. Asking for the value of the `outMesh`
/// plug is a pull, and the same for `worldMatrix` - which also has to be read that
/// way, for the same reason.
///
/// This cost an evening: a scene audit built on the unsafe read reported 20 times
/// the error that was really there, on a result that was correct.
MStatus sampleWorldPoints(const MDagPath& path, MPointArray& points, MString& problem) {
    MStatus status;
    MFnDagNode node(path);

    MPlug outMesh = node.findPlug("outMesh", false, &status);
    if (!status) {
        problem = "Could not find outMesh on " + path.partialPathName() + ".";
        return status;
    }
    MObject meshData = outMesh.asMObject(&status);
    if (!status || meshData.isNull()) {
        problem = "Could not evaluate " + path.partialPathName() + ".";
        return MS::kFailure;
    }

    MPlug worldMatrixArray = node.findPlug("worldMatrix", false, &status);
    if (!status) {
        problem = "Could not find worldMatrix on " + path.partialPathName() + ".";
        return status;
    }
    MPlug worldMatrixPlug = worldMatrixArray.elementByLogicalIndex(
        static_cast<unsigned int>(path.instanceNumber()));
    MObject matrixData = worldMatrixPlug.asMObject(&status);
    if (!status || matrixData.isNull()) {
        problem = "Could not evaluate the transform of " + path.partialPathName() + ".";
        return MS::kFailure;
    }
    const MMatrix world = MFnMatrixData(matrixData).matrix();

    MFnMesh posed(meshData, &status);
    if (!status) {
        problem = path.partialPathName() + " did not evaluate to a mesh.";
        return status;
    }
    status = posed.getPoints(points, MSpace::kObject);
    if (!status) {
        return status;
    }
    for (unsigned int index = 0; index < points.length(); ++index) {
        points[index] = points[index] * world;
    }
    return MS::kSuccess;
}

/// A joint's world matrix, read the same way and for the same reason.
MStatus sampleWorldMatrix(const MDagPath& path, MMatrix& out) {
    MStatus status;
    MPlug array = MFnDagNode(path).findPlug("worldMatrix", false, &status);
    if (!status) {
        return status;
    }
    MPlug plug = array.elementByLogicalIndex(static_cast<unsigned int>(path.instanceNumber()));
    MObject data = plug.asMObject(&status);
    if (!status || data.isNull()) {
        return MS::kFailure;
    }
    out = MFnMatrixData(data).matrix();
    return MS::kSuccess;
}

mca::Mat4 toMat4(const MMatrix& matrix) {
    mca::Mat4 out;
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            out.m[row][column] = matrix[row][column];
        }
    }
    return out;
}

/// Additive mode: everything about the skin that is already on the mesh.
struct ExistingSkin {
    /// The mesh the skinCluster deforms, which is not always the mesh that was sampled.
    MDagPath deformed;
    MDagPathArray influences;
    /// World-to-influence at the bind pose, per influence.
    std::vector<mca::Mat4> bindInverse;
    /// 1 for an influence the user nominated as a donor, 0 for one to leave alone.
    std::vector<char> donor;
    /// `weights[usedVertex][influence]`.
    std::vector<std::vector<double>> weights;
    /// The donors' total weight per used vertex - the most that can be taken there.
    std::vector<double> donorTotal;
};

/// Read the existing skin, and work out which influences are giving up weight.
///
/// **The weights are read from the mesh the skinCluster actually deforms, not from the
/// mesh that was sampled.** Those are usually the same mesh and deliberately are not
/// when the poses live on a blendshaped mesh and the skin goes on a clean duplicate -
/// which is the normal way to use this. Reading them off the sampled mesh worked only
/// by accident in the case where the two coincide, and `MFnSkinCluster::getWeights`
/// asked for a mesh its cluster does not deform does not fail loudly.
MStatus readExistingSkin(const MString& skinName, const MDagPath& mesh,
                         const std::vector<int>& used, const MStringArray& donorNames,
                         ExistingSkin& out, MString& problem) {
    MSelectionList list;
    if (!list.add(skinName)) {
        problem = "No skinCluster called \"" + skinName + "\" to add joints to.";
        return MS::kNotFound;
    }
    MObject node;
    list.getDependNode(0, node);
    if (!node.hasFn(MFn::kSkinClusterFilter)) {
        problem = "\"" + skinName + "\" is not a skinCluster.";
        return MS::kInvalidParameter;
    }
    MFnSkinCluster cluster(node);
    cluster.influenceObjects(out.influences);
    if (out.influences.length() == 0) {
        problem = "\"" + skinName + "\" has no influences, so there is nothing to take "
                  "weight from.";
        return MS::kInvalidParameter;
    }

    // Which of them are donors. Matched on the full path so that a short name that
    // happens to be ambiguous cannot silently pick the wrong joint.
    out.donor.assign(out.influences.length(), 0);
    int donorCount = 0;
    for (unsigned int wanted = 0; wanted < donorNames.length(); ++wanted) {
        MSelectionList one;
        if (!one.add(donorNames[wanted])) {
            problem = "No influence called \"" + donorNames[wanted] + "\".";
            return MS::kNotFound;
        }
        MDagPath path;
        one.getDagPath(0, path);
        bool found = false;
        for (unsigned int index = 0; index < out.influences.length(); ++index) {
            if (out.influences[index].fullPathName() == path.fullPathName()) {
                if (!out.donor[index]) {
                    ++donorCount;
                }
                out.donor[index] = 1;
                found = true;
            }
        }
        if (!found) {
            problem = "\"" + donorNames[wanted] + "\" is not an influence of " + skinName +
                      ", so it has no weight to give. Name one of its influences as the donor.";
            return MS::kInvalidParameter;
        }
    }
    if (donorCount == 0) {
        problem = "None of the donors named are influences of " + skinName + ".";
        return MS::kInvalidParameter;
    }

    // The bind matrices, taken from the skinCluster's own bindPreMatrix rather than
    // from where the joint happens to be standing now. They are the same on a rig
    // nobody has moved since binding and different the moment somebody has, and
    // using the live transform in that case silently shifts every baseline.
    MPlug bindPre = MFnDependencyNode(node).findPlug("bindPreMatrix", false);
    out.bindInverse.assign(out.influences.length(), mca::Mat4());
    for (unsigned int index = 0; index < out.influences.length(); ++index) {
        MStatus indexStatus;
        const unsigned int logical =
            cluster.indexForInfluenceObject(out.influences[index], &indexStatus);
        bool got = false;
        if (indexStatus && !bindPre.isNull()) {
            MPlug one = bindPre.elementByLogicalIndex(logical);
            MObject data = one.asMObject();
            if (!data.isNull() && data.hasFn(MFn::kMatrixData)) {
                out.bindInverse[index] = toMat4(MFnMatrixData(data).matrix());
                got = true;
            }
        }
        if (!got) {
            out.bindInverse[index] =
                toMat4(out.influences[index].inclusiveMatrix().inverse());
        }
    }

    // The mesh this cluster deforms - which is what its weights are indexed by.
    MDagPath deformed;
    if (cluster.getPathAtIndex(0, deformed) != MS::kSuccess) {
        problem = skinName + " does not deform any geometry.";
        return MS::kInvalidParameter;
    }
    const int deformedCount = MFnMesh(deformed).numVertices();
    const int sampledCount = MFnMesh(mesh).numVertices();
    if (deformedCount != sampledCount) {
        std::ostringstream stream;
        stream << skinName.asChar() << " deforms a mesh with " << deformedCount
               << " vertices and the poses were sampled on one with " << sampledCount
               << ". Additive mode needs the same topology on both, because a weight is "
                  "matched to a vertex by its number.";
        problem = stream.str().c_str();
        return MS::kInvalidParameter;
    }

    // The weights, one call for the whole mesh.
    MFnSingleIndexedComponent components;
    MObject component = components.create(MFn::kMeshVertComponent);
    components.setCompleteData(deformedCount);
    MDoubleArray flat;
    unsigned int perVertex = 0;
    MStatus status = cluster.getWeights(deformed, component, flat, perVertex);
    if (!status || perVertex != out.influences.length()) {
        problem = "Could not read the weights already on " + skinName + ".";
        return MS::kFailure;
    }
    out.deformed = deformed;

    out.weights.assign(used.size(), std::vector<double>(perVertex, 0.0));
    out.donorTotal.assign(used.size(), 0.0);
    for (std::size_t slot = 0; slot < used.size(); ++slot) {
        const unsigned int vertex = static_cast<unsigned int>(used[slot]);
        for (unsigned int influence = 0; influence < perVertex; ++influence) {
            const double value = flat[vertex * perVertex + influence];
            out.weights[slot][influence] = value;
            if (out.donor[influence]) {
                out.donorTotal[slot] += value;
            }
        }
    }
    return MS::kSuccess;
}

}  // namespace

const MString McaPoseSkinner::kCommandName("mcaPoseSkinner");

void* McaPoseSkinner::creator() {
    return new McaPoseSkinner();
}

MSyntax McaPoseSkinner::newSyntax() {
    MSyntax syntax;
    syntax.addFlag(kMeshShort, kMeshLong, MSyntax::kString);
    syntax.addFlag(kJointShort, kJointLong, MSyntax::kString);
    syntax.makeFlagMultiUse(kJointShort);
    syntax.addFlag(kFrameShort, kFrameLong, MSyntax::kDouble);
    syntax.makeFlagMultiUse(kFrameShort);
    syntax.addFlag(kRestFrameShort, kRestFrameLong, MSyntax::kDouble);
    syntax.addFlag(kVertexShort, kVertexLong, MSyntax::kLong);
    syntax.makeFlagMultiUse(kVertexShort);
    syntax.addFlag(kMaxInfluencesShort, kMaxInfluencesLong, MSyntax::kLong);
    syntax.addFlag(kAffinityShort, kAffinityLong, MSyntax::kDouble);
    syntax.addFlag(kSmoothingShort, kSmoothingLong, MSyntax::kDouble);
    syntax.addFlag(kSmoothingRoundsShort, kSmoothingRoundsLong, MSyntax::kLong);
    syntax.addFlag(kLocalityShort, kLocalityLong, MSyntax::kLong);
    syntax.addFlag(kGeodesicShort, kGeodesicLong, MSyntax::kBoolean);
    syntax.addFlag(kIterationsShort, kIterationsLong, MSyntax::kLong);
    syntax.addFlag(kSolveBonesShort, kSolveBonesLong, MSyntax::kBoolean);
    syntax.addFlag(kRigidShort, kRigidLong, MSyntax::kBoolean);
    syntax.addFlag(kUpdateBindShort, kUpdateBindLong, MSyntax::kBoolean);
    syntax.addFlag(kBreakShort, kBreakLong, MSyntax::kDouble);
    syntax.addFlag(kFloorShort, kFloorLong, MSyntax::kDouble);
    syntax.addFlag(kPruneShort, kPruneLong, MSyntax::kBoolean);
    syntax.addFlag(kHoldoutShort, kHoldoutLong, MSyntax::kLong);
    syntax.makeFlagMultiUse(kHoldoutShort);
    syntax.addFlag(kThreadsShort, kThreadsLong, MSyntax::kLong);
    syntax.addFlag(kApplyToShort, kApplyToLong, MSyntax::kString);
    syntax.addFlag(kCandidateShort, kCandidateLong, MSyntax::kString);
    syntax.addFlag(kVertexErrorShort, kVertexErrorLong, MSyntax::kBoolean);
    syntax.addFlag(kReturnBonesShort, kReturnBonesLong, MSyntax::kBoolean);
    syntax.addFlag(kDonorShort, kDonorLong, MSyntax::kString);
    syntax.makeFlagMultiUse(kDonorShort);
    syntax.enableQuery(false);
    syntax.enableEdit(false);
    return syntax;
}

MStatus McaPoseSkinner::gather(const MArgList& args) {
    MStatus status;
    MArgDatabase database(syntax(), args, &status);
    if (!status) {
        return status;
    }

    if (!database.isFlagSet(kMeshShort)) {
        MGlobal::displayError("mcaPoseSkinner needs -mesh: the mesh that deforms.");
        return MS::kInvalidParameter;
    }
    database.getFlagArgument(kMeshShort, 0, meshName_);

    const unsigned int joints = database.numberOfFlagUses(kJointShort);
    for (unsigned int index = 0; index < joints; ++index) {
        MArgList list;
        database.getFlagArgumentList(kJointShort, index, list);
        jointNames_.append(list.asString(0));
    }
    if (jointNames_.length() == 0) {
        MGlobal::displayError("mcaPoseSkinner needs at least one -joint.");
        return MS::kInvalidParameter;
    }

    const unsigned int donors = database.numberOfFlagUses(kDonorShort);
    for (unsigned int index = 0; index < donors; ++index) {
        MArgList list;
        database.getFlagArgumentList(kDonorShort, index, list);
        donorNames_.append(list.asString(0));
    }
    if (donorNames_.length() > 0) {
        options_.additive = true;
        // The -applyTo check lives further down, where that flag is actually parsed.
    }

    const unsigned int frames = database.numberOfFlagUses(kFrameShort);
    for (unsigned int index = 0; index < frames; ++index) {
        MArgList list;
        database.getFlagArgumentList(kFrameShort, index, list);
        frames_.append(list.asDouble(0));
    }
    if (frames_.length() == 0) {
        MGlobal::displayError(
            "mcaPoseSkinner needs at least one -frame: a frame where the mesh is posed. "
            "A rest shape on its own has nothing in it to solve from.");
        return MS::kInvalidParameter;
    }

    if (database.isFlagSet(kRestFrameShort)) {
        database.getFlagArgument(kRestFrameShort, 0, restFrame_);
        restFrameGiven_ = true;
    }

    const unsigned int vertices = database.numberOfFlagUses(kVertexShort);
    for (unsigned int index = 0; index < vertices; ++index) {
        MArgList list;
        database.getFlagArgumentList(kVertexShort, index, list);
        vertexSubset_.push_back(list.asInt(0));
    }

    const unsigned int holdout = database.numberOfFlagUses(kHoldoutShort);
    for (unsigned int index = 0; index < holdout; ++index) {
        MArgList list;
        database.getFlagArgumentList(kHoldoutShort, index, list);
        options_.holdoutPoses.push_back(list.asInt(0));
    }

    if (database.isFlagSet(kMaxInfluencesShort)) {
        database.getFlagArgument(kMaxInfluencesShort, 0, options_.maxInfluences);
    }
    if (database.isFlagSet(kAffinityShort)) {
        database.getFlagArgument(kAffinityShort, 0, options_.affinity);
    }
    if (database.isFlagSet(kSmoothingShort)) {
        database.getFlagArgument(kSmoothingShort, 0, options_.smoothing);
    }
    if (database.isFlagSet(kSmoothingRoundsShort)) {
        database.getFlagArgument(kSmoothingRoundsShort, 0, options_.smoothingRounds);
    }
    if (database.isFlagSet(kLocalityShort)) {
        database.getFlagArgument(kLocalityShort, 0, options_.localityJoints);
    }
    if (database.isFlagSet(kGeodesicShort)) {
        database.getFlagArgument(kGeodesicShort, 0, options_.geodesicLocality);
    }
    if (database.isFlagSet(kIterationsShort)) {
        database.getFlagArgument(kIterationsShort, 0, options_.maxIterations);
    }
    if (database.isFlagSet(kSolveBonesShort)) {
        database.getFlagArgument(kSolveBonesShort, 0, options_.solveBones);
    }
    if (database.isFlagSet(kRigidShort)) {
        database.getFlagArgument(kRigidShort, 0, options_.rigidBones);
    }
    if (database.isFlagSet(kUpdateBindShort)) {
        database.getFlagArgument(kUpdateBindShort, 0, options_.updateBindPose);
    }
    if (database.isFlagSet(kBreakShort)) {
        database.getFlagArgument(kBreakShort, 0, options_.improvementBreak);
    }
    if (database.isFlagSet(kFloorShort)) {
        database.getFlagArgument(kFloorShort, 0, options_.weightFloor);
    }
    if (database.isFlagSet(kPruneShort)) {
        database.getFlagArgument(kPruneShort, 0, options_.prunePerStep);
    }
    if (database.isFlagSet(kThreadsShort)) {
        database.getFlagArgument(kThreadsShort, 0, options_.threads);
    }
    if (database.isFlagSet(kApplyToShort)) {
        database.getFlagArgument(kApplyToShort, 0, applyToName_);
    }
    if (options_.additive && applyToName_.length() == 0) {
        MGlobal::displayError("mcaPoseSkinner -donor needs -applyTo: additive mode adds joints "
                              "to a skinCluster that already exists, so it has to be told which "
                              "one.");
        return MS::kInvalidParameter;
    }
    if (database.isFlagSet(kCandidateShort)) {
        database.getFlagArgument(kCandidateShort, 0, candidateSkinName_);
    }
    if (database.isFlagSet(kVertexErrorShort)) {
        database.getFlagArgument(kVertexErrorShort, 0, wantVertexError_);
    }
    if (database.isFlagSet(kReturnBonesShort)) {
        database.getFlagArgument(kReturnBonesShort, 0, wantBones_);
    }
    return MS::kSuccess;
}

MStatus McaPoseSkinner::sample(mca::PoseSkinInput& input, MString& problem) {
    MDagPath mesh;
    MStatus status = meshPath(meshName_, mesh, problem);
    if (!status) {
        return status;
    }
    skinnedPath_ = mesh;

    MDagPathArray joints;
    for (unsigned int index = 0; index < jointNames_.length(); ++index) {
        MSelectionList list;
        if (!list.add(jointNames_[index])) {
            problem = "No joint called \"" + jointNames_[index] + "\".";
            return MS::kNotFound;
        }
        MDagPath path;
        if (!list.getDagPath(0, path) || !path.hasFn(MFn::kTransform)) {
            problem = "\"" + jointNames_[index] +
                      "\" is not a transform, so it cannot act as a joint.";
            return MS::kInvalidParameter;
        }
        joints.append(path);
    }

    const int jointCount = static_cast<int>(joints.length());
    const MTime::Unit unit = MTime::uiUnit();
    const MTime wasAt = MAnimControl::currentTime();

    // The rest pose. Defaults to wherever the artist is standing, which is the
    // frame they are looking at when they press the button.
    const MTime restAt = restFrameGiven_ ? MTime(restFrame_, unit) : wasAt;
    MAnimControl::setCurrentTime(restAt);

    MPointArray restPoints;
    if (!sampleWorldPoints(mesh, restPoints, problem)) {
        MAnimControl::setCurrentTime(wasAt);
        return MS::kFailure;
    }
    const int fullVertexCount = static_cast<int>(restPoints.length());
    if (fullVertexCount == 0) {
        MAnimControl::setCurrentTime(wasAt);
        problem = "\"" + meshName_ + "\" has no vertices.";
        return MS::kInvalidParameter;
    }

    // Which vertices are being solved, and the map back to mesh vertex ids.
    std::vector<int> used;
    std::vector<int> positionOf(static_cast<std::size_t>(fullVertexCount), -1);
    if (vertexSubset_.empty()) {
        used.resize(static_cast<std::size_t>(fullVertexCount));
        for (int vertex = 0; vertex < fullVertexCount; ++vertex) {
            used[static_cast<std::size_t>(vertex)] = vertex;
            positionOf[static_cast<std::size_t>(vertex)] = vertex;
        }
    } else {
        std::vector<int> sorted = vertexSubset_;
        std::sort(sorted.begin(), sorted.end());
        sorted.erase(std::unique(sorted.begin(), sorted.end()), sorted.end());
        for (int vertex : sorted) {
            if (vertex < 0 || vertex >= fullVertexCount) {
                MAnimControl::setCurrentTime(wasAt);
                std::ostringstream stream;
                stream << "Vertex " << vertex << " is not on a mesh with " << fullVertexCount
                       << " vertices.";
                problem = stream.str().c_str();
                return MS::kInvalidParameter;
            }
            positionOf[static_cast<std::size_t>(vertex)] = static_cast<int>(used.size());
            used.push_back(vertex);
        }
    }
    vertexSubset_ = used;

    input.rest.clear();
    for (int vertex : used) {
        const MPoint& point = restPoints[static_cast<unsigned int>(vertex)];
        input.rest.push_back(mca::Vec3(point.x, point.y, point.z));
    }

    // Who is next to whom, for the smoothing prior.
    input.neighbours.assign(used.size(), std::vector<int>());
    {
        MItMeshVertex iterator(mesh);
        for (; !iterator.isDone(); iterator.next()) {
            const int vertex = iterator.index();
            if (vertex < 0 || vertex >= fullVertexCount) {
                continue;
            }
            const int position = positionOf[static_cast<std::size_t>(vertex)];
            if (position < 0) {
                continue;
            }
            MIntArray around;
            iterator.getConnectedVertices(around);
            for (unsigned int index = 0; index < around.length(); ++index) {
                const int other = around[index];
                if (other < 0 || other >= fullVertexCount) {
                    continue;
                }
                const int otherPosition = positionOf[static_cast<std::size_t>(other)];
                if (otherPosition >= 0) {
                    input.neighbours[static_cast<std::size_t>(position)].push_back(otherPosition);
                }
            }
        }
    }

    input.bindInverse.clear();
    for (int joint = 0; joint < jointCount; ++joint) {
        MMatrix world;
        if (!sampleWorldMatrix(joints[static_cast<unsigned int>(joint)], world)) {
            MAnimControl::setCurrentTime(wasAt);
            problem = "Could not evaluate the transform of " +
                      joints[static_cast<unsigned int>(joint)].partialPathName() +
                      " at the rest frame.";
            return MS::kFailure;
        }
        input.bindInverse.push_back(toMat4(world.inverse()));
    }

    // Additive mode: the skin that is already there, read once.
    //
    // Read at the REST frame, deliberately. The weights do not depend on time, and
    // reading them here rather than inside the pose loop means one read instead of one
    // per frame on a 173-pose face.
    ExistingSkin existing;
    if (options_.additive) {
        MAnimControl::setCurrentTime(restAt);
        if (!readExistingSkin(applyToName_, mesh, used, donorNames_, existing, problem)) {
            MAnimControl::setCurrentTime(wasAt);
            return MS::kFailure;
        }
        // A joint cannot both give weight away and receive it. Allowed through, it
        // would be asked to account for a deformation while its own contribution to
        // the baseline is being subtracted from the thing it is fitting, and the answer
        // would be quietly wrong rather than obviously wrong.
        for (unsigned int index = 0; index < existing.influences.length(); ++index) {
            if (!existing.donor[index]) {
                continue;
            }
            for (unsigned int solved = 0; solved < joints.length(); ++solved) {
                if (joints[solved].fullPathName() == existing.influences[index].fullPathName()) {
                    MAnimControl::setCurrentTime(wasAt);
                    problem = existing.influences[index].partialPathName() +
                              " is named both as a donor and as a joint to solve. It has to be "
                              "one or the other.";
                    return MS::kInvalidParameter;
                }
            }
        }
        input.donorWeight = existing.donorTotal;
    }

    input.poses.clear();
    input.jointWorld.clear();
    input.baseline.clear();
    input.donorPoint.clear();
    for (unsigned int frame = 0; frame < frames_.length(); ++frame) {
        MAnimControl::setCurrentTime(MTime(frames_[frame], unit));

        MPointArray points;
        if (!sampleWorldPoints(mesh, points, problem)) {
            MAnimControl::setCurrentTime(wasAt);
            return MS::kFailure;
        }
        if (points.length() != restPoints.length()) {
            MAnimControl::setCurrentTime(wasAt);
            std::ostringstream stream;
            stream << "The mesh has " << points.length() << " vertices on frame "
                   << frames_[frame] << " and " << restPoints.length()
                   << " on the rest frame. Something is changing its topology between "
                      "frames, which a skin cannot follow.";
            problem = stream.str().c_str();
            return MS::kInvalidParameter;
        }
        std::vector<mca::Vec3> pose;
        for (int vertex : used) {
            const MPoint& point = points[static_cast<unsigned int>(vertex)];
            pose.push_back(mca::Vec3(point.x, point.y, point.z));
        }
        input.poses.push_back(pose);

        std::vector<mca::Mat4> perJoint;
        for (int joint = 0; joint < jointCount; ++joint) {
            MMatrix world;
            if (!sampleWorldMatrix(joints[static_cast<unsigned int>(joint)], world)) {
                MAnimControl::setCurrentTime(wasAt);
                std::ostringstream stream;
                stream << "Could not evaluate "
                       << joints[static_cast<unsigned int>(joint)].partialPathName().asChar()
                       << " on frame " << frames_[frame] << ".";
                problem = stream.str().c_str();
                return MS::kFailure;
            }
            perJoint.push_back(toMat4(world));
        }
        input.jointWorld.push_back(perJoint);

        // Additive mode: where the existing skin puts each vertex on this frame, and
        // where the donors alone put it per unit of their weight. Both are computed
        // from the existing weights and the existing influences' matrices - not
        // sampled off a second mesh - so they are exactly what the skinCluster will
        // do, and there is no second copy of the geometry to drift out of step.
        if (options_.additive) {
            std::vector<mca::Mat4> existingSkin(existing.influences.length());
            for (unsigned int index = 0; index < existing.influences.length(); ++index) {
                MMatrix world;
                if (!sampleWorldMatrix(existing.influences[index], world)) {
                    MAnimControl::setCurrentTime(wasAt);
                    problem = "Could not evaluate the existing influence " +
                              existing.influences[index].partialPathName() + ".";
                    return MS::kFailure;
                }
                existingSkin[index] =
                    mca::multiply(existing.bindInverse[index], toMat4(world));
            }

            std::vector<mca::Vec3> baseline;
            std::vector<mca::Vec3> donorPoint;
            baseline.reserve(input.rest.size());
            donorPoint.reserve(input.rest.size());
            for (std::size_t slot = 0; slot < input.rest.size(); ++slot) {
                const mca::Vec3& rest = input.rest[slot];
                mca::Vec3 whole(0.0, 0.0, 0.0);
                mca::Vec3 fromDonors(0.0, 0.0, 0.0);
                for (unsigned int index = 0; index < existing.influences.length(); ++index) {
                    const double weight = existing.weights[slot][index];
                    if (weight == 0.0) {
                        continue;
                    }
                    const mca::Vec3 moved = mca::transformPoint(rest, existingSkin[index]);
                    whole.x += weight * moved.x;
                    whole.y += weight * moved.y;
                    whole.z += weight * moved.z;
                    if (existing.donor[index]) {
                        fromDonors.x += weight * moved.x;
                        fromDonors.y += weight * moved.y;
                        fromDonors.z += weight * moved.z;
                    }
                }
                baseline.push_back(whole);
                const double held = existing.donorTotal[slot];
                if (held > 1e-12) {
                    donorPoint.push_back(mca::Vec3(fromDonors.x / held, fromDonors.y / held,
                                                   fromDonors.z / held));
                } else {
                    // Nothing can be taken here, so this is never read. Kept finite
                    // rather than left as a NaN waiting for somebody to divide by it.
                    donorPoint.push_back(whole);
                }
            }
            input.baseline.push_back(baseline);
            input.donorPoint.push_back(donorPoint);
        }
    }

    // Does the mesh move at all?
    //
    // This is the check that turns the stale-evaluation trap above from a mystery
    // into a sentence. A solve measures its error against the samples it was
    // given, so samples that never move produce a tiny error and a skin that does
    // nothing - reported as success. It cannot detect that from the inside; it can
    // notice that the input it was handed has no deformation in it, which is never
    // what somebody meant.
    double travelled = 0.0;
    for (const std::vector<mca::Vec3>& pose : input.poses) {
        for (std::size_t vertex = 0; vertex < pose.size(); ++vertex) {
            const mca::Vec3& a = input.rest[vertex];
            const mca::Vec3& b = pose[vertex];
            const double dx = a.x - b.x;
            const double dy = a.y - b.y;
            const double dz = a.z - b.z;
            travelled = std::max(travelled, dx * dx + dy * dy + dz * dz);
        }
    }
    if (travelled <= 1e-14) {
        MAnimControl::setCurrentTime(wasAt);
        std::ostringstream stream;
        stream << "\"" << meshName_.asChar() << "\" is identical on every one of those "
               << frames_.length() << " frames, so there is no deformation to fit. Either the "
                  "poses are not driving it, or the frames are wrong.";
        problem = stream.str().c_str();
        return MS::kFailure;
    }

    // An existing skinCluster can say which joints a vertex is allowed, which is
    // both a big speed-up and a way to improve a skin without moving influences
    // around.
    if (candidateSkinName_.length() > 0) {
        MSelectionList list;
        if (!list.add(candidateSkinName_)) {
            MAnimControl::setCurrentTime(wasAt);
            problem = "No skinCluster called \"" + candidateSkinName_ + "\".";
            return MS::kNotFound;
        }
        MObject node;
        list.getDependNode(0, node);
        if (!node.hasFn(MFn::kSkinClusterFilter)) {
            MAnimControl::setCurrentTime(wasAt);
            problem = "\"" + candidateSkinName_ + "\" is not a skinCluster.";
            return MS::kInvalidParameter;
        }
        MFnSkinCluster cluster(node);
        MDagPathArray influences;
        cluster.influenceObjects(influences);

        std::map<std::string, int> ours;
        for (int joint = 0; joint < jointCount; ++joint) {
            ours[joints[static_cast<unsigned int>(joint)].fullPathName().asChar()] = joint;
        }

        input.candidates.assign(used.size(), std::vector<int>());
        for (unsigned int index = 0; index < influences.length(); ++index) {
            const auto found = ours.find(influences[index].fullPathName().asChar());
            if (found == ours.end()) {
                continue;
            }
            MSelectionList affected;
            MDoubleArray weights;
            cluster.getPointsAffectedByInfluence(influences[index], affected, weights);
            for (unsigned int item = 0; item < affected.length(); ++item) {
                MDagPath unused;
                MObject component;
                affected.getDagPath(item, unused, component);
                if (component.isNull()) {
                    continue;
                }
                MIntArray elements;
                MFnSingleIndexedComponent(component).getElements(elements);
                for (unsigned int element = 0; element < elements.length(); ++element) {
                    const int vertex = elements[element];
                    if (vertex < 0 || vertex >= fullVertexCount) {
                        continue;
                    }
                    const int position = positionOf[static_cast<std::size_t>(vertex)];
                    if (position >= 0) {
                        input.candidates[static_cast<std::size_t>(position)].push_back(
                            found->second);
                    }
                }
            }
        }
        // A vertex the old skin does not touch at all gets no restriction rather
        // than no joints, which would leave it stuck at the bind pose.
        int empty = 0;
        for (std::vector<int>& list2 : input.candidates) {
            if (list2.empty()) {
                ++empty;
            }
        }
        if (empty > 0) {
            std::ostringstream stream;
            stream << empty << " vertex(es) have no influence in " << candidateSkinName_.asChar()
                   << ", so they were left unrestricted.";
            MGlobal::displayWarning(stream.str().c_str());
        }
    }

    MAnimControl::setCurrentTime(wasAt);
    return MS::kSuccess;
}

MStatus McaPoseSkinner::applyAdditiveWeights(const mca::PoseSkinResult& result,
                                             MString& problem) {
    MFnSkinCluster cluster(skinCluster_);

    // Every solved joint has to be an influence already. **The command does not add
    // them**, and that is deliberate.
    //
    // It used to, through `skinCluster -edit -addInfluence`, because there is no API call
    // for it. That worked, and then `undoIt` had to take the influences back off - which
    // means running a command from inside undoIt, which Maya does not support: the undo
    // restored the weights and left the added influence behind, so undoing an additive
    // solve gave you a joint bound at whatever weight the renormalise decided. A test
    // caught it.
    //
    // Adding an influence is scene construction, and scene construction belongs in the
    // Python layer where Maya's own undo already handles it. `poseskinner_api.add_to_skin`
    // does it before calling this, inside one undo chunk with everything else.
    // Re-read everything, now that the influence list has changed.
    ExistingSkin existing;
    if (!readExistingSkin(applyToName_, skinnedPath_, vertexSubset_, donorNames_, existing,
                          problem)) {
        return MS::kFailure;
    }
    // Write to the mesh the cluster deforms, which is the duplicate when the poses were
    // sampled off a blendshaped original.
    skinnedPath_ = existing.deformed;

    const unsigned int influenceCount = existing.influences.length();
    std::vector<int> column(jointNames_.length(), -1);
    (void)influenceCount;
    for (unsigned int index = 0; index < jointNames_.length(); ++index) {
        MSelectionList one;
        if (!one.add(jointNames_[index])) {
            continue;
        }
        MDagPath path;
        one.getDagPath(0, path);
        for (unsigned int have = 0; have < influenceCount; ++have) {
            if (existing.influences[have].fullPathName() == path.fullPathName()) {
                column[index] = static_cast<int>(have);
            }
        }
        if (column[index] < 0) {
            problem = "\"" + jointNames_[index] + "\" is not an influence of " + applyToName_ +
                      ". Additive mode adjusts the weights of influences that already exist; add "
                      "it to the skinCluster first (poseskinner_api.add_to_skin does that for "
                      "you).";
            return MS::kInvalidParameter;
        }
    }

    appliedInfluences_.clear();
    std::vector<int> logical(influenceCount, -1);
    for (unsigned int index = 0; index < influenceCount; ++index) {
        MStatus indexStatus;
        const unsigned int found =
            cluster.indexForInfluenceObject(existing.influences[index], &indexStatus);
        logical[index] = indexStatus ? static_cast<int>(found) : static_cast<int>(index);
        appliedInfluences_.append(logical[index]);
    }

    MFnSingleIndexedComponent components;
    MObject component = components.create(MFn::kMeshVertComponent);
    MIntArray elements;
    for (int vertex : vertexSubset_) {
        elements.append(vertex);
    }
    components.addElements(elements);
    skinnedComponent_ = component;

    MDoubleArray weights(static_cast<unsigned int>(vertexSubset_.size()) * influenceCount, 0.0);
    double worstSum = 0.0;
    for (std::size_t slot = 0; slot < vertexSubset_.size(); ++slot) {
        // Start from what is already there, so an influence nobody nominated is
        // carried across bit for bit rather than recomputed.
        std::vector<double> row = existing.weights[slot];

        double taken = 0.0;
        for (std::size_t item = 0;
             item < result.vertexJoints[slot].size(); ++item) {
            taken += result.vertexWeights[slot][item];
        }
        const double held = existing.donorTotal[slot];
        if (taken > held) {
            // The solver caps this, so reaching here means the two disagree. Clamping
            // rather than trusting, because the alternative is a negative weight.
            taken = held;
        }

        if (held > 1e-12 && taken > 0.0) {
            const double keep = 1.0 - taken / held;
            for (unsigned int index = 0; index < influenceCount; ++index) {
                if (existing.donor[index]) {
                    row[index] *= keep;
                }
            }
            for (std::size_t item = 0; item < result.vertexJoints[slot].size(); ++item) {
                const int which = result.vertexJoints[slot][item];
                if (which < 0 || which >= static_cast<int>(column.size())) {
                    continue;
                }
                const int target = column[static_cast<std::size_t>(which)];
                if (target >= 0) {
                    row[static_cast<std::size_t>(target)] +=
                        result.vertexWeights[slot][item];
                }
            }
        }

        double total = 0.0;
        for (unsigned int index = 0; index < influenceCount; ++index) {
            weights[static_cast<unsigned int>(slot) * influenceCount + index] = row[index];
            total += row[index];
        }
        worstSum = std::max(worstSum, std::fabs(total - 1.0));
    }

    // The sum is meant to be exactly one by construction - what the new joints gain,
    // the donors lose. If it is not, something above is wrong and writing it would
    // hand Maya weights it will renormalise into something nobody chose.
    if (worstSum > 1e-9) {
        std::ostringstream stream;
        stream << "Refusing to write: the weights come to " << (1.0 + worstSum)
               << " on at least one vertex rather than 1. Additive mode takes weight out of the "
                  "donors and gives it to the new joints, so the total cannot change - this "
                  "means the bookkeeping is wrong, not the fit.";
        problem = stream.str().c_str();
        return MS::kFailure;
    }

    previousWeights_.clear();
    MStatus status = cluster.setWeights(skinnedPath_, component, appliedInfluences_, weights,
                                       /*normalize=*/false, &previousWeights_);
    if (!status) {
        problem = MString("Could not write weights into ") + applyToName_ + ": " +
                  status.errorString();
        return status;
    }
    appliedWeights_ = true;
    return MS::kSuccess;
}

MStatus McaPoseSkinner::applyWeights(const mca::PoseSkinResult& result, MString& problem) {
    MSelectionList list;
    if (!list.add(applyToName_)) {
        problem = "No skinCluster called \"" + applyToName_ + "\" to write into.";
        return MS::kNotFound;
    }
    MObject node;
    list.getDependNode(0, node);
    if (!node.hasFn(MFn::kSkinClusterFilter)) {
        problem = "\"" + applyToName_ + "\" is not a skinCluster.";
        return MS::kInvalidParameter;
    }
    skinCluster_ = node;

    // Additive mode writes back differently enough to be its own function: it must
    // ADD influences rather than require them, and it must leave every influence the
    // user did not nominate exactly as it found it - which the ordinary path
    // deliberately does not do, because there a vertex's answer is complete and
    // anything unnamed has to go to zero.
    if (options_.additive) {
        return applyAdditiveWeights(result, problem);
    }

    MFnSkinCluster cluster(node);

    // The mesh the skinCluster actually deforms, which is NOT always the mesh that
    // was sampled. The useful case is exactly that: sample a head driven by forty
    // blendshapes, write the weights onto a clean duplicate, and keep both. Taking
    // the sampled mesh's path here instead would write the weights against a
    // vertex list belonging to a different object - same indices, different mesh,
    // no error anywhere.
    MDagPath deformed;
    if (cluster.getPathAtIndex(0, deformed) == MS::kSuccess) {
        MFnMesh sampledMesh(skinnedPath_);
        MFnMesh deformedMesh(deformed);
        if (deformedMesh.numVertices() != sampledMesh.numVertices()) {
            std::ostringstream stream;
            stream << applyToName_.asChar() << " deforms a mesh with "
                   << deformedMesh.numVertices() << " vertices and the solve was run on "
                   << sampledMesh.numVertices()
                   << ". The weights would land on the wrong vertices.";
            problem = stream.str().c_str();
            return MS::kInvalidParameter;
        }
        skinnedPath_ = deformed;
    }
    MDagPathArray influences;
    cluster.influenceObjects(influences);

    // Every influence the skinCluster has, not only the ones solved for. The
    // solve's answer for a vertex is complete, so anything it does not name has
    // to go to zero on that vertex - and a partial write would leave the vertex
    // over-weighted and let Maya renormalise it into something nobody asked for.
    std::map<std::string, int> position;
    for (unsigned int index = 0; index < influences.length(); ++index) {
        position[influences[index].fullPathName().asChar()] = static_cast<int>(index);
    }

    std::vector<int> jointColumn(jointNames_.length(), -1);
    for (unsigned int index = 0; index < jointNames_.length(); ++index) {
        MSelectionList one;
        if (!one.add(jointNames_[index])) {
            continue;
        }
        MDagPath path;
        one.getDagPath(0, path);
        const auto found = position.find(path.fullPathName().asChar());
        if (found == position.end()) {
            problem = "\"" + jointNames_[index] + "\" is not an influence of " + applyToName_ +
                      ". Add it to the skinCluster first, or solve without it.";
            return MS::kInvalidParameter;
        }
        jointColumn[index] = found->second;
    }

    // The LOGICAL index into the skinCluster's matrix array, not the position in
    // the influence list. They agree on a skinCluster nobody has edited, and stop
    // agreeing the moment an influence is removed - at which point weights written
    // by position land on the wrong joints, or setWeights refuses outright.
    appliedInfluences_.clear();
    std::vector<int> logical(influences.length(), -1);
    for (unsigned int index = 0; index < influences.length(); ++index) {
        MStatus indexStatus;
        const unsigned int found =
            cluster.indexForInfluenceObject(influences[index], &indexStatus);
        logical[index] = indexStatus ? static_cast<int>(found) : static_cast<int>(index);
        appliedInfluences_.append(logical[index]);
    }

    MFnSingleIndexedComponent components;
    MObject component = components.create(MFn::kMeshVertComponent);
    MIntArray elements;
    for (int vertex : vertexSubset_) {
        elements.append(vertex);
    }
    components.addElements(elements);
    skinnedComponent_ = component;

    const unsigned int influenceCount = influences.length();
    MDoubleArray weights(static_cast<unsigned int>(vertexSubset_.size()) * influenceCount, 0.0);
    for (std::size_t vertex = 0; vertex < vertexSubset_.size(); ++vertex) {
        const std::vector<int>& joints = result.vertexJoints[vertex];
        const std::vector<double>& values = result.vertexWeights[vertex];
        for (std::size_t slot = 0; slot < joints.size(); ++slot) {
            const int column = jointColumn[static_cast<std::size_t>(joints[slot])];
            if (column < 0) {
                continue;
            }
            // `column` is the position in the influence list, which is also the
            // position in each vertex's block of the weights array - the array is
            // ordered by the influenceIndices argument, not by logical index.
            weights[static_cast<unsigned int>(vertex) * influenceCount +
                    static_cast<unsigned int>(column)] = values[slot];
        }
    }

    previousWeights_.clear();
    MStatus status = cluster.setWeights(skinnedPath_, component, appliedInfluences_, weights,
                                        /*normalize=*/false, &previousWeights_);
    if (!status) {
        // Saying which call failed and what Maya said about it, because "could not
        // write weights" on its own sends the reader looking at the weights.
        std::ostringstream stream;
        stream << "Could not write weights into " << applyToName_.asChar() << ": "
               << status.errorString().asChar() << " (" << vertexSubset_.size()
               << " vertices x " << influenceCount << " influences on "
               << skinnedPath_.partialPathName().asChar() << ").";
        problem = stream.str().c_str();
        return status;
    }
    appliedWeights_ = true;
    return MS::kSuccess;
}

MStatus McaPoseSkinner::doIt(const MArgList& args) {
    MStatus status = gather(args);
    if (!status) {
        return status;
    }
    return redoIt();
}

MStatus McaPoseSkinner::redoIt() {
    mca::PoseSkinInput input;
    MString problem;
    MStatus status = sample(input, problem);
    if (!status) {
        MGlobal::displayError(problem);
        return status;
    }

    // There is nothing to tell Maya about threads here, and that is the point.
    //
    // This used to call MThreadUtils::syncNumOpenMPThreads(), on the strength of
    // the tool this replaces calling it and the devkit once documenting it as what
    // makes a plug-in's OpenMP safe alongside Maya's own pool. It is a no-op. The
    // compiler says so every build:
    //
    //   warning C4996: 'MThreadUtils::syncNumOpenMPThreads': Does nothing.
    //   Present for backward-compatibility purposes only.
    //
    // in 2022, 2024, 2025 and 2026 alike - Maya moved to TBB and left the call as a
    // stub. So it never reconciled anything, and an access violation on a
    // _vcomp_fork worker thread inside this plug-in kept coming back after it was
    // "fixed". The solver no longer uses OpenMP at all: see mca::parallelFor. No
    // VCOMP runtime is loaded into Maya's process, so there is no second thread pool
    // to reconcile.
    //
    // The warning was in the build log the whole time, in four copies. It is worth
    // knowing how easy that is to scroll past.

    // The escape key, wired through to the solver.
    //
    // A face with 173 poses and 80 joints is seconds of work, but a heavier one is
    // minutes, and a solve that cannot be stopped is a Maya that looks hung. The
    // solver only checks between iterations, so whatever comes back is a complete
    // answer rather than a partly-solved mesh.
    // Only in an interactive Maya. A progress bar has nothing to draw on under
    // mayapy, and asking for one there means the headless suites exercise a
    // different code path from the one artists run - which is the sort of
    // difference that is discovered at the worst moment.
    const bool interactive = MGlobal::mayaState() == MGlobal::kInteractive;
    MComputation computation;
    if (interactive) {
        computation.beginComputation(/*showProgressBar=*/true, /*isInterruptable=*/true);
        options_.interrupted = [&computation]() { return computation.isInterruptRequested(); };
    }
    const int total = std::max(1, options_.maxIterations);
    options_.progress = [total](int iteration, double rms) {
        std::ostringstream stream;
        stream.setf(std::ios::fixed);
        stream.precision(4);
        stream << "mcaPoseSkinner: iteration " << iteration << " of " << total << ", rms "
               << rms;
        MGlobal::displayInfo(stream.str().c_str());
    };

    mca::PoseSkinResult result;
    std::string error;
    const bool solved = mca::solvePoseSkin(input, options_, result, error);
    if (interactive) {
        computation.endComputation();
    }
    options_.interrupted = nullptr;
    options_.progress = nullptr;
    if (!solved) {
        MGlobal::displayError(MString("mcaPoseSkinner: ") + error.c_str());
        return MS::kFailure;
    }

    if (applyToName_.length() > 0) {
        MString applyProblem;
        status = applyWeights(result, applyProblem);
        if (!status) {
            MGlobal::displayError(applyProblem);
            return status;
        }
    }

    // ---- the result ---------------------------------------------------------//
    //
    // One flat double array, because a command result cannot carry a structure.
    // The header is fixed width and says how long everything after it is, so the
    // parser in poseskinner_api.py needs no knowledge of the options that were
    // used. The leading version number is there so that adding a section later
    // cannot silently mis-parse in an older script.
    //
    //   [0]  layout version
    //   [1]  rms                 over the poses that were fitted
    //   [2]  worst               over the poses that were fitted
    //   [3]  held-out rms        negative when nothing was held out
    //   [4]  held-out worst
    //   [5]  iterations done
    //   [6]  vertices solved     n
    //   [7]  poses               F
    //   [8]  joints              J
    //   [9]  degenerate joints   d
    //   [10] unweighted vertices u
    //   [11] 1 if per-vertex error follows
    //   [12] 1 if bone matrices follow
    //   [13] 1 if weights were written into a skinCluster
    //   [14] 1 if the solve was stopped early on request
    //   [15] additive mode: vertices scaled back because the donor ran out of weight
    //   then F doubles: rms per pose, in the order the frames were given
    //   then d doubles: joint indices whose transform could not be fitted
    //   then u doubles: mesh vertex ids that came out with nothing on them
    //   then n blocks:  mesh vertex id, influence count, (joint index, weight)...
    //   then n doubles: worst error per vertex, when asked for
    //   then F*J*16:    joint-to-world per pose per joint, row major, when asked
    const int vertexCount = static_cast<int>(result.vertexJoints.size());
    const int poseCount = static_cast<int>(input.poses.size());
    const int jointCount = static_cast<int>(input.bindInverse.size());

    MDoubleArray out;
    out.append(3.0);
    out.append(result.rms);
    out.append(result.worst);
    out.append(result.holdoutRms);
    out.append(result.holdoutWorst);
    out.append(static_cast<double>(result.iterationsDone));
    out.append(static_cast<double>(vertexCount));
    out.append(static_cast<double>(poseCount));
    out.append(static_cast<double>(jointCount));
    out.append(static_cast<double>(result.degenerateJoints.size()));
    out.append(static_cast<double>(result.unweightedVertices.size()));
    out.append(wantVertexError_ ? 1.0 : 0.0);
    out.append(wantBones_ ? 1.0 : 0.0);
    out.append(appliedWeights_ ? 1.0 : 0.0);
    out.append(result.cancelled ? 1.0 : 0.0);
    out.append(static_cast<double>(result.cappedVertices));

    for (int pose = 0; pose < poseCount; ++pose) {
        out.append(result.poseError[static_cast<std::size_t>(pose)]);
    }
    for (int joint : result.degenerateJoints) {
        out.append(static_cast<double>(joint));
    }
    for (int vertex : result.unweightedVertices) {
        out.append(static_cast<double>(vertexSubset_[static_cast<std::size_t>(vertex)]));
    }
    for (int vertex = 0; vertex < vertexCount; ++vertex) {
        const std::vector<int>& joints = result.vertexJoints[static_cast<std::size_t>(vertex)];
        const std::vector<double>& weights =
            result.vertexWeights[static_cast<std::size_t>(vertex)];
        out.append(static_cast<double>(vertexSubset_[static_cast<std::size_t>(vertex)]));
        out.append(static_cast<double>(joints.size()));
        for (std::size_t slot = 0; slot < joints.size(); ++slot) {
            out.append(static_cast<double>(joints[slot]));
            out.append(weights[slot]);
        }
    }
    if (wantVertexError_) {
        for (int vertex = 0; vertex < vertexCount; ++vertex) {
            out.append(result.vertexError[static_cast<std::size_t>(vertex)]);
        }
    }
    if (wantBones_) {
        for (int pose = 0; pose < poseCount; ++pose) {
            for (int joint = 0; joint < jointCount; ++joint) {
                const mca::Mat4& matrix = result.jointWorld[static_cast<std::size_t>(pose)]
                                                           [static_cast<std::size_t>(joint)];
                for (int row = 0; row < 4; ++row) {
                    for (int column = 0; column < 4; ++column) {
                        out.append(matrix.m[row][column]);
                    }
                }
            }
        }
    }

    setResult(out);
    MGlobal::displayInfo(MString("mcaPoseSkinner: ") + result.message.c_str());
    return MS::kSuccess;
}

MStatus McaPoseSkinner::undoIt() {
    if (!appliedWeights_ || skinCluster_.isNull()) {
        return MS::kSuccess;
    }
    MFnSkinCluster cluster(skinCluster_);
    // Weights only. This command never changes the influence LIST - see
    // applyAdditiveWeights for why that is the Python layer's job - so putting the
    // weights back is the whole of the undo.
    return cluster.setWeights(skinnedPath_, skinnedComponent_, appliedInfluences_,
                              previousWeights_, /*normalize=*/false);
}
