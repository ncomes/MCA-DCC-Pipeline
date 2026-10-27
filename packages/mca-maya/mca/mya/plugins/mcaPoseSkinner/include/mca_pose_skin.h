// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// Pose skinning: given a mesh that deforms - by blendshapes, by a sim, by any
// deformer at all - work out the joint weights that reproduce that deformation,
// and optionally the joint transforms as well. No Maya in here, so the maths can
// be tested off-DCC.
//
// How it works
// ------------
// A skinned vertex is a weighted sum of itself seen through each joint:
//
//     v'(pose) = SUM_j  w_j * ( v_rest * bindInverse_j * jointWorld_j(pose) )
//
// Everything on the right except w is known once you have a rest mesh, the posed
// meshes and the joints' transforms in each pose. So for one vertex, across every
// pose, that is an overdetermined linear system in w - and the constraints a
// skin weight has to satisfy (non-negative, summing to one, at most N of them
// non-zero) make it a non-negative least squares problem with a cardinality
// limit. Solve it per vertex and you have a skinCluster.
//
// When the joints are NOT already animated, the same relation is linear in the
// joint transforms for fixed weights, so the two solves alternate: weights,
// bones, weights, bones. That is the structure from Le and Deng's smooth
// skinning decomposition, and it is the right structure. What follows is our own
// implementation of it.
//
// What this fixes in the tool it replaces
// ---------------------------------------
// The reference is `skinningConverter`, and the algorithm in it is sound. These
// are the things that measurably cost accuracy, all of which are addressed below
// and asserted in tests/test_solver.cpp.
//
// **The answer depended on where the mesh sat in the world.** Its per-vertex
// system carried the rest position as an extra row - A's columns all equal to the
// rest point, b equal to the rest point - which is the sum-to-one constraint
// multiplied by the vertex's distance from the world origin. So the same mesh
// solved differently at the origin and at (0, 0, 1000): a character rigged where
// they stood got a different skin from one rigged at centre stage, and for a
// vertex exactly on the origin that row said nothing at all. Ours subtracts the
// target position from every column of A, which makes the fit exactly invariant
// to where the mesh is - see `solveVertexWeights`.
//
// **Influences were chosen once and never revisited.** It solved with every
// joint, took the largest `maxInfluences`, and re-solved on those. That first
// solve is made under a different constraint set than the final one, so the
// joints it ranks highest are not the best subset of that size. Dropping the
// smallest weight and re-solving, repeatedly, is the standard remedy and is
// measurably better - the numbers are in the test suite.
//
// **The reflection fix negated the wrong axis.** A weighted point fit can come
// back as a reflection rather than a rotation, and the closest rotation is
// recovered by flipping the singular vector belonging to the SMALLEST singular
// value. Negating the third column of the assembled matrix - which is what the
// original did - does give an orthogonal matrix with a positive determinant, so
// nothing complains, but it is not the closest rotation to the data unless the
// smallest singular value happens to be the third. See `fitTransform`.
//
// **Every weight was solved as if its neighbours did not exist.** Per-vertex NNLS
// is independent per vertex, so nothing stops two adjacent vertices picking
// different joint sets with similar error. It fits the poses you gave it and
// looks torn between them. `smoothing` adds the neighbourhood as a prior in the
// same solve rather than blurring afterwards.
//
// **It only ever reported error on the poses it fitted.** With enough joints that
// number always looks good, which is exactly when the result is worst on the
// poses you did not fit. `holdoutPoses` keeps some out of the fit and reports
// their error separately.
//
// **Nothing said where the error was.** One scalar for the whole mesh. Ours
// returns per-vertex and per-pose error, which is what makes a heat map possible.

#ifndef MCA_POSE_SKIN_H
#define MCA_POSE_SKIN_H

#include <functional>
#include <string>
#include <vector>

#include "mca_parallel.h"

namespace mca {

struct Vec3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;

    Vec3() = default;
    Vec3(double inX, double inY, double inZ) : x(inX), y(inY), z(inZ) {}
};

/// A 4x4 in Maya's convention: row vectors, so a point is transformed as
/// `p * m`, and translation lives in row 3. Kept as a plain array so this
/// header needs neither Maya nor Eigen.
struct Mat4 {
    double m[4][4] = {{1.0, 0.0, 0.0, 0.0},
                      {0.0, 1.0, 0.0, 0.0},
                      {0.0, 0.0, 1.0, 0.0},
                      {0.0, 0.0, 0.0, 1.0}};
};

