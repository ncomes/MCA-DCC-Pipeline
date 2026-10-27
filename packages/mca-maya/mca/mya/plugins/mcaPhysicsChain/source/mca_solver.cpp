// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_solver.h"

#include <algorithm>
#include <cmath>

namespace mca {

Vec3 operator+(const Vec3& a, const Vec3& b) { return Vec3(a.x + b.x, a.y + b.y, a.z + b.z); }
Vec3 operator-(const Vec3& a, const Vec3& b) { return Vec3(a.x - b.x, a.y - b.y, a.z - b.z); }
Vec3 operator*(const Vec3& v, double s) { return Vec3(v.x * s, v.y * s, v.z * s); }

double length(const Vec3& v) { return std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z); }

Vec3 normalized(const Vec3& v) {
    const double len = length(v);
    // A zero-length direction is a legitimate way to mean "no gravity", so it
    // returns zero rather than dividing and producing NaNs that then spread
    // through the whole chain.
    return len > 1e-12 ? v * (1.0 / len) : Vec3();
}

double dampingCoefficient(double mass, double stiffness, double dampingRatio) {
    if (mass <= 0.0 || stiffness <= 0.0) {
        return 0.0;
    }
    return dampingRatio * 2.0 * mass * std::sqrt(stiffness / mass);
}

double acceleration(double offset, double velocity, double gravityOnAxis,
                    const SolverParams& params) {
    if (params.mass <= 0.0) {
        // Massless is not a physical state and dividing by it would produce
        // infinities. Treat it as "pinned to the animation".
        return 0.0;
    }
    const double damp = dampingCoefficient(params.mass, params.stiffness, params.damping);
    return (-offset * params.stiffness - velocity * damp) / params.mass + gravityOnAxis;
}

void integrate(double offset, double velocity, double dt, double gravityOnAxis,
               const SolverParams& params, double& outOffset, double& outVelocity) {
    // Classic RK4. Euler is tempting and wrong here: a stiff spring integrated
    // with Euler gains energy every step and the chain detonates. RK4 costs four
    // force evaluations and stays stable across the range of stiffness values
    // animators actually reach for.
    const double x1 = offset;
    const double v1 = velocity;
    const double a1 = acceleration(x1, v1, gravityOnAxis, params);

    const double x2 = offset + 0.5 * v1 * dt;
    const double v2 = velocity + 0.5 * a1 * dt;
    const double a2 = acceleration(x2, v2, gravityOnAxis, params);

    const double x3 = offset + 0.5 * v2 * dt;
    const double v3 = velocity + 0.5 * a2 * dt;
    const double a3 = acceleration(x3, v3, gravityOnAxis, params);

    const double x4 = offset + v3 * dt;
    const double v4 = velocity + a3 * dt;
    const double a4 = acceleration(x4, v4, gravityOnAxis, params);

    outOffset = offset + (dt / 6.0) * (v1 + 2.0 * v2 + 2.0 * v3 + v4);
    outVelocity = velocity + (dt / 6.0) * (a1 + 2.0 * a2 + 2.0 * a3 + a4);
}

namespace {

/// Gravity resolved into a world vector, or zero when it is switched off.
Vec3 gravityVector(const SolverParams& params) {
    if (params.gravity == 0.0) {
        return Vec3();
    }
    return normalized(params.gravityDirection) * params.gravity;
}

}  // namespace

int substepCount(double dt, const SolverParams& params) {
    if (params.mass <= 0.0 || params.stiffness <= 0.0 || dt <= 0.0) {
        return 1;
    }
    const double omega = std::sqrt(params.stiffness / params.mass);
    const double steps = std::ceil((omega * dt) / kMaxOmegaStep);
    if (steps < 1.0) {
        return 1;
    }
    if (steps > static_cast<double>(kMaxSubsteps)) {
        return kMaxSubsteps;
    }
    return static_cast<int>(steps);
}

namespace {

/// One raw step, small enough to be stable. Called substepCount() times.
State stepOnce(const State& current, const Vec3& goal, double dt, const SolverParams& params);

}  // namespace

