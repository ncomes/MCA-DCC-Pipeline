// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include <algorithm>
#include <cmath>
#include "mca_physics_chain.h"
#include "mca_node_ids.h"
#include "mca_solver.h"

#include <maya/MFnNumericAttribute.h>
#include <maya/MFnUnitAttribute.h>
#include <maya/MFnEnumAttribute.h>
#include <maya/MFnMatrixAttribute.h>
#include <maya/MFnCompoundAttribute.h>
#include <maya/MRampAttribute.h>
#include <maya/MArrayDataHandle.h>
#include <maya/MArrayDataBuilder.h>
#include <maya/MDataHandle.h>
#include <maya/MMatrix.h>
#include <maya/MTime.h>
#include <maya/MAngle.h>
#include <maya/MObjectArray.h>
#include <maya/MGlobal.h>
#include <maya/MTimeRange.h>   // also declares MClosedTimeInterval

#include <cstdlib>
#include <string>
#include <fstream>
#include <mutex>
#include <sstream>
#include <vector>

const MString McaPhysicsChain::kNodeName("mcaPhysicsChain");
const MTypeId McaPhysicsChain::kNodeId = mca::nodeId(mca::kPhysicsChainNode);

MObject McaPhysicsChain::aInTime;
MObject McaPhysicsChain::aStartTime;
MObject McaPhysicsChain::aEnabled;
MObject McaPhysicsChain::aInLevels;
MObject McaPhysicsChain::aGoalMatrix;
MObject McaPhysicsChain::aOutLevels;
MObject McaPhysicsChain::aOutTranslate;
MObject McaPhysicsChain::aOutRotate;
MObject McaPhysicsChain::aOutRotateX;
MObject McaPhysicsChain::aOutRotateY;
MObject McaPhysicsChain::aOutRotateZ;
MObject McaPhysicsChain::aOutMatrix;
MObject McaPhysicsChain::aMass;
MObject McaPhysicsChain::aStiffness;
MObject McaPhysicsChain::aDamping;
MObject McaPhysicsChain::aGravity;
MObject McaPhysicsChain::aGravityDirection;
MObject McaPhysicsChain::aSolveMode;
MObject McaPhysicsChain::aUpdateMode;
MObject McaPhysicsChain::aAimAxis;
MObject McaPhysicsChain::aUpAxis;
MObject McaPhysicsChain::aAimWeight;
MObject McaPhysicsChain::aUpWeight;
MObject McaPhysicsChain::aLimitAngle;
MObject McaPhysicsChain::aStretch;
MObject McaPhysicsChain::aAdvanced;
MObject McaPhysicsChain::aAmount;
MObject McaPhysicsChain::aSpringiness;
MObject McaPhysicsChain::aDroop;
MObject McaPhysicsChain::aUseStiffnessRamp;
MObject McaPhysicsChain::aStiffnessRamp;
MObject McaPhysicsChain::aUseDampingRamp;
MObject McaPhysicsChain::aDampingRamp;
MObject McaPhysicsChain::aUseMassRamp;
MObject McaPhysicsChain::aMassRamp;
MObject McaPhysicsChain::aUseGravityRamp;
MObject McaPhysicsChain::aGravityRamp;
MObject McaPhysicsChain::aUseAimWeightRamp;
MObject McaPhysicsChain::aAimWeightRamp;
MObject McaPhysicsChain::aStatePosition;
MObject McaPhysicsChain::aStateVelocity;
namespace {

/// Where to write a per-compute trace, or empty for the usual silence.
///
/// Cached Playback is opaque from the outside: the values a script reads back
/// come from the CACHE, so a frozen reading cannot tell you whether compute()
/// ran with a stale time or never ran at all - and those two want opposite
/// fixes. The only way to know is to have the node say so from inside.
///
/// Read once. Off by default, so a shipped build costs nothing.
/// std::getenv without MSVC's deprecation warning, and portable.
///
/// MSVC flags getenv (C4996) because the pointer it hands back can be
/// invalidated by a later putenv on another thread. Copying into a string at
/// first use closes that window, and the #else keeps this building on a
/// platform that is not Windows - which is the whole point of having taken
/// windows.h out of this project.
std::string environmentValue(const char* name) {
#ifdef _MSC_VER
    char* buffer = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&buffer, &size, name) != 0 || buffer == nullptr) {
        return std::string();
    }
    std::string value(buffer);
    std::free(buffer);
    return value;
#else
    const char* value = std::getenv(name);
    return value ? std::string(value) : std::string();
#endif
}

const std::string& traceFile() {
    static const std::string path = environmentValue("MCA_PHYSICS_CHAIN_TRACE");
    return path;
}

/// Append one line to the trace. Serialised: parallel evaluation means several
/// nodes can be in compute() at once, and interleaved half-lines would be
/// useless.
void trace(const std::string& line) {
    const std::string& path = traceFile();
    if (path.empty()) {
        return;
    }
    static std::mutex guard;
    std::lock_guard<std::mutex> hold(guard);
    std::ofstream file(path.c_str(), std::ios::app);
    if (file) {
        file << line << std::endl;
    }
}

}  // namespace

MObject McaPhysicsChain::aStateTime;
MObject McaPhysicsChain::aStateInitialised;

void* McaPhysicsChain::creator() { return new McaPhysicsChain(); }

