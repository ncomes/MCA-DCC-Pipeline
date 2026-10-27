// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// mcaPhysicsChain: secondary motion for a joint chain, solved as a
// mass/spring/damper per level.
//
// One node drives a whole chain. Each level has a goal - where the animation
// says it should be - and the solver lags behind it, overshoots and settles.
// Orientation comes from aiming each level at the next, so a chain reads as a
// chain rather than as independently wobbling transforms.
//
// The maths is in mca_solver.h and has no Maya in it, so it is tested off-DCC.
// This file is the Maya shell: attributes in, solver, attributes out.
//
// Two design points worth knowing, both departures from how such nodes are
// usually written:
//
// **Simulation state lives in attributes, not on the instance.** Position and
// velocity carry between frames, and the obvious home for them is a member
// variable - which is what the tool this replaces did, and why it could not
// work with Cached Playback and was unsafe under parallel evaluation. Maya's
// rule is explicit: "store node state/settings in attributes". State Maya can
// see is state Maya can cache.
//
// **The node declares itself a simulation.** getCacheSetup() asks for
// kSimulationSupport so the cache fills forward only and invalidates forward in
// time from any edit.
//
// **And it tells the cache to carry the state.** Declaring the simulation is not
// enough on its own. Under Cached Playback a node can be evaluated against a
// datablock restored from the cache, and anything the cache was not told to keep
// comes back at its default - so position and velocity arrived empty at every
// frame, the solver restarted from rest each time, and the chain did not move AT
// ALL. Measured: the cached result differed from the truth by 2.380374369 on a
// chain whose tip travels 2.380374369. configCache() adds the three state plugs
// to the cache schema, which is what makes the state survive.

#ifndef MCA_PHYSICS_CHAIN_H
#define MCA_PHYSICS_CHAIN_H

#include <maya/MPxNode.h>
#include <maya/MTimeRange.h>
#include <maya/MTypeId.h>
#include <maya/MObject.h>
#include <maya/MStatus.h>
#include <maya/MDataBlock.h>
#include <maya/MPlug.h>
#include <maya/MNodeCacheDisablingInfo.h>
#include <maya/MNodeCacheSetupInfo.h>
#include <maya/MEvaluationNode.h>
#include <maya/MCacheSchema.h>

class McaPhysicsChain : public MPxNode {
public:
    static void* creator();
    static MStatus initialize();

    static const MString kNodeName;
    static const MTypeId kNodeId;

    MStatus compute(const MPlug& plug, MDataBlock& data) override;

    void configCache(const MEvaluationNode& evalNode, MCacheSchema& schema) const override;

    /// How far forward a change at one time invalidates this node's output.
    ///
    /// The answer for a simulation is "to the end of time", and saying so is the
    /// whole of making Cached Playback correct here.
    MTimeRange transformInvalidationRange(const MPlug& source,
                                          const MTimeRange& input) const override;

    void getCacheSetup(const MEvaluationNode& evalNode, MNodeCacheDisablingInfo& disablingInfo,
                       MNodeCacheSetupInfo& cacheSetupInfo,
                       MObjectArray& monitoredAttributes) const override;

    // --- time and gate ---------------------------------------------------- //
    static MObject aInTime;
    static MObject aStartTime;
    static MObject aEnabled;

    // --- the chain --------------------------------------------------------- //
    static MObject aInLevels;        ///< Array. One entry per level.
    static MObject aGoalMatrix;      ///< Child of inLevels.

    static MObject aOutLevels;       ///< Array, matching inLevels.
    static MObject aOutTranslate;    ///< Child of outLevels.
    static MObject aOutRotate;       ///< Child of outLevels.
    static MObject aOutRotateX;
    static MObject aOutRotateY;
    static MObject aOutRotateZ;
    static MObject aOutMatrix;       ///< Child of outLevels.

    // --- solver ------------------------------------------------------------ //
    static MObject aMass;
    static MObject aStiffness;
    static MObject aDamping;
    static MObject aGravity;
    static MObject aGravityDirection;
    static MObject aSolveMode;
    static MObject aUpdateMode;

    // --- orientation -------------------------------------------------------- //
    static MObject aAimAxis;
    static MObject aUpAxis;
    static MObject aAimWeight;
    static MObject aUpWeight;

    // --- limits -------------------------------------------------------------- //
    static MObject aLimitAngle;      ///< Degrees from the goal direction. 180 = off.
    // --- what an animator actually turns --------------------------------- //
    //
    // Stiffness and damping are the physics, and they are poor controls: lower
    // stiffness means MORE lag until the chain stops following at all, and lag
    // is not even monotonic in damping - measured on a nine level chain it fell
    // from 64.6 to 40.1 as damping went 0.7 -> 0.3, then rose again to 57.7 by
    // 0.1. These three are monotonic in what they are named after, and map onto
    // the physics below.

    static MObject aAdvanced;        ///< Use the raw physics values instead.
    static MObject aAmount;          ///< 0 tracks the animation, 1 trails far behind.
    static MObject aSpringiness;     ///< 0 settles dead, 1 overshoots and bounces.
    static MObject aDroop;           ///< Hang, in segment lengths. Scale free.

    static MObject aStretch;         ///< 0 holds segment lengths, 1 lets them float free.

    // --- ramps, for varying a parameter along the chain ---------------------- //
    static MObject aUseStiffnessRamp;
    static MObject aStiffnessRamp;
    static MObject aUseDampingRamp;
    static MObject aDampingRamp;
    static MObject aUseMassRamp;
    static MObject aMassRamp;
    static MObject aUseGravityRamp;
    static MObject aGravityRamp;
    static MObject aUseAimWeightRamp;
    static MObject aAimWeightRamp;

    // --- state, stored so the cache can see it -------------------------------- //
    static MObject aStatePosition;   ///< Array, one per level.
    static MObject aStateVelocity;   ///< Array, one per level.
    static MObject aStateTime;
    /// Whether the three state plugs above have ever been written. Without it,
    /// a dt of exactly zero on a node that has never solved would hand the
    /// solver an all-zero state and be told to keep it.
    static MObject aStateInitialised;
};

#endif  // MCA_PHYSICS_CHAIN_H
