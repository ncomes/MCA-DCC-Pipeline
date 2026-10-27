// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_retarget_command.h"

#include <maya/MArgDatabase.h>
#include <maya/MSelectionList.h>
#include <maya/MItSelectionList.h>
#include <maya/MFnMesh.h>
#include <maya/MFnDagNode.h>
#include <maya/MFnTransform.h>
#include <maya/MFnSingleIndexedComponent.h>
#include <maya/MDagPath.h>
#include <maya/MGlobal.h>
#include <maya/MPointArray.h>
#include <maya/MTransformationMatrix.h>

#include <algorithm>
#include <chrono>
#include <string>

const MString McaRetargetShapes::kCommandName("mcaRetargetShapes");

namespace {

const char* kSourceShort = "-s";
const char* kSourceLong = "-source";
const char* kTargetShort = "-t";
const char* kTargetLong = "-target";
const char* kShapeShort = "-sh";
const char* kShapeLong = "-shape";
const char* kSphereShort = "-sp";
const char* kSphereLong = "-sphereAnchors";
const char* kRegularisationShort = "-reg";
const char* kRegularisationLong = "-regularization";
const char* kAffineShort = "-af";
const char* kAffineLong = "-affine";
const char* kMaxShort = "-mx";
const char* kMaxLong = "-maxSolverPoints";

MString note(const std::string& text) {
    return MString("mcaRetargetShapes: ") + text.c_str();
}

/// Find a mesh by name.
MStatus meshByName(const MString& name, MObject& out) {
    MSelectionList list;
    if (!list.add(name)) {
        MGlobal::displayError(note("there is nothing called \"" + std::string(name.asChar()) +
                                   "\" in this scene."));
        return MS::kFailure;
    }
    MDagPath path;
    if (!list.getDagPath(0, path)) {
        MGlobal::displayError(note(std::string(name.asChar()) + " is not a DAG object."));
        return MS::kFailure;
    }
    if (path.hasFn(MFn::kTransform)) {
        path.extendToShape();
    }
    if (!path.hasFn(MFn::kMesh)) {
        MGlobal::displayError(note(std::string(name.asChar()) + " is not a polygon mesh."));
        return MS::kFailure;
    }
    out = path.node();
    return MS::kSuccess;
}

std::vector<mca::Vec3> meshPoints(const MObject& mesh) {
    MFnMesh function(mesh);
    MPointArray points;
    function.getPoints(points, MSpace::kObject);
    std::vector<mca::Vec3> out;
    out.reserve(points.length());
    for (unsigned int i = 0u; i < points.length(); ++i) {
        out.push_back(mca::Vec3(points[i].x, points[i].y, points[i].z));
    }
    return out;
}

/// Do two point sets occupy any of the same space?
///
/// A cheap bounding-box test. Precision is not the point - catching the mesh
/// that went in the wrong field is, and that one is typically metres away.
bool overlapsSource(const std::vector<mca::Vec3>& points,
                    const std::vector<mca::Vec3>& source) {
    if (points.empty() || source.empty()) {
        return true;
    }
    mca::Vec3 lowA = points[0];
    mca::Vec3 highA = points[0];
    for (const mca::Vec3& point : points) {
        lowA.x = std::min(lowA.x, point.x);
        lowA.y = std::min(lowA.y, point.y);
        lowA.z = std::min(lowA.z, point.z);
        highA.x = std::max(highA.x, point.x);
        highA.y = std::max(highA.y, point.y);
        highA.z = std::max(highA.z, point.z);
    }
    mca::Vec3 lowB = source[0];
    mca::Vec3 highB = source[0];
    for (const mca::Vec3& point : source) {
        lowB.x = std::min(lowB.x, point.x);
        lowB.y = std::min(lowB.y, point.y);
        lowB.z = std::min(lowB.z, point.z);
        highB.x = std::max(highB.x, point.x);
        highB.y = std::max(highB.y, point.y);
        highB.z = std::max(highB.z, point.z);
    }
    return !(highA.x < lowB.x || highB.x < lowA.x ||
             highA.y < lowB.y || highB.y < lowA.y ||
             highA.z < lowB.z || highB.z < lowA.z);
}

}  // namespace

void* McaRetargetShapes::creator() {
    return new McaRetargetShapes();
}