namespace {

mca::Vec3 toVec3(const double3& d) { return mca::Vec3(d[0], d[1], d[2]); }

mca::Vec3 translationOf(const MMatrix& m) { return mca::Vec3(m[3][0], m[3][1], m[3][2]); }

/// The axis index and sign an enum value stands for. 0..5 is +x -x +y -y +z -z.
void decodeAxis(short value, int& axis, double& sign) {
    axis = value / 2;
    sign = (value % 2) == 0 ? 1.0 : -1.0;
}

/// A ramp value at a position along the chain, or the flat value when the ramp
/// is switched off.
///
/// Ramps are the whole reason a chain looks like hair rather than like a row of
/// identical springs: stiffness that falls off toward the tip is what makes the
/// end trail. Sampling is guarded because an empty ramp returns nothing useful
/// and a zero stiffness would pin a level solid.
double rampedValue(const MObject& node, const MObject& rampAttr, bool useRamp, double flat,
                   double position) {
    if (!useRamp) {
        return flat;
    }
    MStatus status;
    MRampAttribute ramp(node, rampAttr, &status);
    if (!status || ramp.getNumEntries() == 0) {
        return flat;
    }
    float sampled = 1.0f;
    ramp.getValueAtPosition(static_cast<float>(position), sampled, &status);
    if (!status) {
        return flat;
    }
    return flat * static_cast<double>(sampled);
}

/// A basis from a matrix's upper 3x3.
mca::Basis basisOf(const MMatrix& m) {
    mca::Basis basis;
    basis.x = mca::normalized(mca::Vec3(m[0][0], m[0][1], m[0][2]));
    basis.y = mca::normalized(mca::Vec3(m[1][0], m[1][1], m[1][2]));
    basis.z = mca::normalized(mca::Vec3(m[2][0], m[2][1], m[2][2]));
    return basis;
}

MMatrix matrixOf(const mca::Basis& basis, const mca::Vec3& position) {
    double values[4][4] = {{basis.x.x, basis.x.y, basis.x.z, 0.0},
                           {basis.y.x, basis.y.y, basis.y.z, 0.0},
                           {basis.z.x, basis.z.y, basis.z.z, 0.0},
                           {position.x, position.y, position.z, 1.0}};
    return MMatrix(values);
}

}  // namespace

