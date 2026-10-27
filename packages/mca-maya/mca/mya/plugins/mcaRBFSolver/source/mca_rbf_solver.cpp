// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_rbf_solver.h"
#include "mca_node_ids.h"

#include <maya/MFnNumericAttribute.h>
#include <maya/MFnEnumAttribute.h>
#include <maya/MFnCompoundAttribute.h>
#include <maya/MArrayDataHandle.h>
#include <maya/MArrayDataBuilder.h>
#include <maya/MGlobal.h>

#include <algorithm>
#include <cmath>
#include <cstring>

const MString McaRBFSolver::kNodeName("mcaRBFSolver");
const MTypeId McaRBFSolver::kNodeId = mca::nodeId(mca::kRBFSolverNode);

MObject McaRBFSolver::aInput;
MObject McaRBFSolver::aPoses;
MObject McaRBFSolver::aPoseState;
MObject McaRBFSolver::aPoseKey;
MObject McaRBFSolver::aPoseValue;
MObject McaRBFSolver::aOutput;
MObject McaRBFSolver::aDistanceMode;
MObject McaRBFSolver::aKernel;
MObject McaRBFSolver::aScale;
MObject McaRBFSolver::aNormalise;
MObject McaRBFSolver::aRegularisation;
MObject McaRBFSolver::aWeightsSumToOne;
MObject McaRBFSolver::aStatedKeyDimension;
MObject McaRBFSolver::aStatedValueDimension;

namespace {

MString note(const std::string& text) {
    return MString("mcaRBFSolver: ") + text.c_str();
}

void mixHash(std::size_t& hash, std::size_t value) {
    hash ^= value + 0x9e3779b97f4a7c15ull + (hash << 6) + (hash >> 2);
}

void mixHash(std::size_t& hash, double value) {
    // The bit pattern rather than the number, so -0.0 and 0.0 are one key.
    std::size_t bits = 0u;
    static_assert(sizeof(bits) >= sizeof(value), "double must fit in size_t for hashing");
    std::memcpy(&bits, &value, sizeof(value));
    mixHash(hash, bits);
}

/// Read a float array attribute into a dense vector.
///
/// Maya's arrays are sparse - element 0 and element 4 can exist with nothing
/// between - so the logical index decides where a value lands and the gaps are
/// zero. The original walked physical elements and trusted them to line up,
/// wrapped in a bare `except: pass`, so a sparse array silently produced a key
/// with its dimensions in the wrong order.
void readFloatArray(MArrayDataHandle& handle, std::vector<double>& out) {
    out.clear();
    const unsigned int count = handle.elementCount();
    for (unsigned int element = 0u; element < count; ++element) {
        if (handle.jumpToArrayElement(element) != MS::kSuccess) {
            continue;
        }
        const unsigned int index = handle.elementIndex();
        if (out.size() <= index) {
            out.resize(index + 1u, 0.0);
        }
        out[index] = handle.inputValue().asFloat();
    }
}

}  // namespace

void* McaRBFSolver::creator() {
    return new McaRBFSolver();
}