MSyntax McaRetargetShapes::newSyntax() {
    MSyntax syntax;
    syntax.addFlag(kSourceShort, kSourceLong, MSyntax::kString);
    syntax.addFlag(kTargetShort, kTargetLong, MSyntax::kString);
    syntax.addFlag(kShapeShort, kShapeLong, MSyntax::kString);
    syntax.makeFlagMultiUse(kShapeShort);
    syntax.addFlag(kSphereShort, kSphereLong, MSyntax::kLong);
    syntax.addFlag(kRegularisationShort, kRegularisationLong, MSyntax::kDouble);
    syntax.addFlag(kAffineShort, kAffineLong, MSyntax::kBoolean);
    syntax.addFlag(kMaxShort, kMaxLong, MSyntax::kLong);

    // Solver vertices come from the selection, which is how they are picked in
    // practice - and avoids a flag carrying thousands of integers.
    syntax.useSelectionAsDefault(true);
    syntax.setObjectType(MSyntax::kSelectionList);
    syntax.enableQuery(false);
    syntax.enableEdit(false);
    return syntax;
}

MStatus McaRetargetShapes::gather(const MArgList& args) {
    MStatus status;
    MArgDatabase database(syntax(), args, &status);
    if (!status) {
        return status;
    }

    if (!database.isFlagSet(kSourceShort) || !database.isFlagSet(kTargetShort)) {
        MGlobal::displayError(note("needs -source and -target."));
        return MS::kFailure;
    }
    database.getFlagArgument(kSourceShort, 0, sourceName_);
    database.getFlagArgument(kTargetShort, 0, targetName_);

    shapeNames_.clear();
    const unsigned int shapeCount = database.numberOfFlagUses(kShapeShort);
    for (unsigned int i = 0u; i < shapeCount; ++i) {
        MArgList shapeArgs;
        if (database.getFlagArgumentList(kShapeShort, i, shapeArgs) == MS::kSuccess) {
            shapeNames_.append(shapeArgs.asString(0));
        }
    }
    if (shapeNames_.length() == 0u) {
        MGlobal::displayError(note("needs at least one -shape to retarget."));
        return MS::kFailure;
    }

    if (database.isFlagSet(kSphereShort)) {
        int value = 0;
        database.getFlagArgument(kSphereShort, 0, value);
        options_.sphereSamples = value;
    }
    if (database.isFlagSet(kRegularisationShort)) {
        double value = 0.0;
        database.getFlagArgument(kRegularisationShort, 0, value);
        options_.regularisation = value;
    }
    if (database.isFlagSet(kAffineShort)) {
        bool value = true;
        database.getFlagArgument(kAffineShort, 0, value);
        options_.affineTerm = value;
    }
    if (database.isFlagSet(kMaxShort)) {
        int value = 0;
        database.getFlagArgument(kMaxShort, 0, value);
        options_.maxSolverPoints = value;
    }

    // Vertices from the selection.
    solverVertices_.clear();
    MSelectionList selection;
    database.getObjects(selection);
    for (MItSelectionList it(selection, MFn::kMeshVertComponent); !it.isDone(); it.next()) {
        MDagPath path;
        MObject component;
        it.getDagPath(path, component);
        if (component.isNull()) {
            continue;
        }
        MFnSingleIndexedComponent indexed(component);
        for (int i = 0; i < indexed.elementCount(); ++i) {
            solverVertices_.push_back(indexed.element(i));
        }
    }

    return MS::kSuccess;
}

MStatus McaRetargetShapes::doIt(const MArgList& args) {
    MStatus status = gather(args);
    if (!status) {
        return status;
    }
    return redoIt();
}

