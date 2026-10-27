// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// The pose skinning maths. See include/mca_pose_skin.h for what it does and why
// it is shaped this way.

#include "mca_pose_skin.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <sstream>

#include <Eigen/Dense>

namespace mca {
namespace {

using Eigen::MatrixXd;
using Eigen::VectorXd;

constexpr double kTiny = 1e-12;

Eigen::Matrix4d toEigen(const Mat4& matrix) {
    Eigen::Matrix4d out;
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            out(row, column) = matrix.m[row][column];
        }
    }
    return out;
}

Mat4 fromEigen(const Eigen::Matrix4d& matrix) {
    Mat4 out;
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            out.m[row][column] = matrix(row, column);
        }
    }
    return out;
}

}  // namespace

void prepareParallel() {
    // Once per process is enough, and it has to be here rather than inside the
    // parallel region: the whole point is that it happens before any worker thread
    // exists. The static makes repeat calls free.
    static const bool ready = []() {
        Eigen::initParallel();

        // And then tell Eigen to stay on one thread.
        //
        // We parallelise per vertex, which is the right level - thousands of
        // independent problems. Eigen left to its own devices ALSO parallelises,
        // inside each of those, and nested OpenMP is both slower and not
        // deterministic: how a product is split between threads decides the order
        // the sums happen in, and floating-point addition is not associative.
        //
        // Measured on a 173-pose face: with Eigen free to thread, one thread and
        // eight gave weights differing by 1.8e-10 and an rms differing in the
        // fourteenth digit. Harmless in itself, and it means "the same input gives
        // the same answer" is not quite true - which is a property worth having
        // exactly, because the day it matters is the day someone is comparing two
        // runs to find something else.
        Eigen::setNbThreads(1);
        return true;
    }();
    (void)ready;
}

Vec3 transformPoint(const Vec3& point, const Mat4& matrix) {
    return Vec3(point.x * matrix.m[0][0] + point.y * matrix.m[1][0] +
                    point.z * matrix.m[2][0] + matrix.m[3][0],
                point.x * matrix.m[0][1] + point.y * matrix.m[1][1] +
                    point.z * matrix.m[2][1] + matrix.m[3][1],
                point.x * matrix.m[0][2] + point.y * matrix.m[1][2] +
                    point.z * matrix.m[2][2] + matrix.m[3][2]);
}

Mat4 multiply(const Mat4& a, const Mat4& b) {
    Mat4 out;
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            double sum = 0.0;
            for (int k = 0; k < 4; ++k) {
                sum += a.m[row][k] * b.m[k][column];
            }
            out.m[row][column] = sum;
        }
    }
    return out;
}

Mat4 inverse(const Mat4& matrix, bool* ok) {
    const Eigen::Matrix4d source = toEigen(matrix);
    Eigen::Matrix4d inverted;
    double determinant = 0.0;
    bool invertible = false;
    source.computeInverseAndDetWithCheck(inverted, determinant, invertible);
    if (ok) {
        *ok = invertible;
    }
    if (!invertible) {
        // A singular joint matrix is a scale of zero somewhere in the rig. Hand
        // back the identity rather than NaNs, so the caller's error stays finite
        // and points at the joint instead of at the whole solve.
        return Mat4();
    }
    return fromEigen(inverted);
}

Vec3 skinPoint(const Vec3& rest, const std::vector<int>& joints,
               const std::vector<double>& weights, const std::vector<Mat4>& bindInverse,
               const std::vector<Mat4>& jointWorld) {
    Vec3 out;
    const std::size_t count = std::min(joints.size(), weights.size());
    for (std::size_t index = 0; index < count; ++index) {
        const int joint = joints[index];
        if (joint < 0 || joint >= static_cast<int>(bindInverse.size()) ||
            joint >= static_cast<int>(jointWorld.size())) {
            continue;
        }
        const Vec3 moved =
            transformPoint(rest, multiply(bindInverse[joint], jointWorld[joint]));
        out.x += weights[index] * moved.x;
        out.y += weights[index] * moved.y;
        out.z += weights[index] * moved.z;
    }
    return out;
}