MStatus McaRBFSolver::initialize() {
    MFnNumericAttribute numericAttr;
    MFnEnumAttribute enumAttr;
    MFnCompoundAttribute compoundAttr;
    MStatus status;

    // --- the system ---------------------------------------------------------- //

    aInput = numericAttr.create("nInput", "ni", MFnNumericData::kFloat, 0.0, &status);
    numericAttr.setArray(true);
    numericAttr.setKeyable(true);
    addAttribute(aInput);

    aPoseState = numericAttr.create("state", "st", MFnNumericData::kBoolean, true, &status);
    numericAttr.setKeyable(true);

    aPoseKey = numericAttr.create("nKey", "nk", MFnNumericData::kFloat, 0.0, &status);
    numericAttr.setArray(true);
    numericAttr.setKeyable(true);

    aPoseValue = numericAttr.create("mValue", "mv", MFnNumericData::kFloat, 0.0, &status);
    numericAttr.setArray(true);
    numericAttr.setKeyable(true);

    aPoses = compoundAttr.create("poses", "ps", &status);
    compoundAttr.addChild(aPoseState);
    compoundAttr.addChild(aPoseKey);
    compoundAttr.addChild(aPoseValue);
    compoundAttr.setArray(true);
    addAttribute(aPoses);

    aOutput = numericAttr.create("mOutput", "mo", MFnNumericData::kFloat, 0.0, &status);
    numericAttr.setArray(true);
    numericAttr.setUsesArrayDataBuilder(true);
    numericAttr.setWritable(false);
    numericAttr.setStorable(false);
    addAttribute(aOutput);

    // --- how it interpolates --------------------------------------------------- //

    // In the original, mode 0 was labelled Euclidean and was not - it was the
    // p-norm with p set to the key's dimension, which is right for 1D and 2D and
    // wrong above. Mode 0 is now the real thing, and the old behaviour is mode 2
    // under its own name.
    aDistanceMode = enumAttr.create("distanceMode", "dist", 0, &status);
    enumAttr.addField("Euclidean", 0);
    enumAttr.addField("Angular", 1);
    enumAttr.addField("P-Norm (legacy)", 2);
    enumAttr.setKeyable(true);
    addAttribute(aDistanceMode);

    aKernel = enumAttr.create("rbfMode", "rbf", 1, &status);
    enumAttr.addField("Linear", 0);
    enumAttr.addField("Gaussian", 1);
    enumAttr.addField("Multiquadric", 2);
    enumAttr.addField("Inverse Quadratic", 3);
    enumAttr.addField("Inverse Multiquadric", 4);
    enumAttr.addField("Cubic", 5);
    enumAttr.addField("Thin Plate", 6);
    enumAttr.setKeyable(true);
    addAttribute(aKernel);

    aScale = numericAttr.create("scale", "sc", MFnNumericData::kDouble, 1.0, &status);
    numericAttr.setKeyable(true);
    numericAttr.setSoftMin(0.01);
    numericAttr.setSoftMax(10.0);
    addAttribute(aScale);

    aNormalise = numericAttr.create("normalize", "nz", MFnNumericData::kBoolean, true,
                                    &status);
    numericAttr.setKeyable(true);
    addAttribute(aNormalise);

    aRegularisation = numericAttr.create("regularization", "reg", MFnNumericData::kDouble,
                                         0.0, &status);
    numericAttr.setKeyable(true);
    numericAttr.setMin(0.0);
    numericAttr.setSoftMax(0.1);
    addAttribute(aRegularisation);

    aWeightsSumToOne = numericAttr.create("blendShapeMode", "bsm", MFnNumericData::kBoolean,
                                          false, &status);
    numericAttr.setKeyable(true);
    addAttribute(aWeightsSumToOne);

    // --- read, not trusted ------------------------------------------------------ //

    aStatedKeyDimension = numericAttr.create("NDimension", "nd", MFnNumericData::kInt, 1,
                                             &status);
    numericAttr.setKeyable(false);
    addAttribute(aStatedKeyDimension);

    aStatedValueDimension = numericAttr.create("MDimension", "md", MFnNumericData::kInt, 1,
                                               &status);
    numericAttr.setKeyable(false);
    addAttribute(aStatedValueDimension);

    // --- wiring ------------------------------------------------------------------ //
    //
    // No hidden `solved` boolean. The original carried one purely as a manual
    // dirty flag, with data.isClean() on it deciding whether to refactorise -
    // working around the DG rather than using it. Here the rebuild is keyed on a
    // hash of what was actually read.
    const MObject inputs[] = {aInput,     aPoses,          aPoseState,
                              aPoseKey,   aPoseValue,      aDistanceMode,
                              aKernel,    aScale,          aNormalise,
                              aRegularisation, aWeightsSumToOne};
    for (const MObject& input : inputs) {
        status = attributeAffects(input, aOutput);
        if (!status) {
            return status;
        }
    }

    return MS::kSuccess;
}

