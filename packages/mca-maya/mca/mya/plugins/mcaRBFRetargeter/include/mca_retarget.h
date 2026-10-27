// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// Deformation transfer: rebuild one mesh's blendshapes on another mesh that has
// the same topology but different proportions. No Maya in here, so it can be
// tested off-DCC.
//
// How it works
// ------------
// Pick some SOLVER POINTS on the source mesh. Build the dense matrix of the
// distance between every pair of them, solve it against where those same points
// sit on the TARGET mesh, and you have a function that maps "somewhere on the
// source" to "the matching place on the target". Push every vertex of every
// blendshape through it.
//
// The kernel is the raw distance - a linear RBF. For deformation transfer that
// is the standard choice and it is why the tool needs no falloff to tune.
//
// What this fixes in the tool it replaces
// ---------------------------------------
// **It was cubic, and nothing said so.** With no solver points chosen it used
// EVERY vertex: a 20,000-vertex head meant a 20,000 x 20,000 dense matrix -
// 3.2 GB - and a factorisation of about 10^12 operations. There was no guard, no
// warning, and the count it was about to use went to std::cout, which on Windows
// goes to a console nobody has open. `maxSolverPoints` refuses that up front and
// says what it would have cost.
//
// **It was single-threaded.** Its header defined RELEASE_OPENMP and its redoIt
// called MThreadUtils::syncNumOpenMPThreads(), and there was not one `#pragma
// omp` in the source. Evaluating is independent per vertex, so it parallelises
// exactly.
//
// **It could not tell a bad point set from a good one.** partialPivLu() with no
// rank test: two coincident solver points - easy on a mesh with merged vertices
// - produced silent garbage. Here the rank is checked and reported, and
// `regularisation` is the way out.
//
// **It could not reproduce a plain move.** See `affineTerm` below.

#ifndef MCA_RETARGET_H
#define MCA_RETARGET_H

#include <string>
#include <vector>

namespace mca {

struct Vec3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;

    Vec3() = default;
    Vec3(double inX, double inY, double inZ) : x(inX), y(inY), z(inZ) {}
};

struct RetargetOptions {
    /// Added to the matrix diagonal. 0 passes exactly through every solver
    /// point; a small value trades that for stability and is the way out when
    /// two solver points sit on top of each other.
    double regularisation = 0.0;

    /// Points spread over a bounding sphere, the source's paired to the
    /// target's, so the solve has something outside the mesh to push against
    /// and does not have to extrapolate wildly at the silhouette. 0 turns it
    /// off; the tool this replaces hard-coded 300 and called it
    /// "static_sphere".
    int sphereSamples = 0;

    /// Refuse a solve above this many points rather than quietly allocating a
    /// matrix nobody can hold. 0 removes the guard.
    int maxSolverPoints = 5000;

    /// Add a linear polynomial term to the system.
    ///
    /// A linear RBF on its own cannot reproduce an affine map away from its
    /// solver points - so if the target is simply the source moved, scaled or
    /// rotated, the result drifts between the points it was given. Augmenting
    /// the system with [1, x, y, z] fixes that exactly, which is the standard
    /// treatment and costs four extra rows.
    ///
    /// The tool this replaces did not do it. Left on by default here because
    /// two heads of different proportions differ by roughly an affine transform
    /// plus detail, which is precisely the case it repairs - but it does change
    /// results, so it can be turned off to reproduce the old behaviour.
    bool affineTerm = true;
};

struct RetargetReport {
    /// How many points the solve actually used, spheres included.
    int solverPoints = 0;
    /// True when the matrix was rank deficient - solver points the solve cannot
    /// tell apart. The answer is still produced, by least squares.
    bool degenerate = false;
    /// What the dense matrix cost, so the number can be put in front of someone
    /// before they wait for it.
    double matrixMegabytes = 0.0;
};

/// Evenly spread points over a sphere, by the golden angle.
///
/// Same distribution the original used, which was already right - an even
/// spread matters here because clumped anchors make the matrix worse
/// conditioned for no benefit.
std::vector<Vec3> pointsOnSphere(int count, const Vec3& centre, const Vec3& scale);

/// The centre and radius of a set of points.
void boundingSphere(const std::vector<Vec3>& points, Vec3& centre, double& radius);

class RetargetSolver {
public:
    /// Factorise the system.
    ///
    /// :param source: The source mesh's points.
    /// :param target: The target mesh's points. Must be the same length - the
    ///     two meshes have to share topology for any of this to mean anything.
    /// :param solverIds: Which points to solve on. Empty means all of them,
    ///     which is what makes the guard matter.
    /// :param error: Filled in when this returns false.
    /// :return: false rather than throwing - this is called from a Maya command.
    bool build(const std::vector<Vec3>& source,
               const std::vector<Vec3>& target,
               const std::vector<int>& solverIds,
               const RetargetOptions& options,
               std::string& error);

    /// Retarget a shape, in place.
    ///
    /// Parallel over points when OpenMP is available; every point is
    /// independent of every other.
    bool evaluate(std::vector<Vec3>& points) const;

    void clear();

    bool valid() const { return solverPoints_ > 0; }
    const RetargetReport& report() const { return report_; }

private:
    std::vector<Vec3> centres_;
    /// One weight per solver point, three columns.
    std::vector<double> weights_;
    /// The four affine coefficients, three columns. Empty when affineTerm is off.
    std::vector<double> affine_;
    int solverPoints_ = 0;
    RetargetReport report_;
};

}  // namespace mca

#endif  // MCA_RETARGET_H