/// Get Eigen ready to be called from several threads at once.
///
/// **This must happen on the main thread before any parallel region, and leaving it
/// out crashed Maya.** Eigen initialises some internals lazily - the cache-size
/// table its matrix products consult - and two threads reaching that at the same
/// time write through a pointer neither of them has set yet. The symptom is an
/// access violation writing to an address like 0x00000007, inside the plug-in,
/// minutes into a run that worked a dozen times before.
///
/// It was not the whole story - the same fault came back with this call in place,
/// and see `parallelFor` for what else was wrong - but it is a real hazard and the
/// call is cheap. It is still needed: Eigen is called from several threads here
/// whatever starts them.
///
/// `solvePoseSkin` calls this itself. It is exposed because any other entry point
/// that goes parallel has to call it too.
///
/// The tool this replaces called `Eigen::initParallel()` before every one of its
/// parallel loops, and we dropped the line while rewriting. Reading an algorithm
/// out of someone else's code and leaving the plumbing behind is exactly the risk
/// that carries.
void prepareParallel();

// `mca::parallelFor` lives in ../common/include/mca_parallel.h, shared with the
// other plug-ins in this tree. Its header explains why it is not OpenMP and
// where the thread cap comes from.

/// `p * m`, row-vector convention.
Vec3 transformPoint(const Vec3& point, const Mat4& matrix);

/// `a * b`, row-vector convention.
Mat4 multiply(const Mat4& a, const Mat4& b);

Mat4 inverse(const Mat4& matrix, bool* ok = nullptr);

struct PoseSkinInput {
    /// The mesh at rest, which is the pose the joints' bind matrices belong to.
    std::vector<Vec3> rest;

    /// The same mesh in every pose being fitted. `poses[f][v]`.
    std::vector<std::vector<Vec3>> poses;

    /// World-to-joint at the bind pose, one per joint.
    std::vector<Mat4> bindInverse;

    /// Joint-to-world in each pose. `jointWorld[f][j]`. When the bones are being
    /// solved this is the starting guess and the result carries the answer.
    std::vector<std::vector<Mat4>> jointWorld;

    /// Which vertices share an edge with which, used by `smoothing` and by the
    /// locality restriction. Empty means the solve has no idea what the mesh
    /// looks like, and both of those features switch themselves off.
    std::vector<std::vector<int>> neighbours;

    /// Per-vertex importance, 0 to 1. Empty means every vertex counts equally.
    /// A vertex at 0 is still solved - it just does not pull on the bone fit.
    std::vector<double> importance;

    /// Per-vertex restriction on which joints may be used, for honouring an
    /// existing skinCluster's influence sets or a hand-painted mask. Empty means
    /// every joint is a candidate everywhere.
    std::vector<std::vector<int>> candidates;

    // ---- additive mode ---------------------------------------------------- //
    //
    // Set these three together with `PoseSkinOptions::additive` to ADD joints to a
    // skin that already exists, rather than solving the whole skin. See that flag
    // for what the mode is for; these are what it needs to know.

    /// Where the EXISTING skin puts each vertex, per pose. `baseline[f][v]`.
    ///
    /// The residual `poses[f][v] - baseline[f][v]` is what the new joints have to
    /// account for, and it is zero wherever the existing skin already fits - which
    /// is why a cheek joint earns nothing on the back of the head.
    std::vector<std::vector<Vec3>> baseline;

    /// Where the donor influences put each vertex PER UNIT of donor weight, per
    /// pose. `donorPoint[f][v]`.
    ///
    /// Weight handed to a new joint comes out of the donors, so what a new joint
    /// changes is not where it puts the vertex but the difference between that and
    /// where the donors were putting it. That difference is the column of the
    /// system; this is the thing subtracted.
    std::vector<std::vector<Vec3>> donorPoint;

    /// How much weight the donors hold at each vertex - the most that can be taken.
    /// A vertex where this is zero can receive nothing, which is the mechanism that
    /// keeps the influences the user did NOT nominate exactly as they were.
    std::vector<double> donorWeight;
};

struct PoseSkinOptions {
    /// Most joints a single vertex may end up with. Game engines usually want 4,
    /// 8 or 12; Maya's own limit is what you set on the skinCluster.
    int maxInfluences = 8;

    /// How hard the weights are pushed to sum to one, relative to fitting the
    /// poses. It is a penalty rather than a hard constraint because a hard one
    /// makes the problem harder to solve than the accuracy is worth, and the
    /// result is normalised at the end anyway. 0 disables it, which is a way to
    /// see what it is buying.
    double affinity = 1.0;

    /// How hard each vertex's weights are pulled toward the average of its
    /// neighbours'. 0 is off and is the behaviour of the tool this replaces.
    /// Around 0.05 to 0.2 of the data term is the useful range; it trades error
    /// on the fitted poses for error everywhere else.
    double smoothing = 0.0;

