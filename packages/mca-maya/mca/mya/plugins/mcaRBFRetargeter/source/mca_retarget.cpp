// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_retarget.h"

#include <algorithm>
#include <cmath>
#include <limits>

#include <Eigen/Dense>

#include "mca_parallel.h"

namespace mca {

namespace {

double distance(const Vec3& a, const Vec3& b) {
    const double dx = a.x - b.x;
    const double dy = a.y - b.y;
    const double dz = a.z - b.z;
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

}  // namespace

std::vector<Vec3> pointsOnSphere(int count, const Vec3& centre, const Vec3& scale) {
    std::vector<Vec3> points;
    if (count <= 0) {
        return points;
    }
    points.reserve(static_cast<std::size_t>(count));

    const double total = static_cast<double>(count);
    const double pi = 3.14159265358979323846;
    // The golden angle. An even spread matters: clumped anchors make the matrix
    // worse conditioned without adding any information.
    const double increment = pi * (3.0 - std::sqrt(5.0));
    const double step = 2.0 / total;

    for (int index = 0; index < count; ++index) {
        const double y = index * step - 1.0 + (step / 2.0);
        const double radius = std::sqrt(std::max(0.0, 1.0 - y * y));
        const double phi = index * increment;
        points.push_back(Vec3(centre.x + scale.x * std::cos(phi) * radius,
                              centre.y + scale.y * y,
                              centre.z + scale.z * std::sin(phi) * radius));
    }
    return points;
}

void boundingSphere(const std::vector<Vec3>& points, Vec3& centre, double& radius) {
    centre = Vec3();
    radius = 0.0;
    if (points.empty()) {
        return;
    }

    Vec3 low(std::numeric_limits<double>::max(), std::numeric_limits<double>::max(),
             std::numeric_limits<double>::max());
    Vec3 high(-std::numeric_limits<double>::max(), -std::numeric_limits<double>::max(),
              -std::numeric_limits<double>::max());
    for (const Vec3& point : points) {
        low.x = std::min(low.x, point.x);
        low.y = std::min(low.y, point.y);
        low.z = std::min(low.z, point.z);
        high.x = std::max(high.x, point.x);
        high.y = std::max(high.y, point.y);
        high.z = std::max(high.z, point.z);
    }

    centre = Vec3(0.5 * (low.x + high.x), 0.5 * (low.y + high.y), 0.5 * (low.z + high.z));
    for (const Vec3& point : points) {
        radius = std::max(radius, distance(point, centre));
    }
}

void RetargetSolver::clear() {
    centres_.clear();
    weights_.clear();
    affine_.clear();
    solverPoints_ = 0;
    report_ = RetargetReport();
}

bool RetargetSolver::build(const std::vector<Vec3>& source,
                           const std::vector<Vec3>& target,
                           const std::vector<int>& solverIds,
                           const RetargetOptions& options,
                           std::string& error) {
    clear();

    if (source.empty()) {
        error = "The source mesh has no points.";
        return false;
    }
    if (source.size() != target.size()) {
        error = "The source and target meshes have different vertex counts (" +
                std::to_string(source.size()) + " and " + std::to_string(target.size()) +
                "). They must share topology.";
        return false;
    }

    // Which points to solve on. Empty means all of them - the setting that made
    // the original quietly attempt a matrix the size of the mesh squared.
    std::vector<int> ids = solverIds;
    if (ids.empty()) {
        ids.resize(source.size());
        for (std::size_t i = 0u; i < ids.size(); ++i) {
            ids[i] = static_cast<int>(i);
        }
    }
    for (int id : ids) {
        if (id < 0 || static_cast<std::size_t>(id) >= source.size()) {
            error = "Solver point " + std::to_string(id) + " is not a vertex of a mesh "
                    "with " + std::to_string(source.size()) + " points.";
            return false;
        }
    }

    std::vector<Vec3> centres;
    std::vector<Vec3> destinations;
    centres.reserve(ids.size());
    destinations.reserve(ids.size());
    for (int id : ids) {
        centres.push_back(source[static_cast<std::size_t>(id)]);
        destinations.push_back(target[static_cast<std::size_t>(id)]);
    }

    // Anchors on a bounding sphere: the source's sphere paired to the target's,
    // so the solve has something outside the mesh to push against instead of
    // extrapolating at the silhouette.
    if (options.sphereSamples > 0) {
        Vec3 sourceCentre;
        Vec3 targetCentre;
        double sourceRadius = 0.0;
        double targetRadius = 0.0;
        boundingSphere(source, sourceCentre, sourceRadius);
        boundingSphere(target, targetCentre, targetRadius);

        const Vec3 sourceScale(sourceRadius, sourceRadius, sourceRadius);
        const Vec3 targetScale(targetRadius, targetRadius, targetRadius);
        const std::vector<Vec3> sourceSphere =
            pointsOnSphere(options.sphereSamples, sourceCentre, sourceScale);
        const std::vector<Vec3> targetSphere =
            pointsOnSphere(options.sphereSamples, targetCentre, targetScale);
        centres.insert(centres.end(), sourceSphere.begin(), sourceSphere.end());
        destinations.insert(destinations.end(), targetSphere.begin(), targetSphere.end());
    }

    const std::size_t points = centres.size();
    report_.solverPoints = static_cast<int>(points);
    // A dense double matrix, plus the affine block when it is on.
    const std::size_t side = points + (options.affineTerm ? 4u : 0u);
    report_.matrixMegabytes =
        static_cast<double>(side) * static_cast<double>(side) * 8.0 / (1024.0 * 1024.0);

    if (options.maxSolverPoints > 0 &&
        points > static_cast<std::size_t>(options.maxSolverPoints)) {
        // Say the cost rather than attempting it. The original had no guard at
        // all, so asking for every vertex of a dense mesh meant a matrix of
        // gigabytes and a factorisation of roughly 10^12 operations, with the
        // only clue a line printed to a console nobody has open.
        error = "That would solve on " + std::to_string(points) + " points, which needs a " +
                std::to_string(static_cast<long long>(report_.matrixMegabytes)) +
                " MB matrix and grows as the cube of the count. Select fewer solver "
                "vertices - a few hundred well spread is usually better than thousands - "
                "or raise maxSolverPoints if you really mean it.";
        clear();
        report_.solverPoints = static_cast<int>(points);
        return false;
    }

    // --- the matrix ------------------------------------------------------------ //
    Eigen::MatrixXd matrix = Eigen::MatrixXd::Zero(static_cast<Eigen::Index>(side),
                                                   static_cast<Eigen::Index>(side));
    for (std::size_t i = 0u; i < points; ++i) {
        for (std::size_t j = i; j < points; ++j) {
            const double d = distance(centres[i], centres[j]);
            matrix(static_cast<Eigen::Index>(i), static_cast<Eigen::Index>(j)) = d;
            matrix(static_cast<Eigen::Index>(j), static_cast<Eigen::Index>(i)) = d;
        }
    }

    if (options.regularisation > 0.0) {
        for (std::size_t i = 0u; i < points; ++i) {
            matrix(static_cast<Eigen::Index>(i), static_cast<Eigen::Index>(i)) +=
                options.regularisation;
        }
    }

    // The polynomial block. Without it a linear RBF cannot reproduce an affine
    // map away from its solver points, so a target that is simply the source
    // moved comes back drifting in between.
    if (options.affineTerm) {
        for (std::size_t i = 0u; i < points; ++i) {
            const Eigen::Index row = static_cast<Eigen::Index>(i);
            const Eigen::Index base = static_cast<Eigen::Index>(points);
            matrix(row, base + 0) = 1.0;
            matrix(row, base + 1) = centres[i].x;
            matrix(row, base + 2) = centres[i].y;
            matrix(row, base + 3) = centres[i].z;
            matrix(base + 0, row) = 1.0;
            matrix(base + 1, row) = centres[i].x;
            matrix(base + 2, row) = centres[i].y;
            matrix(base + 3, row) = centres[i].z;
        }
    }

    Eigen::MatrixXd rhs = Eigen::MatrixXd::Zero(static_cast<Eigen::Index>(side), 3);
    for (std::size_t i = 0u; i < points; ++i) {
        rhs(static_cast<Eigen::Index>(i), 0) = destinations[i].x;
        rhs(static_cast<Eigen::Index>(i), 1) = destinations[i].y;
        rhs(static_cast<Eigen::Index>(i), 2) = destinations[i].z;
    }

    // Column-pivoting QR rather than the original's partialPivLu: it reports the
    // rank, so two solver points the solve cannot tell apart become something we
    // can say rather than a division by a pivot near zero.
    Eigen::ColPivHouseholderQR<Eigen::MatrixXd> decomposition(matrix);
    decomposition.setThreshold(1e-10);
    report_.degenerate = decomposition.rank() < static_cast<Eigen::Index>(side);

    const Eigen::MatrixXd solved = decomposition.solve(rhs);
    if (!solved.allFinite()) {
        error = "The solve did not converge. Two solver points are probably in the same "
                "place; move them apart or raise regularisation.";
        clear();
        return false;
    }

    centres_ = centres;
    solverPoints_ = static_cast<int>(points);
    weights_.resize(points * 3u);
    for (std::size_t i = 0u; i < points; ++i) {
        weights_[i * 3u + 0u] = solved(static_cast<Eigen::Index>(i), 0);
        weights_[i * 3u + 1u] = solved(static_cast<Eigen::Index>(i), 1);
        weights_[i * 3u + 2u] = solved(static_cast<Eigen::Index>(i), 2);
    }
    if (options.affineTerm) {
        affine_.resize(12u);
        for (std::size_t row = 0u; row < 4u; ++row) {
            for (std::size_t column = 0u; column < 3u; ++column) {
                affine_[row * 3u + column] =
                    solved(static_cast<Eigen::Index>(points + row),
                           static_cast<Eigen::Index>(column));
            }
        }
    }
    return true;
}

bool RetargetSolver::evaluate(std::vector<Vec3>& points) const {
    if (solverPoints_ <= 0) {
        return false;
    }

    const int count = static_cast<int>(points.size());
    const int centreCount = solverPoints_;
    const bool hasAffine = !affine_.empty();

    // Every point is independent of every other, which is what makes this worth
    // parallelising - and what the tool this replaces left on the table after
    // going to the trouble of setting OpenMP up and then never writing a pragma.
    //
    // This was a `#pragma omp parallel for` until mcaPoseSkinner established that
    // the devkit call which supposedly makes OpenMP safe inside Maya
    // (`MThreadUtils::syncNumOpenMPThreads()`) is a documented no-op, so nothing was
    // reconciling our VCOMP140 pool with Maya's TBB one. Nothing has ever faulted
    // here - this loop allocates nothing, touches no Eigen and writes only its own
    // index, which is none of the ingredients that made the pose skinner fault - so
    // this is hygiene rather than a fix. It costs nothing and it means no plug-in in
    // this tree brings a second parallel runtime into Maya's process.
    mca::parallelFor(count, 0, [&](int index) {
        const Vec3 point = points[static_cast<std::size_t>(index)];
        double x = 0.0;
        double y = 0.0;
        double z = 0.0;

        for (int i = 0; i < centreCount; ++i) {
            const double d = distance(point, centres_[static_cast<std::size_t>(i)]);
            x += d * weights_[static_cast<std::size_t>(i) * 3u + 0u];
            y += d * weights_[static_cast<std::size_t>(i) * 3u + 1u];
            z += d * weights_[static_cast<std::size_t>(i) * 3u + 2u];
        }

        if (hasAffine) {
            x += affine_[0] + affine_[3] * point.x + affine_[6] * point.y +
                 affine_[9] * point.z;
            y += affine_[1] + affine_[4] * point.x + affine_[7] * point.y +
                 affine_[10] * point.z;
            z += affine_[2] + affine_[5] * point.x + affine_[8] * point.y +
                 affine_[11] * point.z;
        }

        points[static_cast<std::size_t>(index)] = Vec3(x, y, z);
    }, nullptr);
    return true;
}

}  // namespace mca
