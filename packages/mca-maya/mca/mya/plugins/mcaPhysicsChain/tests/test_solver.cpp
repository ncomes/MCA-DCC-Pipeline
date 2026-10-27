// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// Tests for the physics chain solver. No Maya, no scene, no timeline - build
// and run this anywhere:
//
//     g++ -std=c++17 -I../include ../source/mca_solver.cpp test_solver.cpp -o test_solver
//     ./test_solver

#include "mca_solver.h"

#include <cmath>
#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

namespace {

int gChecks = 0;
std::vector<std::string> gFailures;

void check(const std::string& label, bool condition, const std::string& detail = "") {
    ++gChecks;
    if (!condition) {
        gFailures.push_back(label + (detail.empty() ? "" : "  |  " + detail));
    }
}

mca::SolverParams defaults() {
    mca::SolverParams p;
    p.mass = 1.0;
    p.stiffness = 10.0;
    p.damping = 0.2;
    return p;
}

/// Run a chain of steps against a stationary goal and report the furthest the
/// simulated point ever got past it.
double overshootAgainstGoal(const mca::SolverParams& params, int steps) {
    mca::State s;
    s.position = mca::Vec3(10.0, 0.0, 0.0);
    const mca::Vec3 goal(0.0, 0.0, 0.0);
    double worstPast = 0.0;
    for (int i = 0; i < steps; ++i) {
        s = mca::step(s, goal, 1.0 / 24.0, params);
        if (s.position.x < worstPast) {
            worstPast = s.position.x;
        }
    }
    return -worstPast;
}

}  // namespace

