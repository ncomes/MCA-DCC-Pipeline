// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// The physics chain solver, with no Maya in it.
//
// Keeping the maths free of Maya types is the whole point of this header. The
// solver it replaces could only be exercised by loading a plug-in, opening a
// scene and scrubbing a timeline, which is why it was never tested. This one is
// a function from (state, goal, dt) to state, so it can be tested from a plain
// C++ main with no DCC at all.

#ifndef MCA_SOLVER_H
#define MCA_SOLVER_H

namespace mca {

/// A point in space, or a direction. Deliberately not MVector: this header is
/// compiled into the tests, where Maya does not exist.
struct Vec3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;

    Vec3() = default;
    Vec3(double x_, double y_, double z_) : x(x_), y(y_), z(z_) {}

    double operator[](int axis) const { return axis == 0 ? x : (axis == 1 ? y : z); }
    double& operator[](int axis) { return axis == 0 ? x : (axis == 1 ? y : z); }
};

Vec3 operator+(const Vec3& a, const Vec3& b);
Vec3 operator-(const Vec3& a, const Vec3& b);
Vec3 operator*(const Vec3& v, double s);
double length(const Vec3& v);
Vec3 normalized(const Vec3& v);

/// How the spring is solved.
enum class SolveMode {
    /// Three independent scalar springs, one per world axis. Cheaper, and it is
    /// what the tool this replaces did - so it is the default, because animators
    /// have tuned stiffness and damping values against its feel and those values
    /// should keep meaning the same thing.
    PerAxis = 0,
    /// One spring on the displacement vector. More physically correct: the
    /// restoring force points back along the offset rather than being resolved
    /// per axis, so the motion does not favour the world axes. Different feel,
    /// so it is opt-in rather than a silent improvement.
    Vector = 1
};

/// What the integrated result is applied to.
enum class UpdateMode {
    /// position = goal + integrated offset. The straightforward reading.
    Velocity = 0,
    /// position = goal + (velocity before - velocity after). Not physically
    /// motivated; it is a feel variant from the original and rigs will have been
    /// built against it, so it is carried over rather than corrected away.
    Acceleration = 1
};

/// Everything the solve needs for one joint on one step.
///
/// These are the resolved per-joint values - if a ramp is driving stiffness
/// along the chain, the ramp has already been sampled by the time it gets here.
/// The solver has no idea ramps exist.
struct SolverParams {
    double mass = 1.0;
    double stiffness = 0.5;

    /// As a ratio of critical damping, not a raw coefficient: 0 oscillates
    /// forever, 1 returns to the goal without overshooting. This
    /// parameterisation is inherited deliberately - it means a damping value
    /// keeps its meaning when mass or stiffness changes, which a raw
    /// coefficient does not.
    double damping = 0.5;

    double gravity = 0.0;
    Vec3 gravityDirection = Vec3(0.0, -1.0, 0.0);

    SolveMode solveMode = SolveMode::PerAxis;
    UpdateMode updateMode = UpdateMode::Velocity;
};

/// What carries from one frame to the next.
///
/// In the node this lives in attributes rather than on the instance, so that
/// Cached Playback can store and restore it. Here it is just a value.
struct State {
    Vec3 position;
    Vec3 velocity;
};

/// The damping coefficient a ratio of critical damping works out to.
///
/// critical = 2 * m * sqrt(k / m), so a ratio of 1.0 is exactly critical.
/// Returns 0 for a non-positive mass or stiffness rather than producing a NaN,
/// because a stiffness of 0 is a legitimate way to switch a joint off.
double dampingCoefficient(double mass, double stiffness, double dampingRatio);

/// Acceleration of the spring at a given offset and velocity, on one axis.
///
/// The classic mass-spring-damper, ma + cv + kx = 0, rearranged for a:
///
///     a = (-k*x - c*v) / m  + g
///
/// x is the offset from the goal, so the force always pulls back toward the
/// animation.
double acceleration(double offset, double velocity, double gravityOnAxis,
                    const SolverParams& params);