bool solveNonNegative(const std::vector<double>& a, int rows, int columns,
                      const std::vector<double>& b, std::vector<double>& x,
                      int maxIterations, double tolerance) {
    x.assign(static_cast<std::size_t>(std::max(columns, 0)), 0.0);
    if (rows <= 0 || columns <= 0) {
        return false;
    }
    if (a.size() < static_cast<std::size_t>(rows) * static_cast<std::size_t>(columns) ||
        b.size() < static_cast<std::size_t>(rows)) {
        return false;
    }
    if (maxIterations <= 0) {
        maxIterations = 10 * columns;
    }

    const Eigen::Map<const Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic,
                                         Eigen::RowMajor>>
        matrix(a.data(), rows, columns);
    const Eigen::Map<const VectorXd> target(b.data(), rows);

    // Lawson and Hanson's active set method, run on the normal equations.
    //
    // The inner step of the algorithm is an unconstrained least squares fit on
    // whichever columns are currently free. Done on A directly that is a
    // factorisation of a (rows x free) matrix every time round; done on
    // G = A'A and c = A'b it is a (free x free) solve, and G and c are built
    // once. That is Bro and de Jong's restructuring and it gives the same
    // answer - what it costs is conditioning, since forming A'A squares the
    // condition number, which is why the free-set solve below is an LDLT with a
    // fallback rather than a bare inverse.
    //
    // It matters here because the callers run one of these per vertex: the
    // restructuring is the difference between a mesh solving in seconds and in
    // minutes.
    const MatrixXd gram = matrix.transpose() * matrix;
    const VectorXd correlation = matrix.transpose() * target;

    std::vector<bool> free(static_cast<std::size_t>(columns), false);
    // Columns given up on. Without this list the "numerically stuck" escape at
    // the bottom of the inner loop hands the same column straight back to the
    // selection step and the two spin until the iteration cap - which reports a
    // failure on a problem that was nearly solved.
    std::vector<bool> abandoned(static_cast<std::size_t>(columns), false);
    VectorXd solution = VectorXd::Zero(columns);
    VectorXd gradient = correlation;

    const double scale = gram.diagonal().maxCoeff();
    const double gradientTolerance = tolerance * std::max(scale, 1.0);

    std::vector<int> freeList;
    freeList.reserve(static_cast<std::size_t>(columns));

    auto solveFreeSet = [&](VectorXd& candidate) {
        candidate = VectorXd::Zero(columns);
        freeList.clear();
        for (int column = 0; column < columns; ++column) {
            if (free[static_cast<std::size_t>(column)]) {
                freeList.push_back(column);
            }
        }
        if (freeList.empty()) {
            return;
        }
        const int count = static_cast<int>(freeList.size());
        MatrixXd subGram(count, count);
        VectorXd subCorrelation(count);
        for (int row = 0; row < count; ++row) {
            subCorrelation(row) = correlation(freeList[static_cast<std::size_t>(row)]);
            for (int column = 0; column < count; ++column) {
                subGram(row, column) = gram(freeList[static_cast<std::size_t>(row)],
                                            freeList[static_cast<std::size_t>(column)]);
            }
        }
        VectorXd sub = subGram.ldlt().solve(subCorrelation);
        if (!sub.allFinite()) {
            // A rank-deficient free set: two joints moving identically across
            // every pose given, which is not a mistake, just an input with no
            // unique answer. Least squares through an SVD picks the smallest
            // one, which spreads the weight between them instead of picking
            // arbitrarily.
            sub = subGram.completeOrthogonalDecomposition().solve(subCorrelation);
        }
        for (int row = 0; row < count; ++row) {
            candidate(freeList[static_cast<std::size_t>(row)]) = sub(row);
        }
    };

    int iterations = 0;
    while (true) {
        // Pick the blocked column that would most reduce the residual.
        int best = -1;
        double bestGradient = gradientTolerance;
        for (int column = 0; column < columns; ++column) {
            if (free[static_cast<std::size_t>(column)] ||
                abandoned[static_cast<std::size_t>(column)]) {
                continue;
            }
            if (gradient(column) > bestGradient) {
                bestGradient = gradient(column);
                best = column;
            }
        }
        if (best < 0) {
            return true;
        }

        free[static_cast<std::size_t>(best)] = true;

        // Inner loop: keep the free set feasible.
        while (true) {
            if (++iterations > maxIterations) {
                for (int column = 0; column < columns; ++column) {
                    x[static_cast<std::size_t>(column)] = std::max(solution(column), 0.0);
                }
                return false;
            }

            VectorXd candidate;
            solveFreeSet(candidate);

            double worst = std::numeric_limits<double>::infinity();
            for (int column : freeList) {
                worst = std::min(worst, candidate(column));
            }
            if (freeList.empty()) {
                break;
            }
            if (worst > 0.0) {
                solution = candidate;
                break;
            }

            // Walk as far toward the candidate as feasibility allows.
            double step = std::numeric_limits<double>::infinity();
            for (int column : freeList) {
                if (candidate(column) <= 0.0) {
                    const double denominator = solution(column) - candidate(column);
                    if (denominator > kTiny) {
                        step = std::min(step, solution(column) / denominator);
                    } else {
                        step = 0.0;
                    }
                }
            }
            if (!std::isfinite(step)) {
                step = 0.0;
            }
            for (int column : freeList) {
                solution(column) += step * (candidate(column) - solution(column));
            }
            bool released = false;
            for (int column : freeList) {
                if (solution(column) <= kTiny) {
                    solution(column) = 0.0;
                    free[static_cast<std::size_t>(column)] = false;
                    released = true;
                }
            }
            if (!released) {
                // Numerically stuck rather than logically stuck: drop the column
                // that was just admitted and carry on, so this cannot spin.
                free[static_cast<std::size_t>(best)] = false;
                abandoned[static_cast<std::size_t>(best)] = true;
                solution(best) = 0.0;
                break;
            }
        }

        gradient = correlation - gram * solution;
        for (int column = 0; column < columns; ++column) {
            x[static_cast<std::size_t>(column)] = std::max(solution(column), 0.0);
        }
    }
}

