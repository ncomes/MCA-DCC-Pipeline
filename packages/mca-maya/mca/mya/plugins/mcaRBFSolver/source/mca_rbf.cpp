// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_rbf.h"

#include <algorithm>
#include <cmath>

#include <Eigen/Dense>

namespace mca {

namespace {

/// Thin plate is undefined at zero, so the distance is floored just above it.
/// The original used 1e-14 and called it an epsilon; the value matters only in
/// that it must not be zero.
constexpr double kThinPlateFloor = 1e-12;

/// Below this a vector is treated as having no direction at all.
constexpr double kZeroLength = 1e-12;

double dot(const std::vector<double>& a, const std::vector<double>& b, std::size_t n) {
    double total = 0.0;
    for (std::size_t i = 0u; i < n; ++i) {
        total += a[i] * b[i];
    }
    return total;
}

}  // namespace

double distance(Distance mode, const std::vector<double>& a, const std::vector<double>& b) {
    const std::size_t n = std::min(a.size(), b.size());
    if (n == 0u) {
        return 0.0;
    }

    if (mode == Distance::Angular) {
        // Normalise here rather than requiring the caller to. The original said
        // in a comment that the vectors had to be normalised and then did not
        // check, so an un-normalised key silently gave a wrong angle.
        const double lengthA = std::sqrt(dot(a, a, n));
        const double lengthB = std::sqrt(dot(b, b, n));
        if (lengthA < kZeroLength || lengthB < kZeroLength) {
            return 0.0;
        }
        double cosine = dot(a, b, n) / (lengthA * lengthB);
        cosine = std::max(-1.0, std::min(1.0, cosine));
        return std::acos(cosine);
    }

    if (mode == Distance::PNorm) {
        // The original's "euclidian_distance": the p-norm with p set to the
        // number of dimensions. Correct for 1D and 2D, wrong above.
        const double power = static_cast<double>(n);
        double total = 0.0;
        for (std::size_t i = 0u; i < n; ++i) {
            total += std::pow(std::fabs(a[i] - b[i]), power);
        }
        return std::pow(total, 1.0 / power);
    }

    double total = 0.0;
    for (std::size_t i = 0u; i < n; ++i) {
        const double difference = a[i] - b[i];
        total += difference * difference;
    }
    return std::sqrt(total);
}

double kernel(Kernel which, double d) {
    switch (which) {
        case Kernel::Gaussian:
            return std::exp(-d * d);
        case Kernel::Multiquadric:
            return std::sqrt(1.0 + d * d);
        case Kernel::InverseQuadratic:
            return 1.0 / (1.0 + d * d);
        case Kernel::InverseMultiquadric:
            return 1.0 / std::sqrt(1.0 + d * d);
        case Kernel::Cubic:
            // d*d*d. The original returned d*d*d + 1, which adds a constant to
            // every entry of the matrix; that is not the cubic RBF and nothing
            // in the file explained it.
            return d * d * d;
        case Kernel::ThinPlate: {
            const double floored = std::max(d, kThinPlateFloor);
            return floored * floored * std::log(floored);
        }
        case Kernel::Linear:
        default:
            return d;
    }
}

void RbfSolver::clear() {
    keys_.clear();
    weights_.clear();
    poseCount_ = 0;
    keyDimension_ = 0;
    valueDimension_ = 0;
    degenerate_ = false;
    appliedScale_ = 1.0;
}

bool RbfSolver::build(const std::vector<std::vector<double>>& keys,
                      const std::vector<std::vector<double>>& values,
                      const RbfSetup& setup,
                      std::string& error) {
    clear();

    if (keys.empty()) {
        error = "No poses to interpolate between.";
        return false;
    }
    if (keys.size() != values.size()) {
        error = "Every pose needs both a key and a value: got " +
                std::to_string(keys.size()) + " keys and " +
                std::to_string(values.size()) + " values.";
        return false;
    }

    const std::size_t poses = keys.size();
    const std::size_t keyDimension = keys.front().size();
    const std::size_t valueDimension = values.front().size();
    if (keyDimension == 0u || valueDimension == 0u) {
        error = "Poses need a key and a value with at least one dimension each.";
        return false;
    }
    for (std::size_t i = 0u; i < poses; ++i) {
        if (keys[i].size() != keyDimension || values[i].size() != valueDimension) {
            error = "Pose " + std::to_string(i) + " has a different number of dimensions "
                    "from the first one. Every key must be the same length, and so must "
                    "every value.";
            return false;
        }
    }

    // --- the pose matrix ----------------------------------------------------- //
    Eigen::MatrixXd matrix(static_cast<Eigen::Index>(poses), static_cast<Eigen::Index>(poses));
    double largest = 0.0;
    for (std::size_t i = 0u; i < poses; ++i) {
        for (std::size_t j = i; j < poses; ++j) {
            const double d = distance(setup.distance, keys[i], keys[j]);
            matrix(static_cast<Eigen::Index>(i), static_cast<Eigen::Index>(j)) = d;
            matrix(static_cast<Eigen::Index>(j), static_cast<Eigen::Index>(i)) = d;
            largest = std::max(largest, d);
        }
    }

    // Normalising by the widest gap between poses is what makes `scale` mean the
    // same thing whether the keys are centimetres, radians or blendshape
    // weights. With one pose - or several at the same place - there is no gap,
    // so there is nothing to normalise by and the raw scale is used.
    appliedScale_ = setup.scale;
    if (setup.normalise && largest > kZeroLength) {
        appliedScale_ = setup.scale / largest;
    }

    for (Eigen::Index i = 0; i < matrix.rows(); ++i) {
        for (Eigen::Index j = 0; j < matrix.cols(); ++j) {
            matrix(i, j) = kernel(setup.kernel, matrix(i, j) * appliedScale_);
        }
    }

    if (setup.regularisation > 0.0) {
        for (Eigen::Index i = 0; i < matrix.rows(); ++i) {
            matrix(i, i) += setup.regularisation;
        }
    }

    // --- solve ---------------------------------------------------------------- //
    //
    // Column-pivoting QR rather than a hand-rolled LU: it tells us the rank, so
    // two poses the solver cannot tell apart are something we can report instead
    // of dividing by a pivot near zero and shipping the result. When the matrix
    // IS rank deficient this still returns the least-squares answer, which is a
    // reasonable thing to draw while the rigger fixes the poses.
    Eigen::ColPivHouseholderQR<Eigen::MatrixXd> decomposition(matrix);
    decomposition.setThreshold(1e-10);
    degenerate_ = decomposition.rank() < static_cast<Eigen::Index>(poses);

    weights_.resize(valueDimension);
    for (std::size_t m = 0u; m < valueDimension; ++m) {
        Eigen::VectorXd target(static_cast<Eigen::Index>(poses));
        for (std::size_t i = 0u; i < poses; ++i) {
            target(static_cast<Eigen::Index>(i)) = values[i][m];
        }
        const Eigen::VectorXd solved = decomposition.solve(target);
        if (!solved.allFinite()) {
            error = "The pose matrix could not be solved. Two poses are probably at the "
                    "same key; raise regularisation or remove the duplicate.";
            clear();
            return false;
        }
        weights_[m].assign(solved.data(), solved.data() + solved.size());
    }

    keys_ = keys;
    poseCount_ = static_cast<int>(poses);
    keyDimension_ = static_cast<int>(keyDimension);
    valueDimension_ = static_cast<int>(valueDimension);
    setup_ = setup;
    return true;
}

bool RbfSolver::evaluate(const std::vector<double>& input, std::vector<double>& out) const {
    if (poseCount_ <= 0) {
        return false;
    }
    if (static_cast<int>(input.size()) != keyDimension_) {
        return false;
    }

    std::vector<double> activations(static_cast<std::size_t>(poseCount_), 0.0);
    for (int i = 0; i < poseCount_; ++i) {
        const double d = distance(setup_.distance, input, keys_[static_cast<std::size_t>(i)]);
        activations[static_cast<std::size_t>(i)] = kernel(setup_.kernel, d * appliedScale_);
    }

    out.assign(static_cast<std::size_t>(valueDimension_), 0.0);
    for (int m = 0; m < valueDimension_; ++m) {
        const std::vector<double>& weights = weights_[static_cast<std::size_t>(m)];
        double total = 0.0;
        for (int i = 0; i < poseCount_; ++i) {
            total += weights[static_cast<std::size_t>(i)] *
                     activations[static_cast<std::size_t>(i)];
        }
        out[static_cast<std::size_t>(m)] = total;
    }
    return true;
}

}  // namespace mca