MStatus McaRetargetShapes::redoIt() {
    MObject source;
    MObject target;
    if (!meshByName(sourceName_, source) || !meshByName(targetName_, target)) {
        return MS::kFailure;
    }

    const std::vector<mca::Vec3> sourcePoints = meshPoints(source);
    const std::vector<mca::Vec3> targetPoints = meshPoints(target);

    // Say what is about to be attempted BEFORE attempting it. The tool this
    // replaces printed its point count to std::cout, which on Windows goes to a
    // console nobody has open - so a solve that was about to take ten minutes
    // looked exactly like one that was about to take two seconds.
    const std::size_t requested =
        solverVertices_.empty() ? sourcePoints.size() : solverVertices_.size();
    MGlobal::displayInfo(note("solving on " + std::to_string(requested) + " of " +
                              std::to_string(sourcePoints.size()) + " vertices, for " +
                              std::to_string(shapeNames_.length()) + " shape(s)."));

    const auto started = std::chrono::steady_clock::now();

    mca::RetargetSolver solver;
    std::string error;
    if (!solver.build(sourcePoints, targetPoints, solverVertices_, options_, error)) {
        MGlobal::displayError(note(error));
        return MS::kFailure;
    }

    const auto solved = std::chrono::steady_clock::now();
    const double solveSeconds =
        std::chrono::duration<double>(solved - started).count();

    if (solver.report().degenerate) {
        // Rank deficiency has two causes and the message has to name both,
        // because the second one does not look like a mistake: solver vertices
        // on top of each other, OR solver vertices that all lie on one plane or
        // one line. A flat set cannot describe what happens off the flat, so the
        // affine term's missing direction is solved as zero and shapes come back
        // squashed onto that plane - which reads as a plug-in bug rather than as
        // a point set that was never going to work.
        MGlobal::displayWarning(note(
            "the solver vertices do not span three dimensions - some are in the same "
            "place, or they all lie on one plane or line. The transfer is fitting them "
            "rather than passing through them, and motion off that plane will be lost. "
            "Pick vertices spread through the volume, turn on -sphereAnchors, or raise "
            "-regularization."));
    }

    created_.clear();
    MStringArray names;

    for (unsigned int index = 0u; index < shapeNames_.length(); ++index) {
        MObject shape;
        if (!meshByName(shapeNames_[index], shape)) {
            return MS::kFailure;
        }

        // NO topology requirement on the shape, deliberately.
        //
        // The first version of this refused any shape whose vertex count did not
        // match the source's, reasoning that a blendshape target shares its
        // base's topology. That is right for correctives and wrong for the tool:
        // what is built here is a function of POSITION, so it applies to any mesh
        // sitting in the source's space whatever its topology. The refusal broke
        // the main thing it gets used for - one garment, fitted to a base body,
        // refitted onto each body variant. The tool this replaces had no such
        // check and was right not to.
        //
        // What IS worth saying is when a shape is nowhere near the source, which
        // is the mistake that actually happens. The deformation only means
        // anything where there are solver points, so a mesh outside them comes
        // back extrapolated into nonsense rather than refused.
        std::vector<mca::Vec3> points = meshPoints(shape);
        if (!overlapsSource(points, sourcePoints)) {
            MGlobal::displayWarning(note(
                std::string(shapeNames_[index].asChar()) + " does not overlap " +
                std::string(sourceName_.asChar()) + " at all. This carries meshes that "
                "sit ON the source across to the target - if it is a variant of the "
                "source rather than something worn on it, it belongs in -target."));
        }

        solver.evaluate(points);

        MFnMesh builder;
        MObject transform = builder.copy(shape);

        MPointArray moved;
        moved.setLength(static_cast<unsigned int>(points.size()));
        for (std::size_t i = 0u; i < points.size(); ++i) {
            moved.set(MPoint(points[i].x, points[i].y, points[i].z),
                      static_cast<unsigned int>(i));
        }
        builder.setPoints(moved, MSpace::kObject);

        // Carry the original's local transform across, so the new shape sits
        // where its source did.
        MFnDagNode shapeDag(shape);
        MFnTransform sourceTransform(shapeDag.parent(0));
        MFnTransform newTransform(transform);
        newTransform.set(sourceTransform.transformation());

        // Name it after the shape it came from. MFnMesh::copy hands back
        // "polySurface1", and forty correctives retargeted in one call come back
        // as polySurface1..40 in whatever order the loop ran - which is forty
        // shapes nobody can tell apart, on a tool whose whole job is to produce
        // a named set. Maya makes the name unique if it has to.
        newTransform.setName(sourceTransform.name() + "_retargeted");

        created_.append(transform);
        names.append(MFnDependencyNode(transform).name());
    }

    const double totalSeconds =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();

    MGlobal::displayInfo(note(
        "done in " + std::to_string(totalSeconds).substr(0, 5) + "s (" +
        std::to_string(solveSeconds).substr(0, 5) + "s solving " +
        std::to_string(solver.report().solverPoints) + " points, " +
        std::to_string(static_cast<long long>(solver.report().matrixMegabytes)) +
        " MB matrix)."));

    setResult(names);
    return MS::kSuccess;
}

MStatus McaRetargetShapes::undoIt() {
    MDagModifier modifier;
    for (unsigned int i = 0u; i < created_.length(); ++i) {
        if (!created_[i].isNull()) {
            modifier.deleteNode(created_[i]);
        }
    }
    created_.clear();
    return modifier.doIt();
}