State step(const State& current, const Vec3& goal, double dt, const SolverParams& params) {
    // Three cases, not two. Treating dt == 0 as a reset is the bug that made
    // this node useless under Cached Playback: Maya restores a cached node's
    // state for the frame it is ABOUT to evaluate, so dt comes out as exactly
    // zero, and snapping to the goal there throws away a state that was already
    // correct. With the cache on, every level pinned itself to its own goal and
    // the chain sat perfectly still - the cached result differed from the truth
    // by 2.380374369 on a chain whose tip travels 2.380374369.
    //
    // It is wrong without the cache too. Any re-evaluation of the same frame
    // pops the chain to its goal, quietly, and always did.
    //
    // The caller is responsible for not handing us a state that was never
    // written; the node tracks that with stateInitialised.
    if (dt == 0.0) {
        return current;
    }
    if (dt < 0.0) {
        // Backwards. Integrating a spring backwards through time is not
        // something the maths supports, and the original's workaround - clamping
        // dt to [-1, 1] - is how it gave different results for the same frame
        // depending on where you came from. Restart instead.
        State reset;
        reset.position = goal;
        reset.velocity = Vec3();
        return reset;
    }

    // Subdivide rather than clamp. Clamping dt - which is what the tool this
    // replaces did - keeps the solver alive by quietly running time slower than
    // the scene, so the motion is wrong instead of explosive. Subdividing keeps
    // both the stability and the timing.
    const int steps = substepCount(dt, params);
    const double h = dt / static_cast<double>(steps);
    State state = current;
    for (int i = 0; i < steps; ++i) {
        state = stepOnce(state, goal, h, params);
    }
    return state;
}

namespace {

State stepOnce(const State& current, const Vec3& goal, double dt, const SolverParams& params) {
    State next;

    // dt <= 0 is a reset, not a step backwards. Snapping to the goal with no
    // velocity is the only sane answer: integrating a spring backwards through
    // time is not something the maths supports, and the original's workaround -
    // clamping dt to the range [-1, 1] - is how it ended up giving different
    // results for the same frame depending on where you came from.
    if (dt <= 0.0) {
        next.position = goal;
        next.velocity = Vec3();
        return next;
    }

    const Vec3 gravity = gravityVector(params);
    const Vec3 offset = current.position - goal;

    if (params.solveMode == SolveMode::Vector) {
        // One spring along the displacement. The restoring force points back
        // down the offset rather than being resolved per axis, so the motion
        // does not quietly favour world X, Y and Z.
        const double distance = length(offset);
        const Vec3 direction = normalized(offset);

        // Velocity along the offset is what the spring acts on; the rest is
        // carried so the joint can swing rather than only bounce in and out.
        const double radialVelocity = direction.x * current.velocity.x +
                                      direction.y * current.velocity.y +
                                      direction.z * current.velocity.z;
        const Vec3 tangentialVelocity = current.velocity - direction * radialVelocity;

        const double gravityAlong = direction.x * gravity.x + direction.y * gravity.y +
                                    direction.z * gravity.z;

        double newDistance = 0.0;
        double newRadialVelocity = 0.0;
        integrate(distance, radialVelocity, dt, gravityAlong, params, newDistance,
                  newRadialVelocity);

        const Vec3 newOffset = direction * newDistance;
        const Vec3 newVelocity = tangentialVelocity + direction * newRadialVelocity;

        if (params.updateMode == UpdateMode::Acceleration) {
            next.position = goal + (current.velocity - newVelocity);
        } else {
            next.position = goal + newOffset;
        }
        next.velocity = newVelocity;
        return next;
    }

    // Per axis: three independent scalar springs.
    Vec3 newOffset;
    Vec3 newVelocity;
    for (int axis = 0; axis < 3; ++axis) {
        double resultOffset = 0.0;
        double resultVelocity = 0.0;
        integrate(offset[axis], current.velocity[axis], dt, gravity[axis], params, resultOffset,
                  resultVelocity);
        newOffset[axis] = resultOffset;
        newVelocity[axis] = resultVelocity;
    }

    if (params.updateMode == UpdateMode::Acceleration) {
        next.position = goal + (current.velocity - newVelocity);
    } else {
        next.position = goal + newOffset;
    }
    next.velocity = newVelocity;
    return next;
}

}  // namespace

Vec3 cross(const Vec3& a, const Vec3& b) {
    return Vec3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x);
}

double dot(const Vec3& a, const Vec3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }

Vec3 Basis::axis(int index) const { return index == 0 ? x : (index == 1 ? y : z); }

void Basis::setAxis(int index, const Vec3& value) {
    if (index == 0) {
        x = value;
    } else if (index == 1) {
        y = value;
    } else {
        z = value;
    }
}

