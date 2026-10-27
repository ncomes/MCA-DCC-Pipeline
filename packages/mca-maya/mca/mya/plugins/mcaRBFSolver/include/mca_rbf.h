// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// The RBF maths, with no Maya in it, so it can be tested off-DCC.
//
// What an RBF solver is, in one paragraph: a driven key with more than one
// dimension on each side. A regular driven key maps one float to one float. This
// maps an N-dimensional KEY to an M-dimensional VALUE - a joint's aim vector to
// a set of blendshape weights, say - and interpolates smoothly between the poses
// you gave it.
//
// How it works: given P poses, build the P x P matrix of kernel(distance between
// pose i and pose j), solve it once against each of the M value dimensions, and
// keep the resulting weight vectors. Evaluating is then P kernel calls and M dot
// products. Factorise when the poses change; evaluate every frame.
//
// Three things the tool this replaces got wrong, all of them fixed here and all
// of them covered by the off-DCC tests:
//
// **Its Euclidean distance was not Euclidean.** It summed |d|^N and took the
// Nth root, which is the p-norm with p set to the number of dimensions. That is
// right for 1D and 2D keys by coincidence and wrong for everything above - and
// the headline example in its own documentation is a 3D key. The p-norm is kept
// here as its own named option, honestly labelled, rather than being passed off
// as Euclidean.
//
// **One pose failed silently.** Its LU returned nothing for a 1x1 system and the
// caller read that as an error, so a single-pose setup produced no output. One
// pose is a legitimate setup: the answer is that pose's value, everywhere.
//
// **Two poses with the same key produced garbage.** Nothing checked whether the
// matrix was solvable, so a duplicated pose - easy to make by accident - gave
// whatever the arithmetic happened to produce. Here the solve reports its rank,
// and a ridge term on the diagonal makes a near-singular system behave.

#ifndef MCA_RBF_H
#define MCA_RBF_H

#include <string>
#include <vector>

namespace mca {

/// How the distance between two keys is measured.
enum class Distance {
    /// Straight line. What "Euclidean" should always have meant.
    Euclidean = 0,
    /// Angle between the two keys, in radians. For direction keys - an aim
    /// vector - where length is meaningless and only the direction matters.
    /// Both keys are normalised first; the original required callers to do it
    /// and did not check.
    Angular = 1,
    /// The original's behaviour: the p-norm with p set to the key's dimension.
    /// Kept so an old setup can be reproduced exactly, named for what it is.
    PNorm = 2,
};

/// The radial basis function itself.
enum class Kernel {
    Linear = 0,
    Gaussian = 1,
    Multiquadric = 2,
    InverseQuadratic = 3,
    InverseMultiquadric = 4,
    Cubic = 5,
    ThinPlate = 6,
};

struct RbfSetup {
    Distance distance = Distance::Euclidean;
    Kernel kernel = Kernel::Gaussian;

    /// Multiplies every distance before the kernel sees it. Widens or narrows
    /// how far a pose's influence reaches.
    double scale = 1.0;

    /// Divide distances by the largest distance between any two poses, so the
    /// same scale means the same thing whatever the keys are measured in.
    bool normalise = true;

    /// Added to the matrix diagonal before solving. Trades exactness at the
    /// poses for stability between them, and is what stops two poses with the
    /// same key from being unsolvable. Zero interpolates the poses exactly.
    double regularisation = 0.0;
};

/// Distance between two keys under one of the modes above.
double distance(Distance mode, const std::vector<double>& a, const std::vector<double>& b);

/// The kernel applied to an already-scaled distance.
double kernel(Kernel which, double d);

/// A factorised RBF system.
///
/// Built once when the poses change, evaluated every frame.
class RbfSolver {
public:
    /// Factorise the pose matrix and solve it against every value dimension.
    ///
    /// :param keys: P keys, each of dimension N. All must be the same length.
    /// :param values: P values, each of dimension M. All must be the same length.
    /// :param setup: Distance, kernel, scale and regularisation.
    /// :param error: Filled in when this returns false.
    /// :return: false rather than throwing - this is called from a Maya compute,
    ///     where an exception is not useful.
    bool build(const std::vector<std::vector<double>>& keys,
               const std::vector<std::vector<double>>& values,
               const RbfSetup& setup,
               std::string& error);

    /// Interpolate at one input.
    ///
    /// :param input: A key of dimension N.
    /// :param out: Filled with M values.
    /// :return: false if the solver was never built, or the input is the wrong
    ///     size.
    bool evaluate(const std::vector<double>& input, std::vector<double>& out) const;

    void clear();

    bool valid() const { return poseCount_ > 0; }
    int poseCount() const { return poseCount_; }
    int keyDimension() const { return keyDimension_; }
    int valueDimension() const { return valueDimension_; }

    /// True when the pose matrix was rank deficient - two poses the solver
    /// cannot tell apart. The solve still produces an answer, by least squares,
    /// but the caller should say so rather than pretend it is interpolating.
    bool degenerate() const { return degenerate_; }

    /// The scale actually used, after normalisation.
    double appliedScale() const { return appliedScale_; }

private:
    RbfSetup setup_;
    std::vector<std::vector<double>> keys_;
    /// One weight vector per value dimension, each P long.
    std::vector<std::vector<double>> weights_;

    int poseCount_ = 0;
    int keyDimension_ = 0;
    int valueDimension_ = 0;
    bool degenerate_ = false;
    double appliedScale_ = 1.0;
};

}  // namespace mca

#endif  // MCA_RBF_H