MStatus McaPhysicsChain::initialize() {
    MStatus status;
    MFnNumericAttribute nAttr;
    MFnUnitAttribute uAttr;
    MFnEnumAttribute eAttr;
    MFnMatrixAttribute mAttr;
    MFnCompoundAttribute cAttr;

    // --- time and gate ------------------------------------------------------ //

    aInTime = uAttr.create("inTime", "itm", MFnUnitAttribute::kTime, 0.0, &status);
    uAttr.setStorable(true);
    uAttr.setKeyable(true);
    addAttribute(aInTime);

    aStartTime = uAttr.create("startTime", "stm", MFnUnitAttribute::kTime, 1.0, &status);
    uAttr.setStorable(true);
    uAttr.setKeyable(true);
    addAttribute(aStartTime);

    aEnabled = nAttr.create("enabled", "enb", MFnNumericData::kBoolean, 1, &status);
    nAttr.setKeyable(true);
    addAttribute(aEnabled);

    // --- the chain ---------------------------------------------------------- //

    aGoalMatrix = mAttr.create("goalMatrix", "gm", MFnMatrixAttribute::kDouble, &status);
    mAttr.setStorable(true);

    aInLevels = cAttr.create("inLevels", "ilv", &status);
    cAttr.addChild(aGoalMatrix);
    cAttr.setArray(true);
    cAttr.setStorable(true);
    addAttribute(aInLevels);

    // --- outputs -------------------------------------------------------------- //

    aOutTranslate = nAttr.create("outTranslate", "ot", MFnNumericData::k3Double, 0.0, &status);
    nAttr.setWritable(false);
    nAttr.setStorable(false);

    aOutRotateX = uAttr.create("outRotateX", "orx", MFnUnitAttribute::kAngle, 0.0, &status);
    aOutRotateY = uAttr.create("outRotateY", "ory", MFnUnitAttribute::kAngle, 0.0, &status);
    aOutRotateZ = uAttr.create("outRotateZ", "orz", MFnUnitAttribute::kAngle, 0.0, &status);
    aOutRotate = nAttr.create("outRotate", "or", aOutRotateX, aOutRotateY, aOutRotateZ, &status);
    nAttr.setWritable(false);
    nAttr.setStorable(false);

    aOutMatrix = mAttr.create("outMatrix", "om", MFnMatrixAttribute::kDouble, &status);
    mAttr.setWritable(false);
    mAttr.setStorable(false);

    aOutLevels = cAttr.create("outLevels", "olv", &status);
    cAttr.addChild(aOutTranslate);
    cAttr.addChild(aOutRotate);
    cAttr.addChild(aOutMatrix);
    cAttr.setArray(true);
    cAttr.setWritable(false);
    cAttr.setStorable(false);
    cAttr.setUsesArrayDataBuilder(true);
    addAttribute(aOutLevels);

    // --- solver parameters ------------------------------------------------------ //

    aMass = nAttr.create("mass", "ma", MFnNumericData::kDouble, 1.0, &status);
    nAttr.setKeyable(true);
    nAttr.setMin(0.0);
    addAttribute(aMass);

    // 0.5, not 10. dt here is measured in FRAMES, so stiffness is a per-frame
    // rate and the useful range is far lower than it looks. Against a goal that
    // snaps 10 units with damping 0.3: 0.05 settles around frame 78, 0.5 around
    // 25, 2.0 around 13, 8.0 around 7. A default of 10 gave a chain that barely
    // lagged, which reads as "broken" rather than "stiff".
    aStiffness = nAttr.create("stiffness", "stf", MFnNumericData::kDouble, 0.5, &status);
    nAttr.setKeyable(true);
    nAttr.setMin(0.0);
    nAttr.setSoftMax(5.0);
    addAttribute(aStiffness);

    // A ratio of critical damping, not a raw coefficient: 1.0 returns to the
    // goal without overshooting, and the number keeps its meaning when mass or
    // stiffness change.
    aDamping = nAttr.create("damping", "dmp", MFnNumericData::kDouble, 0.3, &status);
    nAttr.setKeyable(true);
    nAttr.setMin(0.0);
    nAttr.setSoftMax(2.0);
    addAttribute(aDamping);

    aGravity = nAttr.create("gravity", "grv", MFnNumericData::kDouble, 0.0, &status);
    nAttr.setKeyable(true);
    addAttribute(aGravity);

    aGravityDirection = nAttr.create("gravityDirection", "gvd", MFnNumericData::k3Double, 0.0,
                                     &status);
    nAttr.setDefault(0.0, -1.0, 0.0);
    nAttr.setKeyable(true);
    addAttribute(aGravityDirection);

    aSolveMode = eAttr.create("solveMode", "svm", 0, &status);
    eAttr.addField("perAxis", 0);
    eAttr.addField("vector", 1);
    addAttribute(aSolveMode);

    aUpdateMode = eAttr.create("updateMode", "upm", 0, &status);
    eAttr.addField("velocity", 0);
    eAttr.addField("acceleration", 1);
    addAttribute(aUpdateMode);

    // --- orientation ------------------------------------------------------------- //

    const char* axisNames[] = {"+x", "-x", "+y", "-y", "+z", "-z"};
    aAimAxis = eAttr.create("aimAxis", "aim", 0, &status);
    for (short i = 0; i < 6; ++i) {
        eAttr.addField(axisNames[i], i);
    }
    addAttribute(aAimAxis);

    aUpAxis = eAttr.create("upAxis", "upa", 2, &status);
    for (short i = 0; i < 6; ++i) {
        eAttr.addField(axisNames[i], i);
    }
    addAttribute(aUpAxis);

    aAimWeight = nAttr.create("aimWeight", "awt", MFnNumericData::kDouble, 1.0, &status);
    nAttr.setKeyable(true);
    nAttr.setMin(0.0);
    nAttr.setMax(1.0);
    addAttribute(aAimWeight);

    aUpWeight = nAttr.create("upWeight", "uwt", MFnNumericData::kDouble, 1.0, &status);
    nAttr.setKeyable(true);
    nAttr.setMin(0.0);
    nAttr.setMax(1.0);
    addAttribute(aUpWeight);

    // --- limits -------------------------------------------------------------------- //

    aLimitAngle = nAttr.create("limitAngle", "lim", MFnNumericData::kDouble, 180.0, &status);
    nAttr.setKeyable(true);
    nAttr.setMin(0.0);
    nAttr.setMax(180.0);
    addAttribute(aLimitAngle);

    // Every level is solved as a free particle chasing its own goal, so nothing
    // stops two of them drifting closer together or further apart - the chain
    // quietly stretches. Measured on a nine level pony tail, individual segments
    // were out by up to 8.8% while the total length happened to come out right,
    // so it reads as a subtle squash travelling down the chain rather than as
    // anything obviously broken.
    //
    // It also makes the result unbakeable. Flags rotate but do not translate, so
    // a baked chain is rigid by construction and cannot reproduce a stretched
    // one; the error compounds from parent to child and lands on the tip.
    //
    // Default 0: hold the lengths. 1 is the old free behaviour, kept because a
    // squashing chain is a legitimate cartoon look.
    aStretch = nAttr.create("stretch", "str", MFnNumericData::kDouble, 0.0, &status);
    nAttr.setKeyable(true);
    nAttr.setMin(0.0);
    nAttr.setMax(1.0);
    addAttribute(aStretch);

    // --- the animator-facing three -------------------------------------------- //

    aAdvanced = nAttr.create("advanced", "adv", MFnNumericData::kBoolean, 0, &status);
    nAttr.setKeyable(false);
    addAttribute(aAdvanced);

    // stiffness = 8 * 256^-amount. Geometric, so every 0.125 of Amount halves
    // the stiffness, and the ends are useful rather than degenerate: 0 gives 8
    // (tracks tightly, ~6 units of lag on a 90 unit swing) and 1 gives 0.031
    // (hangs almost free). 0.5 lands exactly on 0.5, the old default.
    aAmount = nAttr.create("amount", "amt", MFnNumericData::kDouble, 0.5, &status);
    nAttr.setKeyable(true);
    nAttr.setMin(0.0);
    nAttr.setMax(1.0);
    addAttribute(aAmount);

    // damping = 1 - 0.6 * springiness, so the range is 1.0 down to 0.4 and the
    // control is monotonic in overshoot: 0 is critically damped and never
    // crosses the pose, 1 carries about 30% past it. The floor of 0.4 is
    // deliberate - below it a chain can take 80 frames to settle, or never.
    aSpringiness = nAttr.create("springiness", "spg", MFnNumericData::kDouble, 0.5, &status);
    nAttr.setKeyable(true);
    nAttr.setMin(0.0);
    nAttr.setMax(1.0);
    addAttribute(aSpringiness);

    // Raw gravity is an acceleration in units per FRAME squared, so its useful
    // range is about 0 to 0.1 and its effect scales with 1/stiffness - change
    // Amount and the hang changes with it. Droop is scaled by segment length
    // and stiffness so that it settles a level about droop * its own length off
    // the pose, whatever else is set. 1 is a strong hang.
    aDroop = nAttr.create("droop", "drp", MFnNumericData::kDouble, 0.0, &status);
    nAttr.setKeyable(true);
    nAttr.setMin(0.0);
    nAttr.setMax(1.0);
    addAttribute(aDroop);

    // --- ramps ---------------------------------------------------------------------- //
    //
    // A ramp multiplies its parameter along the chain, 0 at the root and 1 at
    // the tip. Multiplying rather than replacing means the flat value stays
    // meaningful and the ramp is a shape, not a second set of units.

    struct RampSpec {
        MObject* toggle;
        MObject* ramp;
        const char* toggleLong;
        const char* toggleShort;
        const char* rampLong;
        const char* rampShort;
    };
    const RampSpec ramps[] = {
        {&aUseStiffnessRamp, &aStiffnessRamp, "useStiffnessRamp", "usr", "stiffnessRamp", "sfr"},
        {&aUseDampingRamp, &aDampingRamp, "useDampingRamp", "udr", "dampingRamp", "dpr"},
        {&aUseMassRamp, &aMassRamp, "useMassRamp", "umr", "massRamp", "mar"},
        {&aUseGravityRamp, &aGravityRamp, "useGravityRamp", "ugr", "gravityRamp", "gvr"},
        {&aUseAimWeightRamp, &aAimWeightRamp, "useAimWeightRamp", "uar", "aimWeightRamp", "awr"},
    };
    for (const RampSpec& spec : ramps) {
        *spec.toggle = nAttr.create(spec.toggleLong, spec.toggleShort, MFnNumericData::kBoolean,
                                    0, &status);
        nAttr.setKeyable(false);
        addAttribute(*spec.toggle);

        *spec.ramp = MRampAttribute::createCurveRamp(spec.rampLong, spec.rampShort, &status);
        addAttribute(*spec.ramp);
    }

    // --- state ------------------------------------------------------------------------ //
    //
    // Outputs, not inputs: produced here, saved with the scene so a simulation
    // survives a reload, and visible to Cached Playback. Declaring them as
    // inputs that affect the outputs would make the node depend on its own
    // result, which is a cycle - and a cycle through a plug-in node takes Maya
    // down rather than warning.

    aStatePosition = nAttr.create("statePosition", "spo", MFnNumericData::k3Double, 0.0, &status);
    nAttr.setArray(true);
    nAttr.setUsesArrayDataBuilder(true);
    nAttr.setStorable(true);
    nAttr.setWritable(false);
    nAttr.setHidden(true);
    addAttribute(aStatePosition);

    aStateVelocity = nAttr.create("stateVelocity", "sve", MFnNumericData::k3Double, 0.0, &status);
    nAttr.setArray(true);
    nAttr.setUsesArrayDataBuilder(true);
    nAttr.setStorable(true);
    nAttr.setWritable(false);
    nAttr.setHidden(true);
    addAttribute(aStateVelocity);

    aStateTime = uAttr.create("stateTime", "stt", MFnUnitAttribute::kTime, 0.0, &status);
    uAttr.setStorable(true);
    uAttr.setWritable(false);
    uAttr.setHidden(true);
    addAttribute(aStateTime);

    aStateInitialised = nAttr.create("stateInitialised", "sin", MFnNumericData::kBoolean,
                                     false, &status);
    nAttr.setStorable(true);
    nAttr.setWritable(false);
    nAttr.setHidden(true);
    addAttribute(aStateInitialised);

    // --- wiring ------------------------------------------------------------------------ //

    const MObject inputs[] = {aInTime,     aStartTime,   aEnabled,    aInLevels,
                              aGoalMatrix, aMass,        aStiffness,  aDamping,
                              aGravity,    aGravityDirection,          aSolveMode,
                              aUpdateMode, aAimAxis,     aUpAxis,     aAimWeight,
                              aUpWeight,   aLimitAngle,  aStretch,    aAdvanced,
                              aAmount,     aSpringiness, aDroop,      aUseStiffnessRamp,
                              aStiffnessRamp,
                              aUseDampingRamp, aDampingRamp, aUseMassRamp, aMassRamp,
                              aUseGravityRamp, aGravityRamp, aUseAimWeightRamp, aAimWeightRamp};
    const MObject outputs[] = {aOutLevels, aOutTranslate, aOutRotate, aOutMatrix,
                               aStatePosition, aStateVelocity, aStateTime,
                               aStateInitialised};
    for (const MObject& input : inputs) {
        for (const MObject& output : outputs) {
            status = attributeAffects(input, output);
            if (!status) {
                return status;
            }
        }
    }
    return MS::kSuccess;
}