Basis aimBasis(const Vec3& from, const Vec3& to, const Vec3& up,
               const AimConvention& convention, const Basis& fallback) {
    const Vec3 delta = to - from;
    if (length(delta) < 1e-9) {
        // Two levels in the same place say nothing about direction.
        return fallback;
    }
    const Vec3 aim = normalized(delta) * convention.aimSign;

    Vec3 upHint = normalized(up) * convention.upSign;
    if (length(upHint) < 1e-9) {
        upHint = fallback.axis(convention.upAxis);
    }

    // The third axis, which is the one both of the others agree on.
    const int thirdAxis = 3 - convention.aimAxis - convention.upAxis;
    Vec3 side = cross(aim, upHint);
    if (length(side) < 1e-6) {
        // Up is parallel to the aim, so it cannot resolve the roll. Keep the
        // previous frame rather than inventing one and popping.
        return fallback;
    }
    side = normalized(side);
    const Vec3 trueUp = normalized(cross(side, aim));

    Basis basis;
    basis.setAxis(convention.aimAxis, aim);
    basis.setAxis(convention.upAxis, trueUp);
    // Sign chosen so the frame stays right-handed whichever axes were picked.
    const bool evenPermutation = ((convention.aimAxis + 1) % 3) == convention.upAxis;
    basis.setAxis(thirdAxis, evenPermutation ? side : side * -1.0);
    return basis;
}

Basis blendBasis(const Basis& from, const Basis& to, double weight) {
    if (weight >= 1.0) {
        return to;
    }
    if (weight <= 0.0) {
        return from;
    }
    Basis blended;
    blended.x = normalized(from.x + (to.x - from.x) * weight);
    blended.y = normalized(from.y + (to.y - from.y) * weight);
    // Re-orthogonalise rather than blending z too: independently interpolated
    // axes drift out of square, and a sheared "rotation" matrix makes a joint
    // scale as it turns.
    Vec3 z = cross(blended.x, blended.y);
    if (length(z) < 1e-9) {
        return weight < 0.5 ? from : to;
    }
    blended.z = normalized(z);
    blended.y = normalized(cross(blended.z, blended.x));
    return blended;
}

Vec3 eulerFromBasis(const Basis& basis) {
    // Rotation matrix rows are the basis axes. XYZ order, matching Maya's
    // default rotate order.
    const double m00 = basis.x.x, m01 = basis.x.y, m02 = basis.x.z;
    const double m10 = basis.y.x, m11 = basis.y.y, m12 = basis.y.z;
    const double m20 = basis.z.x, m21 = basis.z.y, m22 = basis.z.z;

    double rx, ry, rz;
    if (std::fabs(m02) < 1.0 - 1e-9) {
        ry = std::asin(-m02);
        rx = std::atan2(m12, m22);
        rz = std::atan2(m01, m00);
    } else {
        // Gimbal lock: one of the three angles is arbitrary, so pin roll at zero
        // and put the whole rotation in the other two.
        ry = m02 <= -1.0 + 1e-9 ? (3.14159265358979323846 / 2.0)
                                : -(3.14159265358979323846 / 2.0);
        rx = std::atan2(-m21, m11);
        rz = 0.0;
    }
    (void)m10;
    (void)m20;
    return Vec3(rx, ry, rz);
}

Vec3 clampToCone(const Vec3& origin, const Vec3& axis, const Vec3& position,
                 double limitDegrees) {
    if (limitDegrees >= 180.0) {
        return position;
    }
    const Vec3 offset = position - origin;
    const double distance = length(offset);
    if (distance < 1e-9) {
        return position;
    }
    const Vec3 direction = normalized(offset);
    const Vec3 coneAxis = normalized(axis);
    if (length(coneAxis) < 1e-9) {
        return position;
    }
    const double limit = std::max(0.0, limitDegrees) * 3.14159265358979323846 / 180.0;
    double cosAngle = dot(direction, coneAxis);
    cosAngle = cosAngle > 1.0 ? 1.0 : (cosAngle < -1.0 ? -1.0 : cosAngle);
    const double angle = std::acos(cosAngle);
    if (angle <= limit) {
        return position;
    }

    // Rotate the direction back toward the cone axis by the excess, in the plane
    // the two of them share. Distance from the origin is preserved, so a limit
    // clamps the swing without also shortening the chain.
    Vec3 side = cross(coneAxis, direction);
    if (length(side) < 1e-9) {
        return position;
    }
    side = normalized(side);
    const Vec3 inPlane = normalized(cross(side, coneAxis));
    const Vec3 clamped = coneAxis * std::cos(limit) + inPlane * std::sin(limit);
    return origin + clamped * distance;
}

}  // namespace mca