bool fitTransform(const std::vector<Vec3>& from, const std::vector<Vec3>& to,
                  const std::vector<double>& weights, bool rigid, Mat4& out,
                  bool* degenerate) {
    if (degenerate) {
        *degenerate = false;
    }
    const std::size_t count = std::min(from.size(), to.size());
    if (count == 0) {
        return false;
    }

    double totalWeight = 0.0;
    Eigen::Vector3d fromCentre = Eigen::Vector3d::Zero();
    Eigen::Vector3d toCentre = Eigen::Vector3d::Zero();
    for (std::size_t index = 0; index < count; ++index) {
        const double weight = weights.empty() ? 1.0 : weights[index];
        if (weight <= 0.0) {
            continue;
        }
        totalWeight += weight;
        fromCentre += weight * Eigen::Vector3d(from[index].x, from[index].y, from[index].z);
        toCentre += weight * Eigen::Vector3d(to[index].x, to[index].y, to[index].z);
    }
    if (totalWeight <= kTiny) {
        return false;
    }
    fromCentre /= totalWeight;
    toCentre /= totalWeight;

    Eigen::Matrix3d covariance = Eigen::Matrix3d::Zero();
    Eigen::Matrix3d spread = Eigen::Matrix3d::Zero();
    for (std::size_t index = 0; index < count; ++index) {
        const double weight = weights.empty() ? 1.0 : weights[index];
        if (weight <= 0.0) {
            continue;
        }
        const Eigen::Vector3d p =
            Eigen::Vector3d(from[index].x, from[index].y, from[index].z) - fromCentre;
        const Eigen::Vector3d q =
            Eigen::Vector3d(to[index].x, to[index].y, to[index].z) - toCentre;
        covariance += weight * p * q.transpose();
        spread += weight * p * p.transpose();
    }

    Eigen::Matrix3d linear;

    if (rigid) {
        const Eigen::JacobiSVD<Eigen::Matrix3d> svd(
            covariance, Eigen::ComputeFullU | Eigen::ComputeFullV);
        Eigen::Matrix3d u = svd.matrixU();
        const Eigen::Matrix3d v = svd.matrixV();

        // The reflection case, and the whole reason this is written out rather
        // than left to a one-liner.
        //
        // U * V' can come back with a determinant of -1: a reflection, not a
        // rotation. The closest rotation is recovered by flipping the singular
        // vector belonging to the SMALLEST singular value, because that is the
        // direction the data constrains least - Eigen orders them descending, so
        // that is the third column.
        //
        // The tool this replaces instead negated the third column of the
        // assembled matrix. That does produce an orthogonal matrix with a
        // positive determinant, so nothing anywhere complains, but the third
        // column of a product is not the least-constrained direction, and the
        // result is a valid rotation that is not the best one. It shows up on
        // near-flat clusters - a cheek, a shoulder pad - which is precisely where
        // reflections happen.
        if ((u * v.transpose()).determinant() < 0.0) {
            u.col(2) *= -1.0;
        }
        // Row-vector convention: p' = p * R, so store the transpose of the
        // column-vector rotation.
        linear = (v * u.transpose()).transpose();

        const double largest = svd.singularValues()(0);
        if (degenerate && (largest <= kTiny ||
                           svd.singularValues()(2) <= 1e-9 * std::max(largest, 1.0))) {
            *degenerate = true;
        }
    } else {
        // Free to scale and shear: an ordinary weighted least squares fit. Solved
        // through the pseudo-inverse rather than a plain inverse so that a flat
        // or thin cluster gives the smallest answer that fits instead of a wild
        // one along the direction nothing pins down.
        const Eigen::JacobiSVD<Eigen::Matrix3d> svd(
            spread, Eigen::ComputeFullU | Eigen::ComputeFullV);
        const double largest = svd.singularValues()(0);
        const bool thin = largest <= kTiny ||
                          svd.singularValues()(2) <= 1e-9 * std::max(largest, 1.0);
        if (degenerate && thin) {
            *degenerate = true;
        }
        linear = spread.completeOrthogonalDecomposition().solve(covariance);
    }

    const Eigen::Vector3d translation = toCentre - linear.transpose() * fromCentre;

    out = Mat4();
    for (int row = 0; row < 3; ++row) {
        for (int column = 0; column < 3; ++column) {
            out.m[row][column] = linear(row, column);
        }
    }
    out.m[3][0] = translation(0);
    out.m[3][1] = translation(1);
    out.m[3][2] = translation(2);
    return true;
}

}  // namespace mca