void McaPhysicsChain::getCacheSetup(const MEvaluationNode& evalNode,
                                    MNodeCacheDisablingInfo& disablingInfo,
                                    MNodeCacheSetupInfo& cacheSetupInfo,
                                    MObjectArray& monitoredAttributes) const {
    MPxNode::getCacheSetup(evalNode, disablingInfo, cacheSetupInfo, monitoredAttributes);

    // Ask to be cached at all.
    //
    // Without this the node never becomes a caching point, configCache() is
    // never consulted, the state plugs are never kept, and the solver restarts
    // from rest on every frame.
    cacheSetupInfo.setPreference(MNodeCacheSetupInfo::kWantToCacheByDefault, true);

    // --- kSimulationSupport is deliberately NOT set -------------------------- //
    //
    // This looks exactly wrong. The node IS a simulation, the flag IS named for
    // simulations, Maya honours it (dynamicsSupportActive reports true), and
    // setting it is the obvious thing to do. It is also what broke Cached
    // Playback completely for this node, and finding that out took a trace
    // written from inside compute().
    //
    // With the flag set, on a four-level chain whose tip travels 3.496717:
    //
    //     compute() calls while the cache filled   0
    //     compute() calls over a full forward play 0
    //     frames in the cache                      1, spanning 1-60
    //     cached result vs the truth               3.022768
    //     Maya's own safeModeMessages              (empty)
    //
    // Zero. The node is never evaluated at all: Maya stores one frame, decides
    // it covers the whole range, and serves it forever while the goals move
    // underneath. No error, no warning, no complaint from Maya - just hair that
    // stopped working. Whatever protocol kSimulationSupport signs this node up
    // to ("handling restart time and the such", per the header), it is one this
    // node does not implement, and the cost of not implementing it is total.
    //
    // Without the flag, the same chain:
    //
    //     compute() calls while the cache filled   60
    //     cached result vs the truth               0.0
    //
    // Exact. The trace shows clean sequential evaluation, inTime 1..60 with
    // dt=1 at every step and the state carried forward, which is precisely the
    // behaviour the flag was supposed to guarantee.
    //
    // What the flag was actually protecting against is real, and is handled
    // instead by transformInvalidationRange() below - see the measurement there.
    //
    // MCA_PHYSICS_CHAIN_SIM_SUPPORT puts the flag back for anyone who wants to
    // revisit this against a future Maya. It is expected to freeze the chain.
    if (!environmentValue("MCA_PHYSICS_CHAIN_SIM_SUPPORT").empty()) {
        cacheSetupInfo.setRequirement(MNodeCacheSetupInfo::kSimulationSupport, true);
        disablingInfo.setCacheDisabled(true);
        disablingInfo.setReason("MCA_PHYSICS_CHAIN_SIM_SUPPORT is set, which is known to "
                                "freeze this node under Cached Playback.");
        disablingInfo.setMitigation("Unset MCA_PHYSICS_CHAIN_SIM_SUPPORT.");
    }
}