int main() {
    // --- the damping ratio means what it says ---------------------------- //
    {
        mca::SolverParams p = defaults();
        p.damping = 1.0;
        const double overshoot = overshootAgainstGoal(p, 400);
        check("a critically damped spring does not overshoot", overshoot < 1e-3,
              "overshot by " + std::to_string(overshoot));

        p.damping = 0.05;
        const double loose = overshootAgainstGoal(p, 400);
        check("a lightly damped spring does overshoot", loose > 0.5,
              "overshot by " + std::to_string(loose));
    }

    // --- it settles on the goal ------------------------------------------ //
    {
        mca::SolverParams p = defaults();
        p.damping = 0.6;
        mca::State s;
        s.position = mca::Vec3(25.0, -7.0, 3.0);
        const mca::Vec3 goal(1.0, 2.0, 3.0);
        for (int i = 0; i < 2000; ++i) {
            s = mca::step(s, goal, 1.0 / 24.0, p);
        }
        const double distance = mca::length(s.position - goal);
        check("a damped spring settles on the goal", distance < 1e-6,
              "still " + std::to_string(distance) + " away");
        check("and stops moving", mca::length(s.velocity) < 1e-6,
              "velocity " + std::to_string(mca::length(s.velocity)));
    }

    // --- the property the original could not hold ------------------------- //
    {
        // Same inputs, same outputs, every time. The node this replaces derived
        // dt from whatever frame it happened to evaluate previously, so the same
        // frame could produce different results depending on how you got there.
        const mca::SolverParams p = defaults();
        mca::State a;
        a.position = mca::Vec3(4.0, 5.0, 6.0);
        a.velocity = mca::Vec3(0.5, 0.0, -0.25);
        const mca::State b = a;
        const mca::Vec3 goal(0.0, 0.0, 0.0);

        const mca::State ra = mca::step(a, goal, 1.0 / 24.0, p);
        const mca::State rb = mca::step(b, goal, 1.0 / 24.0, p);
        check("the same state and step give the same result",
              ra.position.x == rb.position.x && ra.position.y == rb.position.y &&
                  ra.position.z == rb.position.z && ra.velocity.x == rb.velocity.x);
    }

    // --- zero and negative dt are DIFFERENT --------------------------------- //
    //
    // This used to assert that a dt of zero snapped to the goal, and that check
    // passed happily while making the node useless under Cached Playback: Maya
    // restores a cached node's state for the frame it is about to evaluate, so
    // dt arrives as exactly zero, and snapping there destroys a state that was
    // already correct. The chain sat perfectly still with the cache on.
    //
    // Zero now means "what I am holding is already the answer for this time".
    // Negative still means restart, because integrating a spring backwards is
    // not something the maths supports.
    {
        const mca::SolverParams p = defaults();
        mca::State s;
        s.position = mca::Vec3(9.0, 9.0, 9.0);
        s.velocity = mca::Vec3(3.0, 3.0, 3.0);
        const mca::Vec3 goal(1.0, 2.0, 3.0);

        const mca::State held = mca::step(s, goal, 0.0, p);
        check("a dt of zero returns the state untouched",
              mca::length(held.position - s.position) < 1e-12);
        check("velocity included, or the next real step starts from rest",
              mca::length(held.velocity - s.velocity) < 1e-12);

        const mca::State back = mca::step(s, goal, -1.0, p);
        check("a negative dt restarts at the goal",
              mca::length(back.position - goal) < 1e-12);
        check("and clears the velocity", mca::length(back.velocity) < 1e-12);

        // Re-solving the same frame must be idempotent. This is what the node
        // relies on every time Maya hands back a restored state.
        const mca::State once = mca::step(s, goal, 1.0, p);
        const mca::State twice = mca::step(once, goal, 0.0, p);
        check("re-solving a frame changes nothing",
              mca::length(twice.position - once.position) < 1e-12 &&
                  mca::length(twice.velocity - once.velocity) < 1e-12);
    }

    // --- gravity pulls the right way -------------------------------------- //
    {
        mca::SolverParams p = defaults();
        p.stiffness = 1.0;
        p.damping = 0.9;
        p.gravity = 50.0;
        p.gravityDirection = mca::Vec3(0.0, -1.0, 0.0);
        mca::State s;
        const mca::Vec3 goal(0.0, 0.0, 0.0);
        for (int i = 0; i < 200; ++i) {
            s = mca::step(s, goal, 1.0 / 24.0, p);
        }
        check("gravity drags the chain down", s.position.y < -1.0,
              "y ended at " + std::to_string(s.position.y));
        check("and only down", std::fabs(s.position.x) < 1e-9 && std::fabs(s.position.z) < 1e-9);
    }

    // --- degenerate parameters must not poison the chain ------------------ //
    {
        const mca::Vec3 goal(0.0, 0.0, 0.0);
        mca::State s;
        s.position = mca::Vec3(5.0, 0.0, 0.0);

        mca::SolverParams zeroMass = defaults();
        zeroMass.mass = 0.0;
        const mca::State m = mca::step(s, goal, 1.0 / 24.0, zeroMass);
        check("zero mass does not produce NaN", !std::isnan(m.position.x));

        mca::SolverParams zeroStiff = defaults();
        zeroStiff.stiffness = 0.0;
        const mca::State k = mca::step(s, goal, 1.0 / 24.0, zeroStiff);
        check("zero stiffness does not produce NaN", !std::isnan(k.position.x));
        check("a zero-length gravity direction does not produce NaN",
              !std::isnan(mca::normalized(mca::Vec3()).x));
    }

    // --- both solve modes are usable -------------------------------------- //
    {
        for (int mode = 0; mode < 2; ++mode) {
            mca::SolverParams p = defaults();
            p.solveMode = mode == 0 ? mca::SolveMode::PerAxis : mca::SolveMode::Vector;
            p.damping = 0.7;
            mca::State s;
            s.position = mca::Vec3(8.0, 4.0, -2.0);
            const mca::Vec3 goal(0.0, 0.0, 0.0);
            for (int i = 0; i < 2000; ++i) {
                s = mca::step(s, goal, 1.0 / 24.0, p);
            }
            check(std::string(mode == 0 ? "per-axis" : "vector") + " mode settles on the goal",
                  mca::length(s.position - goal) < 1e-5,
                  "left " + std::to_string(mca::length(s.position - goal)) + " away");
        }
    }

    // --- stiffness behaves monotonically ---------------------------------- //
    {
        // A stiffer spring should get back to the goal sooner. Worth pinning:
        // it is the assumption every animator makes when they touch the slider.
        auto distanceAfter = [](double stiffness) {
            mca::SolverParams p = defaults();
            p.stiffness = stiffness;
            p.damping = 0.9;
            mca::State s;
            s.position = mca::Vec3(10.0, 0.0, 0.0);
            for (int i = 0; i < 24; ++i) {
                s = mca::step(s, mca::Vec3(), 1.0 / 24.0, p);
            }
            return std::fabs(s.position.x);
        };
        check("a stiffer spring recovers faster", distanceAfter(40.0) < distanceAfter(4.0));
    }

    // --- frame-sized steps must not detonate ------------------------------ //
    {
        // Maya measures dt in frames, so dt is 1.0, not 1/24. At stiffness 8 that
        // puts omega*dt past RK4's stability limit and the chain exploded to
        // 124,117 units from a goal 10 away. Substepping is what makes a
        // stiffness slider safe to drag.
        for (double stiffness : {8.0, 50.0, 500.0, 5000.0}) {
            mca::SolverParams p;
            p.mass = 1.0;
            p.stiffness = stiffness;
            p.damping = 1.0;
            mca::State s;
            s.position = mca::Vec3(10.0, 0.0, 0.0);
            double peak = 0.0;
            for (int frame = 0; frame < 120; ++frame) {
                s = mca::step(s, mca::Vec3(), 1.0, p);
                peak = std::max(peak, std::fabs(s.position.x));
            }
            check("stiffness " + std::to_string(static_cast<int>(stiffness)) +
                      " stays bounded at one-frame steps",
                  peak <= 10.001 && !std::isnan(s.position.x),
                  "peak " + std::to_string(peak));
            check("stiffness " + std::to_string(static_cast<int>(stiffness)) +
                      " still settles on the goal",
                  std::fabs(s.position.x) < 0.01, "left at " + std::to_string(s.position.x));
        }
        mca::SolverParams p;
        p.mass = 1.0;
        p.stiffness = 8.0;
        check("a frame-sized step is subdivided", mca::substepCount(1.0, p) > 1,
              std::to_string(mca::substepCount(1.0, p)));
        check("substeps are capped", mca::substepCount(1.0, {1.0, 1e12, 1.0, 0.0,
                                                             mca::Vec3(0, -1, 0),
                                                             mca::SolveMode::PerAxis,
                                                             mca::UpdateMode::Velocity}) <=
                                         mca::kMaxSubsteps);
    }

    // --- orientation ------------------------------------------------------ //
    {
        mca::AimConvention conv;  // aim +x, up +y
        mca::Basis fallback;

        const mca::Basis b = mca::aimBasis(mca::Vec3(), mca::Vec3(0.0, 0.0, 10.0),
                                           mca::Vec3(0.0, 1.0, 0.0), conv, fallback);
        check("aim points x down the target", std::fabs(b.x.z - 1.0) < 1e-9,
              std::to_string(b.x.z));
        check("the frame is orthonormal",
              std::fabs(mca::dot(b.x, b.y)) < 1e-9 && std::fabs(mca::dot(b.x, b.z)) < 1e-9 &&
                  std::fabs(mca::dot(b.y, b.z)) < 1e-9);
        check("and unit length",
              std::fabs(mca::length(b.x) - 1.0) < 1e-9 &&
                  std::fabs(mca::length(b.y) - 1.0) < 1e-9 &&
                  std::fabs(mca::length(b.z) - 1.0) < 1e-9);
        check("and right handed",
              mca::length(mca::cross(b.x, b.y) - b.z) < 1e-9,
              "cross(x,y) should be z");

        // The cases that produce NaNs if you do not look for them. A NaN in one
        // level spreads to every level below it and the chain vanishes.
        const mca::Basis same = mca::aimBasis(mca::Vec3(1, 2, 3), mca::Vec3(1, 2, 3),
                                              mca::Vec3(0, 1, 0), conv, fallback);
        check("two levels in the same place keep the previous frame",
              !std::isnan(same.x.x) && std::fabs(same.x.x - fallback.x.x) < 1e-9);
        const mca::Basis parallel = mca::aimBasis(mca::Vec3(), mca::Vec3(0, 10, 0),
                                                  mca::Vec3(0, 1, 0), conv, fallback);
        check("an up parallel to the aim keeps the previous frame",
              !std::isnan(parallel.x.x));
        const mca::Basis noUp = mca::aimBasis(mca::Vec3(), mca::Vec3(10, 0, 0),
                                              mca::Vec3(), conv, fallback);
        check("a zero up vector does not produce NaN", !std::isnan(noUp.x.x));
    }

    // --- blending stays square --------------------------------------------- //
    {
        mca::AimConvention conv;
        mca::Basis fallback;
        const mca::Basis a = mca::aimBasis(mca::Vec3(), mca::Vec3(10, 0, 0),
                                           mca::Vec3(0, 1, 0), conv, fallback);
        const mca::Basis b = mca::aimBasis(mca::Vec3(), mca::Vec3(0, 0, 10),
                                           mca::Vec3(0, 1, 0), conv, fallback);
        for (double w : {0.0, 0.25, 0.5, 0.75, 1.0}) {
            const mca::Basis m = mca::blendBasis(a, b, w);
            check("blend at " + std::to_string(w) + " stays orthonormal",
                  std::fabs(mca::dot(m.x, m.y)) < 1e-6 &&
                      std::fabs(mca::length(m.x) - 1.0) < 1e-6 &&
                      std::fabs(mca::length(m.z) - 1.0) < 1e-6);
        }
        check("blend at 0 is the first", mca::length(mca::blendBasis(a, b, 0.0).x - a.x) < 1e-9);
        check("blend at 1 is the second", mca::length(mca::blendBasis(a, b, 1.0).x - b.x) < 1e-9);
    }

    // --- cone limits -------------------------------------------------------- //
    {
        const mca::Vec3 origin;
        const mca::Vec3 axis(1.0, 0.0, 0.0);
        // 45 degrees off the axis, limited to 30, must come back to exactly 30
        // without changing how far out it is.
        const mca::Vec3 swung(std::cos(0.785398), std::sin(0.785398), 0.0);
        const mca::Vec3 clamped = mca::clampToCone(origin, axis, swung * 10.0, 30.0);
        const double angle = std::acos(mca::dot(mca::normalized(clamped), axis)) * 180.0 / 3.14159265358979;
        check("a swing past the limit is clamped to it", std::fabs(angle - 30.0) < 1e-3,
              std::to_string(angle));
        check("and keeps its distance", std::fabs(mca::length(clamped) - 10.0) < 1e-6,
              std::to_string(mca::length(clamped)));
        const mca::Vec3 inside = mca::clampToCone(origin, axis, mca::Vec3(10, 1, 0), 45.0);
        check("a swing inside the limit is untouched",
              mca::length(inside - mca::Vec3(10, 1, 0)) < 1e-9);
        const mca::Vec3 unlimited = mca::clampToCone(origin, axis, mca::Vec3(-10, 0, 0), 180.0);
        check("a limit of 180 is no limit",
              mca::length(unlimited - mca::Vec3(-10, 0, 0)) < 1e-9);
    }

    std::printf("\n%d/%d checks passed.\n", gChecks - static_cast<int>(gFailures.size()), gChecks);
    for (const std::string& failure : gFailures) {
        std::printf("  FAIL  %s\n", failure.c_str());
    }
    return gFailures.empty() ? 0 : 1;
}