    /// How many times to re-solve with the neighbourhood prior taken from the
    /// previous round. The prior needs weights to exist before it can be
    /// applied, so round one is always unsmoothed. Ignored when smoothing is 0.
    int smoothingRounds = 2;

    /// Drop the smallest weight and re-solve until `maxInfluences` is met,
    /// rather than ranking once and re-solving once.
    bool prunePerStep = true;

    /// Restrict each vertex to its N nearest joints, measured at rest. 0 is off.
    /// This is a locality prior: without one, two parts of a mesh that happen to
    /// move alike across the poses you sampled can end up sharing influences,
    /// and the giveaway is a hand that twitches when the other hand moves.
    int localityJoints = 0;

    /// Measure that nearness ACROSS THE SURFACE rather than through the air.
    ///
    /// The upper lip and the lower lip are a millimetre apart and on opposite sides
    /// of a hole; the chin and the tongue likewise. Straight-line distance says they
    /// are neighbours, so an upper-lip vertex is allowed a lower-lip joint and the
    /// mouth fights itself on a jaw shape. Walking the mesh's own edges says what
    /// the model says.
    ///
    /// It also stops influence leaking between separate pieces of geometry
    /// altogether: eyeballs, teeth and a tongue modelled as their own shells are
    /// unreachable from a face joint's seed vertex, so they cannot be weighted to
    /// one. That is usually what you want and occasionally not - a jaw joint that is
    /// SUPPOSED to carry a separate tongue mesh needs this off, or the tongue solved
    /// on its own.
    ///
    /// Needs `neighbours`. Ignored without them.
    bool geodesicLocality = false;

    /// Weight/bone alternations. 1 solves weights only, which is what you want
    /// when the joints are already animated the way they should be.
    int maxIterations = 1;

    /// Solve joint transforms as well as weights. Requires maxIterations > 1 to
    /// do anything.
    bool solveBones = false;

    /// Bones are rigid (rotate and translate only) or free to scale and shear.
    bool rigidBones = true;

    /// Move each joint's bind position to the centroid of what it ends up
    /// weighting, between iterations.
    bool updateBindPose = false;

    /// Stop when an iteration improves the fit by less than this fraction.
    /// Negative runs every iteration.
    double improvementBreak = 0.01;

    /// Weights below this are dropped and the rest renormalised.
    double weightFloor = 1e-5;

    /// Pose indices kept OUT of the fit and reported on separately, so the
    /// result says how it does on poses it has not seen. Empty means no
    /// validation, and then `holdoutRms` comes back negative.
    std::vector<int> holdoutPoses;

    /// Iteration cap inside the non-negative least squares solve. 0 picks a
    /// sensible multiple of the column count.
    int nnlsIterations = 0;

    /// Add joints to an existing skin instead of solving the whole skin.
    ///
    /// **The problem this exists for.** The ordinary solve fits absolute position
    /// with the weights constrained to sum to one, so every vertex must be explained
    /// by the joints it was given. Give it a left-cheek joint and the back of the
    /// head also has to reach 1.0 from the candidates available - so the cheek joint
    /// gets weight on the back of the head. That is the objective doing what it was
    /// told, not a bug, and no amount of locality fixes it.
    ///
    /// In additive mode the solve fits the RESIDUAL - the difference between where
    /// the existing skin already puts the vertex and where the pose actually is - and
    /// takes the weight it needs out of nominated donor influences:
    ///
    ///     new position = baseline + sum(t_j * (T_j(rest) - donorPoint))
    ///                    subject to sum(t_j) <= donorWeight
    ///
    /// Three things follow, none of them a heuristic. The back of the head gets
    /// nothing because the residual there is zero and there is nothing to earn.
    /// Influences that are not donors come out bit-identical, because weight can
    /// only leave a donor. And the weights still sum to exactly one, because what
    /// the new joints gain the donors lose - so nothing is renormalised and nothing
    /// drifts.
    ///
    /// Requires `PoseSkinInput::baseline`, `donorPoint` and `donorWeight`.
    ///
    /// `affinity` is ignored in this mode: the constraint is a cap, not an equality.
    bool additive = false;

    /// Threads. 0 asks the hardware and caps at 8 - see `parallelFor` for the
    /// measurements behind that cap and the open race it guards. 1 forces
    /// single-threaded, which is how the determinism check is written. Any explicit
    /// number is used exactly as given.
    int threads = 0;

    /// Asked between iterations, and between smoothing rounds, whether to stop.
    ///
    /// Checked only at those boundaries on purpose: the weights are complete and
    /// consistent at every one of them, so a cancelled solve hands back a usable
    /// answer rather than a half-solved mesh. Inside the per-vertex loop there is
    /// no such guarantee. The Maya side wires this to the escape key.
    std::function<bool()> interrupted;