void McaPhysicsChain::configCache(const MEvaluationNode& evalNode,
                                  MCacheSchema& schema) const {
    MPxNode::configCache(evalNode, schema);
    // The three plugs that carry the simulation from one frame to the next. They
    // are attributes rather than members precisely so Maya can see them - but
    // being visible is not the same as being kept. Without these three lines the
    // cache restores a datablock in which position and velocity are at their
    // defaults, the solver starts from rest on every frame, and the chain sits
    // perfectly still while Cached Playback is on.
    schema.add(aStatePosition);
    schema.add(aStateVelocity);
    schema.add(aStateTime);
    schema.add(aStateInitialised);
}

MTimeRange McaPhysicsChain::transformInvalidationRange(const MPlug& source,
                                                       const MTimeRange& input) const {
    // A change at time t invalidates every frame from t onward, not just t.
    //
    // This node carries its simulation state from one frame to the next through
    // its own state plugs, which is a dependency the DG cannot see: there is no
    // connection representing "frame 45 depends on frame 44". Without this
    // override Maya invalidates only the frames that actually changed, keeps the
    // rest of the cache, and the chain after an edit is a mixture of new
    // animation and stale simulation.
    //
    // Measured: with Cached Playback filling correctly but no invalidation
    // transform, moving one key at frame 30 left the cached result 2.644205
    // scene units from the truth at frame 40 - on a chain whose tip travels
    // 3.496717. Most of the motion, wrong, on an edit an animator makes
    // constantly.
    if (input.empty()) {
        return input;
    }
    // auto, because MClosedTimeInterval lives in Maya's versioned namespace and
    // naming it directly does not compile without opening that namespace here.
    const auto bounds = input.bounds();
    // "To the end of time." Not literally MTime's maximum: the header warns that
    // beyond 2^62 ticks Maya may treat a value as infinity and arithmetic stops
    // behaving. A billion frames is about 480 days of animation at 24fps and
    // four orders of magnitude inside that limit.
    static const double kEndOfTime = 1.0e9;
    return MTimeRange(bounds.min, MTime(kEndOfTime, MTime::uiUnit()));
}