MStatus McaRBFSolver::rebuild(MDataBlock& data) {
    MStatus status;

    mca::RbfSetup setup;
    setup.distance = static_cast<mca::Distance>(
        std::max(0, std::min(2, static_cast<int>(data.inputValue(aDistanceMode).asShort()))));
    setup.kernel = static_cast<mca::Kernel>(
        std::max(0, std::min(6, static_cast<int>(data.inputValue(aKernel).asShort()))));
    setup.scale = data.inputValue(aScale).asDouble();
    setup.normalise = data.inputValue(aNormalise).asBool();
    setup.regularisation = std::max(0.0, data.inputValue(aRegularisation).asDouble());

    std::vector<std::vector<double>> keys;
    std::vector<std::vector<double>> values;

    MArrayDataHandle posesHandle = data.inputArrayValue(aPoses, &status);
    const unsigned int poseCount = posesHandle.elementCount();
    for (unsigned int element = 0u; element < poseCount; ++element) {
        if (posesHandle.jumpToArrayElement(element) != MS::kSuccess) {
            continue;
        }
        MDataHandle pose = posesHandle.inputValue();
        if (!pose.child(aPoseState).asBool()) {
            continue;
        }

        MArrayDataHandle keyHandle(pose.child(aPoseKey), &status);
        MArrayDataHandle valueHandle(pose.child(aPoseValue), &status);

        std::vector<double> key;
        std::vector<double> value;
        readFloatArray(keyHandle, key);
        readFloatArray(valueHandle, value);
        if (key.empty() || value.empty()) {
            continue;
        }
        keys.push_back(std::move(key));
        values.push_back(std::move(value));
    }

    // Everything the solve depends on goes in the key, so moving one pose
    // rebuilds and moving the input does not.
    std::size_t hash = 0u;
    mixHash(hash, static_cast<std::size_t>(setup.distance));
    mixHash(hash, static_cast<std::size_t>(setup.kernel));
    mixHash(hash, setup.scale);
    mixHash(hash, static_cast<std::size_t>(setup.normalise ? 1u : 0u));
    mixHash(hash, setup.regularisation);
    mixHash(hash, keys.size());
    for (std::size_t i = 0u; i < keys.size(); ++i) {
        mixHash(hash, keys[i].size());
        for (double component : keys[i]) {
            mixHash(hash, component);
        }
        mixHash(hash, values[i].size());
        for (double component : values[i]) {
            mixHash(hash, component);
        }
    }

    if (hash == systemKey_ && solver_.valid()) {
        return MS::kSuccess;
    }
    systemKey_ = hash;

    if (keys.empty()) {
        solver_.clear();
        if (!reported_) {
            MGlobal::displayWarning(note("no poses are enabled, so there is nothing to "
                                         "interpolate between."));
            reported_ = true;
        }
        return MS::kFailure;
    }

    std::string error;
    if (!solver_.build(keys, values, setup, error)) {
        if (!reported_) {
            MGlobal::displayWarning(note(error));
            reported_ = true;
        }
        return MS::kFailure;
    }
    reported_ = false;

    // The dimensions the rig author typed in. They are not used for anything -
    // the data decides - but disagreeing with the data almost always means a
    // pose was built wrong, so it is worth saying once.
    const int statedKey = data.inputValue(aStatedKeyDimension).asInt();
    const int statedValue = data.inputValue(aStatedValueDimension).asInt();
    if (statedKey > 1 && statedKey != solver_.keyDimension()) {
        MGlobal::displayWarning(note("NDimension says " + std::to_string(statedKey) +
                                     " but the poses carry " +
                                     std::to_string(solver_.keyDimension()) +
                                     "; going with the poses."));
    }
    if (statedValue > 1 && statedValue != solver_.valueDimension()) {
        MGlobal::displayWarning(note("MDimension says " + std::to_string(statedValue) +
                                     " but the poses carry " +
                                     std::to_string(solver_.valueDimension()) +
                                     "; going with the poses."));
    }

    if (solver_.degenerate()) {
        MGlobal::displayWarning(note(
            "two or more poses have keys this solver cannot tell apart, so it is fitting "
            "them rather than passing through them. Move the duplicates apart, or raise "
            "regularization."));
    }

    return MS::kSuccess;
}

MStatus McaRBFSolver::compute(const MPlug& plug, MDataBlock& data) {
    if (plug != aOutput && plug.parent() != aOutput) {
        return MS::kUnknownParameter;
    }

    MStatus status;
    if (!rebuild(data)) {
        return MS::kFailure;
    }

    MArrayDataHandle inputHandle = data.inputArrayValue(aInput, &status);
    std::vector<double> input;
    readFloatArray(inputHandle, input);

    // A key that is shorter than the poses is padded rather than refused: a rig
    // being built up one connection at a time should keep evaluating.
    input.resize(static_cast<std::size_t>(solver_.keyDimension()), 0.0);

    std::vector<double> outputs;
    if (!solver_.evaluate(input, outputs)) {
        return MS::kFailure;
    }

    if (data.inputValue(aWeightsSumToOne).asBool() && !outputs.empty()) {
        // Make the outputs a set of weights: nothing negative, adding to one.
        //
        // The original did this by subtracting the smallest output from all of
        // them and rescaling, which lets one very negative output shift every
        // other weight - and divided by zero outright when that smallest value
        // was 1.0, or when the outputs summed to nothing.
        double total = 0.0;
        for (double& value : outputs) {
            value = std::max(0.0, value);
            total += value;
        }
        if (total > 1e-12) {
            for (double& value : outputs) {
                value /= total;
            }
        }
        // A total of zero means every output was zero or negative. There is no
        // meaningful set of weights to give, so the zeros stand rather than
        // being turned into an arbitrary even split.
    }

    MArrayDataHandle outputHandle = data.outputArrayValue(aOutput, &status);
    MArrayDataBuilder builder = outputHandle.builder(&status);
    for (std::size_t m = 0u; m < outputs.size(); ++m) {
        MDataHandle element = builder.addElement(static_cast<unsigned int>(m), &status);
        element.setFloat(static_cast<float>(outputs[m]));
    }
    outputHandle.set(builder);
    outputHandle.setAllClean();

    data.setClean(plug);
    return MS::kSuccess;
}