    /// Told the iteration number and its rms as each one finishes, so a caller can
    /// say something while a long solve runs. A solve that prints nothing for two
    /// minutes is indistinguishable from a hung one, and people reach for the task
    /// manager.
    std::function<void(int, double)> progress;
};

struct PoseSkinResult {
    /// Per vertex, the joints it uses and their weights. Same length, sorted by
    /// descending weight, summing to 1.
    std::vector<std::vector<int>> vertexJoints;
    std::vector<std::vector<double>> vertexWeights;

    /// The joint transforms, updated when the bones were solved.
    std::vector<std::vector<Mat4>> jointWorld;
    std::vector<Mat4> bindInverse;

    /// Worst distance, per vertex, between the skinned result and the pose, over
    /// the poses that were fitted. This is the heat map.
    std::vector<double> vertexError;

    /// RMS distance per pose, over every vertex. Indexed like `poses`, so a
    /// held-out pose's entry is filled in too.
    std::vector<double> poseError;

    /// Over the fitted poses, in scene units.
    double rms = 0.0;
    double worst = 0.0;

    /// Over the held-out poses. Negative when there were none.
    double holdoutRms = -1.0;
    double holdoutWorst = -1.0;

    /// RMS after each weight solve, so the caller can show convergence.
    std::vector<double> iterationRms;
    int iterationsDone = 0;

    /// Joints whose transform could not be fitted because the vertices weighting
    /// them do not span three dimensions - a bone holding a straight line or a
    /// single point. Their transform is left as it was. Reported rather than
    /// skipped silently, because the usual cause is too many joints for the
    /// deformation and the fix is to ask for fewer.
    std::vector<int> degenerateJoints;

    /// Vertices that came out of the solve with nothing on them, which means the
    /// candidate restriction left them no usable joint.
    ///
    /// In additive mode this is NOT filled: a vertex the new joints do not affect is
    /// the expected answer there, not a problem to report.
    std::vector<int> unweightedVertices;

    /// Additive mode: vertices where the new joints wanted more weight than the
    /// donors had, and were scaled back to fit.
    ///
    /// Reported because it is diagnostic rather than fatal. A handful is ordinary;
    /// a lot of them usually means the wrong donor was nominated - the deformation
    /// being fitted needs weight from an influence that was not offered.
    int cappedVertices = 0;

    /// Set when the caller asked it to stop. Everything above is still valid - it
    /// is the answer after however many iterations ran.
    bool cancelled = false;

    std::string message;
};

/// Fit weights, and bones when asked to.
///
/// :return: false with `error` set when the inputs do not describe a solvable
///     problem. A solvable problem that fits badly is a success with a large
///     `rms` - that is a fact about the input, not an error.
bool solvePoseSkin(const PoseSkinInput& input, const PoseSkinOptions& options,
                   PoseSkinResult& result, std::string& error);

/// Where a skinned vertex ends up. The definition the solve is fitting, exposed
/// so tests can check the fit rather than trusting it.
Vec3 skinPoint(const Vec3& rest, const std::vector<int>& joints,
               const std::vector<double>& weights, const std::vector<Mat4>& bindInverse,
               const std::vector<Mat4>& jointWorld);

/// Non-negative least squares: the smallest `x` with every element >= 0 that
/// minimises ||Ax - b||. Lawson and Hanson's active set method.
///
/// Exposed with plain arrays rather than Eigen types so that it can be tested
/// without Eigen in the test's include path, and because it is the engine the
/// whole tool rides on - it deserves checks of its own.
///
/// :param a: Row-major, `rows` by `columns`.
/// :param maxIterations: 0 picks 10 times the column count.
/// :return: false when the iteration cap was hit, with `x` holding the best
///     answer so far. Not fatal, and the caller usually carries on.
bool solveNonNegative(const std::vector<double>& a, int rows, int columns,
                      const std::vector<double>& b, std::vector<double>& x,
                      int maxIterations = 0, double tolerance = 1e-10);

/// The weighted transform that best takes `from` to `to`.
///
/// :param weights: Per-point. Empty weights every point equally.
/// :param rigid: true gives the closest rotation plus translation (Kabsch, with
///     the reflection case handled by flipping the singular vector belonging to
///     the smallest singular value). false allows scale and shear.
/// :param degenerate: Set when the points do not span three dimensions, in which
///     case the answer is still the best available but is not unique.
/// :return: false when there is nothing to fit at all - no points, or no weight.
bool fitTransform(const std::vector<Vec3>& from, const std::vector<Vec3>& to,
                  const std::vector<double>& weights, bool rigid, Mat4& out,
                  bool* degenerate = nullptr);

}  // namespace mca

#endif  // MCA_POSE_SKIN_H