MStatus McaPhysicsChain::compute(const MPlug& plug, MDataBlock& data) {
    const MObject attribute = plug.attribute();
    const bool wanted = attribute == aOutLevels || attribute == aOutTranslate ||
                        attribute == aOutRotate || attribute == aOutMatrix ||
                        attribute == aStatePosition || attribute == aStateVelocity ||
                        attribute == aStateTime || attribute == aStateInitialised ||
                        attribute == aOutRotateX ||
                        attribute == aOutRotateY || attribute == aOutRotateZ;
    if (!wanted) {
        return MS::kUnknownParameter;
    }

    MStatus status;

    // --- read the chain --------------------------------------------------- //

    MArrayDataHandle levelsHandle = data.inputArrayValue(aInLevels, &status);
    if (!status) {
        return status;
    }
    const unsigned int levelCount = levelsHandle.elementCount();
    if (levelCount == 0) {
        data.setClean(plug);
        return MS::kSuccess;
    }

    // Physical index, not logical. jumpToArrayElement walks the elements that
    // actually exist, so a chain wired to inLevels[0] and inLevels[5] has an
    // elementCount of 2 - and indexing the output by the logical index would
    // leave holes that never get written. Keep the logical indices so the
    // outputs line up with whatever the rig connected.
    std::vector<MMatrix> goals(levelCount);
    std::vector<unsigned int> logicalIndex(levelCount, 0);
    for (unsigned int i = 0; i < levelCount; ++i) {
        status = levelsHandle.jumpToArrayElement(i);
        if (!status) {
            continue;
        }
        logicalIndex[i] = levelsHandle.elementIndex();
        MDataHandle levelHandle = levelsHandle.inputValue(&status);
        if (!status) {
            continue;
        }
        goals[i] = levelHandle.child(aGoalMatrix).asMatrix();
    }

    const double currentTime = data.inputValue(aInTime, &status).asTime().value();
    const double startTime = data.inputValue(aStartTime, &status).asTime().value();
    const bool enabled = data.inputValue(aEnabled, &status).asBool();
    const double stateTime = data.outputValue(aStateTime, &status).asTime().value();
    const bool stateInitialised = data.outputValue(aStateInitialised, &status).asBool();

    const double flatMass = data.inputValue(aMass, &status).asDouble();
    const bool advanced = data.inputValue(aAdvanced, &status).asBool();
    const double amount = data.inputValue(aAmount, &status).asDouble();
    const double springiness = data.inputValue(aSpringiness, &status).asDouble();
    const double droop = data.inputValue(aDroop, &status).asDouble();

    // Amount and Springiness ARE stiffness and damping, mapped so that turning
    // them up does more of what they are named after. Advanced hands the raw
    // values back to anyone who wants them.
    const double flatStiffness = advanced ? data.inputValue(aStiffness, &status).asDouble()
                                          : 8.0 * std::pow(256.0, -amount);
    const double flatDamping = advanced ? data.inputValue(aDamping, &status).asDouble()
                                        : 1.0 - 0.6 * springiness;
    const double flatGravity = advanced ? data.inputValue(aGravity, &status).asDouble() : 0.0;
    const mca::Vec3 gravityDirection =
        toVec3(data.inputValue(aGravityDirection, &status).asDouble3());
    const short solveMode = data.inputValue(aSolveMode, &status).asShort();
    const short updateMode = data.inputValue(aUpdateMode, &status).asShort();
    const double flatAimWeight = data.inputValue(aAimWeight, &status).asDouble();
    const double upWeight = data.inputValue(aUpWeight, &status).asDouble();
    const double limitAngle = data.inputValue(aLimitAngle, &status).asDouble();
    const double stretch = data.inputValue(aStretch, &status).asDouble();

    mca::AimConvention convention;
    decodeAxis(data.inputValue(aAimAxis, &status).asShort(), convention.aimAxis,
               convention.aimSign);
    decodeAxis(data.inputValue(aUpAxis, &status).asShort(), convention.upAxis, convention.upSign);
    if (convention.aimAxis == convention.upAxis) {
        // Aim and up on the same axis cannot describe an orientation. Nudge the
        // up axis rather than returning NaNs.
        convention.upAxis = (convention.aimAxis + 1) % 3;
    }

    const bool useStiffnessRamp = data.inputValue(aUseStiffnessRamp, &status).asBool();
    const bool useDampingRamp = data.inputValue(aUseDampingRamp, &status).asBool();
    const bool useMassRamp = data.inputValue(aUseMassRamp, &status).asBool();
    const bool useGravityRamp = data.inputValue(aUseGravityRamp, &status).asBool();
    const bool useAimWeightRamp = data.inputValue(aUseAimWeightRamp, &status).asBool();
    const MObject self = thisMObject();

    // --- read the stored state ---------------------------------------------- //

    std::vector<mca::State> states(levelCount);
    MArrayDataHandle positionsHandle = data.outputArrayValue(aStatePosition, &status);
    MArrayDataHandle velocitiesHandle = data.outputArrayValue(aStateVelocity, &status);
    for (unsigned int i = 0; i < levelCount; ++i) {
        if (positionsHandle.jumpToElement(logicalIndex[i]) == MS::kSuccess) {
            states[i].position = toVec3(positionsHandle.outputValue().asDouble3());
        }
        if (velocitiesHandle.jumpToElement(logicalIndex[i]) == MS::kSuccess) {
            states[i].velocity = toVec3(velocitiesHandle.outputValue().asDouble3());
        }
    }

    // --- solve --------------------------------------------------------------- //

    // A dt of exactly zero now means "the state I am holding is already the
    // answer for this frame" rather than "reset" - which is what makes Cached
    // Playback work. That only holds if there IS a state, hence the flag.
    const bool resetting = !enabled || currentTime <= startTime || !stateInitialised;
    const double dt = currentTime - stateTime;

    if (!traceFile().empty()) {
        // Everything needed to tell the two failure modes apart: whether
        // compute() ran at all for this frame, and what time it thought it was.
        std::ostringstream line;
        line << "compute plug=" << plug.partialName(false, false, false, false, false, true).asChar()
             << " inTime=" << currentTime
             << " startTime=" << startTime
             << " stateTime=" << stateTime
             << " dt=" << dt
             << " resetting=" << (resetting ? 1 : 0)
             << " initialised=" << (stateInitialised ? 1 : 0)
             << " enabled=" << (enabled ? 1 : 0)
             << " levels=" << levelCount;
        trace(line.str());
    }

    // How far each level ended up from where the animation put it. A level
    // inherits its parent's lag, which is what makes this a chain rather than a
    // row of independent springs: without it every level lags by exactly the
    // same amount and the whole thing slides as a rigid body. Measured before
    // this was added: all six levels lagged 33.152 and sagged -6.667, to the
    // millimetre.
    std::vector<mca::Vec3> carried(levelCount, mca::Vec3());

    for (unsigned int i = 0; i < levelCount; ++i) {
        mca::Vec3 goalPosition = translationOf(goals[i]);
        if (i > 0) {
            goalPosition = goalPosition + carried[i - 1];
        }
        // Position along the chain, 0 at the root and 1 at the tip. A single
        // level is the root, not the tip: it should get the un-ramped value.
        const double along = levelCount > 1
                                 ? static_cast<double>(i) / static_cast<double>(levelCount - 1)
                                 : 0.0;

        if (resetting) {
            states[i].position = goalPosition;
            states[i].velocity = mca::Vec3();
            carried[i] = mca::Vec3();
            continue;
        }

        mca::SolverParams params;
        params.mass = rampedValue(self, aMassRamp, useMassRamp, flatMass, along);
        params.stiffness = rampedValue(self, aStiffnessRamp, useStiffnessRamp, flatStiffness,
                                       along);
        params.damping = rampedValue(self, aDampingRamp, useDampingRamp, flatDamping, along);
        params.gravity = rampedValue(self, aGravityRamp, useGravityRamp, flatGravity, along);
        params.gravityDirection = gravityDirection;
        if (!advanced && droop > 0.0 && params.mass > 0.0) {
            // How far below its pose a level settles, as a multiple of its own
            // length. Cancelling stiffness out of the steady state (x = g*m/k)
            // is the point: the hang then survives a change of Amount.
            //
            // The ratio is droop/(1-droop) rather than droop, because a chain
            // approaches vertical asymptotically and the slider should be linear
            // in the angle it produces, not in the force. A level sitting one
            // length below its pose only gets HALFWAY to straight down - so the
            // first version, which used droop directly, topped out at 28.7
            // degrees off vertical with the slider at maximum and read as gravity
            // that refused to work. Raw gravity of 120 reached 2.8 degrees, so
            // the force was never the limit; the mapping was.
            //
            // With this: 0.25 is about 46 degrees off vertical, 0.5 is 30, 0.75
            // is 14, and 1.0 hangs. Capped so gravity stays finite.
            const double kMaxDroopRatio = 20.0;
            const unsigned int near = i > 0 ? i - 1 : 0;
            const unsigned int far = i > 0 ? i : (levelCount > 1 ? 1u : 0u);
            const double restLength =
                near == far ? 1.0
                            : mca::length(translationOf(goals[far]) - translationOf(goals[near]));
            const double ratio = droop >= 1.0
                                     ? kMaxDroopRatio
                                     : std::min(droop / (1.0 - droop), kMaxDroopRatio);
            params.gravity = ratio * restLength * params.stiffness / params.mass *
                             rampedValue(self, aGravityRamp, useGravityRamp, 1.0, along);
        }
        params.solveMode = solveMode == 1 ? mca::SolveMode::Vector : mca::SolveMode::PerAxis;
        params.updateMode =
            updateMode == 1 ? mca::UpdateMode::Acceleration : mca::UpdateMode::Velocity;

        states[i] = mca::step(states[i], goalPosition, dt, params);

        // Limit the swing relative to where the animation wanted this level,
        // measured from the level above it. Without a parent to measure from,
        // the root has nothing to swing away from.
        if (limitAngle < 180.0 && i > 0) {
            const mca::Vec3 parent = states[i - 1].position;
            const mca::Vec3 goalDirection = translationOf(goals[i]) - translationOf(goals[i - 1]);
            if (mca::length(goalDirection) > 1e-9) {
                states[i].position =
                    mca::clampToCone(parent, goalDirection, states[i].position, limitAngle);
            }
        }

        // Hold this level at the distance the animation has it from its parent.
        // The spring decides the direction; the chain decides the length. Done
        // after the cone clamp because that moves the position too, and before
        // the carried displacement is measured because everything downstream is
        // built from a position that has already been made legal.
        if (i > 0 && stretch < 1.0) {
            const mca::Vec3 parent = states[i - 1].position;
            const double rest =
                mca::length(translationOf(goals[i]) - translationOf(goals[i - 1]));
            const mca::Vec3 offset = states[i].position - parent;
            const double current = mca::length(offset);
            if (current > 1e-9 && rest > 1e-9) {
                const double target = rest + (current - rest) * stretch;
                states[i].position = parent + offset * (target / current);
            }
        }

        // Total displacement from where the ANIMATION put this level, not from
        // the already-offset goal it was solved against. The distinction is the
        // whole behaviour: measuring against the offset goal carries only each
        // level's own incremental lag, so inheritance stops after one level and
        // the chain sags to exactly twice the root and then flattens. Measuring
        // against the animated pose accumulates, which is what a chain does.
        carried[i] = states[i].position - translationOf(goals[i]);
    }

    // --- orientation and output ------------------------------------------------ //

    MArrayDataHandle outHandle = data.outputArrayValue(aOutLevels, &status);
    MArrayDataBuilder outBuilder = outHandle.builder(&status);
    MArrayDataBuilder positionBuilder = positionsHandle.builder(&status);
    MArrayDataBuilder velocityBuilder = velocitiesHandle.builder(&status);

    mca::Basis previousBasis;
    bool havePrevious = false;

    for (unsigned int i = 0; i < levelCount; ++i) {
        const mca::Basis goalBasis = basisOf(goals[i]);
        mca::Basis basis = goalBasis;

        // Aim down the chain. Every level aims at the next; the last one has
        // nothing below it, so it takes the direction of the segment that
        // arrives AT it.
        //
        // Leaving the tip on the goal basis - which is what this did first, with
        // a comment claiming it stopped the tip flicking - means the last flag
        // never moves at all, however hard the chain swings. Measured: the tip's
        // rotation differed from the animation by exactly 0.000 degrees while
        // the level above it differed by 59.7.
        const bool hasNext = (i + 1 < levelCount);
        if (hasNext || i > 0) {
            const double along = levelCount > 1
                                     ? static_cast<double>(i) /
                                           static_cast<double>(levelCount - 1)
                                     : 0.0;
            const double aimWeight =
                rampedValue(self, aAimWeightRamp, useAimWeightRamp, flatAimWeight, along);

            // Up follows the animation at upWeight 1 and the chain's own twist
            // at 0. It used to be multiplied into the aim blend instead, which
            // meant turning Up Weight down silently switched the aim off - two
            // separate controls wired to one thing.
            mca::Vec3 up = goalBasis.axis(convention.upAxis);
            if (havePrevious && upWeight < 1.0) {
                const mca::Vec3 carriedUp = previousBasis.axis(convention.upAxis);
                up = mca::normalized(up * upWeight + carriedUp * (1.0 - upWeight));
            }

            const mca::Vec3 from = hasNext ? states[i].position : states[i - 1].position;
            const mca::Vec3 to = hasNext ? states[i + 1].position : states[i].position;
            const mca::Basis aimed = mca::aimBasis(from, to, up, convention, goalBasis);
            basis = mca::blendBasis(goalBasis, aimed, aimWeight);
        }
        previousBasis = basis;
        havePrevious = true;

        const mca::Vec3 euler = mca::eulerFromBasis(basis);

        MDataHandle outLevel = outBuilder.addElement(logicalIndex[i], &status);
        if (!status) {
            continue;
        }
        MDataHandle translateHandle = outLevel.child(aOutTranslate);
        translateHandle.set3Double(states[i].position.x, states[i].position.y,
                                   states[i].position.z);

        MDataHandle rotateHandle = outLevel.child(aOutRotate);
        rotateHandle.child(aOutRotateX).setMAngle(MAngle(euler.x, MAngle::kRadians));
        rotateHandle.child(aOutRotateY).setMAngle(MAngle(euler.y, MAngle::kRadians));
        rotateHandle.child(aOutRotateZ).setMAngle(MAngle(euler.z, MAngle::kRadians));

        outLevel.child(aOutMatrix).setMMatrix(matrixOf(basis, states[i].position));

        MDataHandle positionElement = positionBuilder.addElement(logicalIndex[i], &status);
        if (status) {
            positionElement.set3Double(states[i].position.x, states[i].position.y,
                                       states[i].position.z);
        }
        MDataHandle velocityElement = velocityBuilder.addElement(logicalIndex[i], &status);
        if (status) {
            velocityElement.set3Double(states[i].velocity.x, states[i].velocity.y,
                                       states[i].velocity.z);
        }
    }

    outHandle.set(outBuilder);
    outHandle.setAllClean();
    positionsHandle.set(positionBuilder);
    positionsHandle.setAllClean();
    velocitiesHandle.set(velocityBuilder);
    velocitiesHandle.setAllClean();

    MDataHandle stateTimeHandle = data.outputValue(aStateTime, &status);
    stateTimeHandle.setMTime(MTime(currentTime, MTime::uiUnit()));
    stateTimeHandle.setClean();

    MDataHandle stateInitialisedHandle = data.outputValue(aStateInitialised, &status);
    stateInitialisedHandle.setBool(true);
    stateInitialisedHandle.setClean();

    data.setClean(plug);
    return MS::kSuccess;
}