/// One RK4 step of a scalar spring.
///
/// Fourth-order Runge-Kutta rather than Euler because a stiff spring integrated
/// with Euler gains energy and explodes. Writes the new offset and velocity.
void integrate(double offset, double velocity, double dt, double gravityOnAxis,
               const SolverParams& params, double& outOffset, double& outVelocity);

/// Largest omega*h an RK4 step stays stable at, with margin.
///
/// RK4 on a spring is only stable while the step is small relative to the
/// spring's period. Maya measures dt in FRAMES, so dt is typically 1.0 - and at
/// a stiffness of 8 with unit mass, omega*dt is about 2.83, past the limit. The
/// chain does not wobble at that point, it detonates: measured at 124,117 units
/// from a goal 10 away.
constexpr double kMaxOmegaStep = 0.5;

/// Most substeps a single frame will ever be broken into.
///
/// Bounds the cost of an absurd stiffness rather than letting one slider hang
/// Maya. At the cap the solve is merely damped rather than exact, which is a
/// better failure than a hang or an explosion.
constexpr int kMaxSubsteps = 64;

/// How many substeps this frame needs to stay stable.
int substepCount(double dt, const SolverParams& params);

/// Advance one joint by one step.
///
/// @param current   Where the simulation was.
/// @param goal      Where the animation says this joint should be now.
/// @param dt        Timestep in frames. Zero or negative returns the goal
///                  unchanged with no velocity, which is what a reset means.
/// @param params    Resolved per-joint parameters.
/// @return The new simulated state.
State step(const State& current, const Vec3& goal, double dt, const SolverParams& params);

/// Cross product.
Vec3 cross(const Vec3& a, const Vec3& b);

/// Dot product.
double dot(const Vec3& a, const Vec3& b);

/// An orthonormal frame. Rows of a rotation matrix, in order x, y, z.
struct Basis {
    Vec3 x = Vec3(1.0, 0.0, 0.0);
    Vec3 y = Vec3(0.0, 1.0, 0.0);
    Vec3 z = Vec3(0.0, 0.0, 1.0);

    /// The axis at `index`, 0 = x.
    Vec3 axis(int index) const;
    void setAxis(int index, const Vec3& value);
};

/// Which way a level points, and which way is up.
///
/// Rigs disagree about this - joints usually aim down X, but not always, and a
/// chain built the other way round twists. Two indices and two signs cover every
/// convention without a special case per rig.
struct AimConvention {
    int aimAxis = 0;      ///< 0 = x, 1 = y, 2 = z
    double aimSign = 1.0;
    int upAxis = 1;
    double upSign = 1.0;
};

/// Orientation that points `from` at `to`, with `up` resolving the roll.
///
/// Gram-Schmidt, with the degenerate cases handled rather than left to produce
/// NaNs: a zero-length aim (two levels in the same place) and an up vector
/// parallel to the aim both fall back to `fallback`, because a frame that is
/// merely stale is far better than one full of NaNs - a NaN here spreads to
/// every level below it and the whole chain disappears.
Basis aimBasis(const Vec3& from, const Vec3& to, const Vec3& up,
               const AimConvention& convention, const Basis& fallback);

/// Blend between two orientations.
///
/// Nlerp on the axes rather than a true slerp: at the weights a chain actually
/// uses the difference is invisible, and it cannot produce the sign-flip
/// artefacts a naive quaternion lerp does when two frames are far apart.
Basis blendBasis(const Basis& from, const Basis& to, double weight);

/// Euler angles in radians, XYZ order, from a basis.
Vec3 eulerFromBasis(const Basis& basis);

/// Clamp `position` into a cone of `limitDegrees` around `axis` from `origin`.
///
/// Returns the clamped position. A limit of 180 or more is no limit at all.
Vec3 clampToCone(const Vec3& origin, const Vec3& axis, const Vec3& position,
                 double limitDegrees);

}  // namespace mca

#endif  // MCA_SOLVER_H
