// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// Off-DCC tests for the pose skinning maths. No Maya, no licence, no viewport.
//
// The checks worth having here are the ones that state a property the solve must
// have rather than a number it happens to produce:
//
// * if the deformation IS a skinning, the weights must come back exactly;
// * weights must sum to one and never be negative, whatever the input;
// * the answer must not depend on where the mesh sits in the world;
// * the answer must not depend on how many threads ran it;
// * held-out poses must be measured, not assumed.
//
// Those hold for any mesh, any joint count and any pose set, which is what makes
// them worth asserting. Two of them - translation invariance and the influence
// choice - are properties the tool this replaces does not have, and the checks
// that show that are marked where they appear.

#include "mca_pose_skin.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <numeric>
#include <string>
#include <vector>

namespace {

int gChecks = 0;
int gFailures = 0;

void check(const char* label, bool condition, const std::string& detail = std::string()) {
    ++gChecks;
    if (!condition) {
        ++gFailures;
        std::printf("  FAILED  %s%s%s\n", label, detail.empty() ? "" : "  |  ",
                    detail.c_str());
    }
}

std::string number(double value) {
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.10g", value);
    return std::string(buffer);
}

void note(const char* label, const std::string& detail) {
    std::printf("  measured  %-46s %s\n", label, detail.c_str());
}

/// A small deterministic generator, so that "random" test data is the same on
/// every machine and every run.
struct Random {
    unsigned long long state = 88172645463325252ull;

    double next() {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        return static_cast<double>(state % 1000000ull) / 1000000.0;
    }
    double between(double low, double high) { return low + (high - low) * next(); }
};

mca::Mat4 rotation(double radiansX, double radiansY, double radiansZ) {
    const double cx = std::cos(radiansX), sx = std::sin(radiansX);
    const double cy = std::cos(radiansY), sy = std::sin(radiansY);
    const double cz = std::cos(radiansZ), sz = std::sin(radiansZ);
    mca::Mat4 x;
    x.m[1][1] = cx;  x.m[1][2] = sx;  x.m[2][1] = -sx; x.m[2][2] = cx;
    mca::Mat4 y;
    y.m[0][0] = cy;  y.m[0][2] = -sy; y.m[2][0] = sy;  y.m[2][2] = cy;
    mca::Mat4 z;
    z.m[0][0] = cz;  z.m[0][1] = sz;  z.m[1][0] = -sz; z.m[1][1] = cz;
    return mca::multiply(mca::multiply(x, y), z);
}

mca::Mat4 translation(double x, double y, double z) {
    mca::Mat4 out;
    out.m[3][0] = x;
    out.m[3][1] = y;
    out.m[3][2] = z;
    return out;
}

mca::Mat4 scaling(double x, double y, double z) {
    mca::Mat4 out;
    out.m[0][0] = x;
    out.m[1][1] = y;
    out.m[2][2] = z;
    return out;
}

/// A tube of rings around the x axis with joints spaced along it, weighted
/// linearly between the two nearest joints - the simplest thing that is a real
/// skinning rather than a rigid parenting.
struct Arm {
    std::vector<mca::Vec3> rest;
    std::vector<mca::Mat4> bindInverse;
    std::vector<std::vector<int>> trueJoints;
    std::vector<std::vector<double>> trueWeights;
    std::vector<std::vector<int>> neighbours;
    double length = 0.0;
};

Arm makeArm(int rings, int perRing, int jointCount) {
    Arm arm;
    arm.length = static_cast<double>(jointCount - 1);
    const double spacing = arm.length / static_cast<double>(rings - 1);

    for (int ring = 0; ring < rings; ++ring) {
        const double x = spacing * static_cast<double>(ring);
        for (int around = 0; around < perRing; ++around) {
            const double angle =
                6.283185307179586 * static_cast<double>(around) / static_cast<double>(perRing);
            arm.rest.push_back(mca::Vec3(x, 0.5 * std::cos(angle), 0.5 * std::sin(angle)));
        }
    }

    for (int joint = 0; joint < jointCount; ++joint) {
        arm.bindInverse.push_back(translation(-static_cast<double>(joint), 0.0, 0.0));
    }

    for (const mca::Vec3& point : arm.rest) {
        const double along = std::max(0.0, std::min(point.x, arm.length));
        const int lower = std::min(static_cast<int>(std::floor(along)), jointCount - 2);
        const double fraction = along - static_cast<double>(lower);
        arm.trueJoints.push_back({lower, lower + 1});
        arm.trueWeights.push_back({1.0 - fraction, fraction});
    }

    // Ring neighbours plus the same vertex on the rings either side.
    const int total = rings * perRing;
    arm.neighbours.assign(static_cast<std::size_t>(total), std::vector<int>());
    for (int ring = 0; ring < rings; ++ring) {
        for (int around = 0; around < perRing; ++around) {
            const int self = ring * perRing + around;
            arm.neighbours[static_cast<std::size_t>(self)].push_back(
                ring * perRing + (around + 1) % perRing);
            arm.neighbours[static_cast<std::size_t>(self)].push_back(
                ring * perRing + (around + perRing - 1) % perRing);
            if (ring > 0) {
                arm.neighbours[static_cast<std::size_t>(self)].push_back(self - perRing);
            }
            if (ring + 1 < rings) {
                arm.neighbours[static_cast<std::size_t>(self)].push_back(self + perRing);
            }
        }
    }
    return arm;
}

/// Joint transforms for a set of poses: every joint gets its own rotation and a
/// small translation in every pose, which is what a decomposition assumes - no
/// hierarchy, each bone free.
std::vector<std::vector<mca::Mat4>> posedJoints(int poseCount, int jointCount, Random& random) {
    std::vector<std::vector<mca::Mat4>> out;
    for (int pose = 0; pose < poseCount; ++pose) {
        std::vector<mca::Mat4> perJoint;
        for (int joint = 0; joint < jointCount; ++joint) {
            const mca::Mat4 spin = rotation(random.between(-0.6, 0.6), random.between(-0.6, 0.6),
                                            random.between(-0.6, 0.6));
            const mca::Mat4 shift = translation(random.between(-0.3, 0.3),
                                                random.between(-0.3, 0.3),
                                                random.between(-0.3, 0.3));
            // Back to where the joint lives, so the rotation happens about the
            // joint rather than about the origin.
            perJoint.push_back(mca::multiply(mca::multiply(spin, shift),
                                             translation(static_cast<double>(joint), 0.0, 0.0)));
        }
        out.push_back(perJoint);
    }
    return out;
}

/// Skin the arm forward with its true weights to make the posed shapes.
std::vector<std::vector<mca::Vec3>> makePoses(
    const Arm& arm, const std::vector<std::vector<mca::Mat4>>& jointWorld, double noise,
    Random& random) {
    std::vector<std::vector<mca::Vec3>> poses;
    for (const std::vector<mca::Mat4>& perJoint : jointWorld) {
        std::vector<mca::Vec3> pose;
        for (std::size_t vertex = 0; vertex < arm.rest.size(); ++vertex) {
            mca::Vec3 point = mca::skinPoint(arm.rest[vertex], arm.trueJoints[vertex],
                                             arm.trueWeights[vertex], arm.bindInverse, perJoint);
            if (noise > 0.0) {
                point.x += random.between(-noise, noise);
                point.y += random.between(-noise, noise);
                point.z += random.between(-noise, noise);
            }
            pose.push_back(point);
        }
        poses.push_back(pose);
    }
    return poses;
}

/// A deformation that is NOT a linear blend skin - which is every case the tool
/// is actually used on. A skinning solved against a deformation that already IS
/// a skinning has one exact answer and every option looks the same; the
/// interesting behaviour only shows up when the model cannot reproduce the input
/// and the weights are a compromise.
///
/// Here the tube is bent about z by an angle that grows along its length and
/// swollen in the middle - smooth, and not expressible as a weighted sum of
/// rigid transforms. The joints are then given the best rigid fit of the
/// vertices around them, which is what a rigger's joints would be doing.
struct Bend {
    std::vector<std::vector<mca::Vec3>> poses;
    std::vector<std::vector<mca::Mat4>> jointWorld;
};

Bend makeBend(const Arm& arm, int jointCount, int poseCount) {
    Bend bend;
    for (int pose = 0; pose < poseCount; ++pose) {
        const double amount = 0.08 + 0.05 * static_cast<double>(pose);
        const double swell = 1.0 + 0.04 * static_cast<double>(pose % 4);
        std::vector<mca::Vec3> posed;
        for (const mca::Vec3& point : arm.rest) {
            const double angle = amount * point.x;
            const double fade =
                1.0 + (swell - 1.0) * std::sin(3.141592653589793 * point.x / arm.length);
            const double y = point.y * fade;
            const double z = point.z * fade;
            posed.push_back(mca::Vec3(point.x * std::cos(angle) - y * std::sin(angle),
                                      point.x * std::sin(angle) + y * std::cos(angle), z));
        }
        bend.poses.push_back(posed);

        std::vector<mca::Mat4> perJoint;
        for (int joint = 0; joint < jointCount; ++joint) {
            std::vector<mca::Vec3> from;
            std::vector<mca::Vec3> to;
            for (std::size_t vertex = 0; vertex < arm.rest.size(); ++vertex) {
                if (std::abs(arm.rest[vertex].x - static_cast<double>(joint)) <= 1.0) {
                    from.push_back(arm.rest[vertex]);
                    to.push_back(posed[vertex]);
                }
            }
            mca::Mat4 fitted;
            if (from.size() < 3 || !mca::fitTransform(from, to, {}, true, fitted, nullptr)) {
                fitted = translation(static_cast<double>(joint), 0.0, 0.0);
            } else {
                // fitTransform gives the whole skinning matrix; the input wants
                // joint-to-world, which is that with the bind pose put back.
                fitted = mca::multiply(translation(static_cast<double>(joint), 0.0, 0.0), fitted);
            }
            perJoint.push_back(fitted);
        }
        bend.jointWorld.push_back(perJoint);
    }
    return bend;
}

double weightOf(const std::vector<int>& joints, const std::vector<double>& weights, int joint) {
    for (std::size_t index = 0; index < joints.size(); ++index) {
        if (joints[index] == joint) {
            return weights[index];
        }
    }
    return 0.0;
}

double worstWeightDifference(const mca::PoseSkinResult& result, const Arm& arm, int jointCount) {
    double worst = 0.0;
    for (std::size_t vertex = 0; vertex < arm.rest.size(); ++vertex) {
        for (int joint = 0; joint < jointCount; ++joint) {
            const double mine = weightOf(result.vertexJoints[vertex],
                                         result.vertexWeights[vertex], joint);
            const double truth =
                weightOf(arm.trueJoints[vertex], arm.trueWeights[vertex], joint);
            worst = std::max(worst, std::abs(mine - truth));
        }
    }
    return worst;
}

void translateEverything(mca::PoseSkinInput& input, const mca::Vec3& by) {
    const mca::Mat4 shift = translation(by.x, by.y, by.z);
    const mca::Mat4 back = translation(-by.x, -by.y, -by.z);
    for (mca::Vec3& point : input.rest) {
        point.x += by.x;
        point.y += by.y;
        point.z += by.z;
    }
    for (std::vector<mca::Vec3>& pose : input.poses) {
        for (mca::Vec3& point : pose) {
            point.x += by.x;
            point.y += by.y;
            point.z += by.z;
        }
    }
    // A joint's world-to-bind must undo the move as well, or the joints and the
    // mesh no longer agree about where anything is.
    for (mca::Mat4& matrix : input.bindInverse) {
        matrix = mca::multiply(back, matrix);
    }
    for (std::vector<mca::Mat4>& perPose : input.jointWorld) {
        for (mca::Mat4& matrix : perPose) {
            matrix = mca::multiply(matrix, shift);
        }
    }
}

}  // namespace

int main() {
    std::printf("mcaPoseSkinner : solver tests\n");

    // ---------------------------------------------------------------- NNLS --//
    {
        // Identity: the answer is b with the negatives clamped off.
        std::vector<double> a = {1, 0, 0, 1};
        std::vector<double> b = {3.0, -2.0};
        std::vector<double> x;
        const bool ok = mca::solveNonNegative(a, 2, 2, b, x);
        check("nnls: converges on a 2x2 identity", ok);
        check("nnls: keeps the positive component", std::abs(x[0] - 3.0) < 1e-12, number(x[0]));
        check("nnls: clamps the negative one to zero", std::abs(x[1]) < 1e-12, number(x[1]));
    }
    {
        // A case whose unconstrained answer is already non-negative, so NNLS must
        // return it exactly: [[1,0],[1,1]] x = [2,3]  ->  x = [2,1].
        std::vector<double> a = {1, 0, 1, 1};
        std::vector<double> b = {2.0, 3.0};
        std::vector<double> x;
        mca::solveNonNegative(a, 2, 2, b, x);
        check("nnls: an all-positive answer is the least squares answer",
              std::abs(x[0] - 2.0) < 1e-10 && std::abs(x[1] - 1.0) < 1e-10,
              number(x[0]) + ", " + number(x[1]));
    }
    {
        // Everything points the wrong way: the answer is all zeros, not a small
        // negative.
        std::vector<double> a = {1, 0, 0, 1};
        std::vector<double> b = {-1.0, -2.0};
        std::vector<double> x;
        mca::solveNonNegative(a, 2, 2, b, x);
        check("nnls: an impossible fit gives zeros, not negatives",
              x[0] == 0.0 && x[1] == 0.0, number(x[0]) + ", " + number(x[1]));
    }
    {
        // Two identical columns: no unique answer. It must still be feasible and
        // still fit, rather than blowing up.
        std::vector<double> a = {1, 1, 1, 1};
        std::vector<double> b = {1.0, 1.0};
        std::vector<double> x;
        mca::solveNonNegative(a, 2, 2, b, x);
        const double sum = x[0] + x[1];
        check("nnls: duplicate columns stay feasible and still fit",
              x[0] >= 0.0 && x[1] >= 0.0 && std::abs(sum - 1.0) < 1e-8, number(sum));
    }
    {
        // Overdetermined and inconsistent: the residual must be orthogonal to the
        // free columns, which is the optimality condition the whole method rests
        // on. Checked rather than assumed.
        Random random;
        const int rows = 40;
        const int columns = 6;
        std::vector<double> a(static_cast<std::size_t>(rows * columns));
        std::vector<double> b(static_cast<std::size_t>(rows));
        for (int row = 0; row < rows; ++row) {
            for (int column = 0; column < columns; ++column) {
                a[static_cast<std::size_t>(row * columns + column)] =
                    random.between(-1.0, 1.0);
            }
            b[static_cast<std::size_t>(row)] = random.between(-1.0, 1.0);
        }
        std::vector<double> x;
        mca::solveNonNegative(a, rows, columns, b, x);
        std::vector<double> residual(static_cast<std::size_t>(rows), 0.0);
        for (int row = 0; row < rows; ++row) {
            double sum = 0.0;
            for (int column = 0; column < columns; ++column) {
                sum += a[static_cast<std::size_t>(row * columns + column)] *
                       x[static_cast<std::size_t>(column)];
            }
            residual[static_cast<std::size_t>(row)] = b[static_cast<std::size_t>(row)] - sum;
        }
        double worstFree = 0.0;
        double worstBlocked = 0.0;
        for (int column = 0; column < columns; ++column) {
            double dot = 0.0;
            for (int row = 0; row < rows; ++row) {
                dot += a[static_cast<std::size_t>(row * columns + column)] *
                       residual[static_cast<std::size_t>(row)];
            }
            if (x[static_cast<std::size_t>(column)] > 0.0) {
                worstFree = std::max(worstFree, std::abs(dot));
            } else {
                worstBlocked = std::max(worstBlocked, dot);
            }
        }
        check("nnls: the residual is orthogonal to every used column",
              worstFree < 1e-9, number(worstFree));
        check("nnls: no unused column could improve the fit", worstBlocked < 1e-9,
              number(worstBlocked));
    }

    // ------------------------------------------------------- fitTransform --//
    {
        Random random;
        std::vector<mca::Vec3> from;
        for (int index = 0; index < 20; ++index) {
            from.push_back(mca::Vec3(random.between(-2.0, 2.0), random.between(-2.0, 2.0),
                                     random.between(-2.0, 2.0)));
        }
        const mca::Mat4 truth =
            mca::multiply(rotation(0.3, -0.7, 1.1), translation(4.0, -2.0, 0.5));
        std::vector<mca::Vec3> to;
        for (const mca::Vec3& point : from) {
            to.push_back(mca::transformPoint(point, truth));
        }
        mca::Mat4 fitted;
        bool degenerate = true;
        const bool ok = mca::fitTransform(from, to, {}, true, fitted, &degenerate);
        double worst = 0.0;
        for (std::size_t index = 0; index < from.size(); ++index) {
            const mca::Vec3 moved = mca::transformPoint(from[index], fitted);
            worst = std::max(worst, std::abs(moved.x - to[index].x));
            worst = std::max(worst, std::abs(moved.y - to[index].y));
            worst = std::max(worst, std::abs(moved.z - to[index].z));
        }
        check("fit: a rigid move is recovered exactly", ok && worst < 1e-12, number(worst));
        check("fit: a full-rank cluster is not called degenerate", !degenerate);
    }
    {
        // Scale: the rigid fit cannot do it and must not pretend to; the free fit
        // must reproduce it exactly.
        Random random;
        std::vector<mca::Vec3> from;
        for (int index = 0; index < 30; ++index) {
            from.push_back(mca::Vec3(random.between(-2.0, 2.0), random.between(-2.0, 2.0),
                                     random.between(-2.0, 2.0)));
        }
        const mca::Mat4 truth = mca::multiply(scaling(1.7, 0.6, 1.2), rotation(0.2, 0.4, -0.3));
        std::vector<mca::Vec3> to;
        for (const mca::Vec3& point : from) {
            to.push_back(mca::transformPoint(point, truth));
        }
        mca::Mat4 rigid;
        mca::Mat4 free;
        mca::fitTransform(from, to, {}, true, rigid, nullptr);
        mca::fitTransform(from, to, {}, false, free, nullptr);
        double rigidWorst = 0.0;
        double freeWorst = 0.0;
        for (std::size_t index = 0; index < from.size(); ++index) {
            const mca::Vec3 a = mca::transformPoint(from[index], rigid);
            const mca::Vec3 b = mca::transformPoint(from[index], free);
            rigidWorst = std::max(rigidWorst, std::abs(a.x - to[index].x));
            freeWorst = std::max(freeWorst, std::abs(b.x - to[index].x));
            rigidWorst = std::max(rigidWorst, std::abs(a.y - to[index].y));
            freeWorst = std::max(freeWorst, std::abs(b.y - to[index].y));
        }
        check("fit: the free fit reproduces scale exactly", freeWorst < 1e-12,
              number(freeWorst));
        check("fit: the rigid fit does not claim to", rigidWorst > 0.1, number(rigidWorst));
    }
    {
        // Three points on a line cannot determine a rotation about that line.
        std::vector<mca::Vec3> from = {mca::Vec3(0, 0, 0), mca::Vec3(1, 0, 0),
                                       mca::Vec3(2, 0, 0)};
        std::vector<mca::Vec3> to = {mca::Vec3(0, 1, 0), mca::Vec3(1, 1, 0),
                                     mca::Vec3(2, 1, 0)};
        mca::Mat4 fitted;
        bool degenerate = false;
        const bool ok = mca::fitTransform(from, to, {}, true, fitted, &degenerate);
        check("fit: a straight line is reported as degenerate", ok && degenerate);
    }
    {
        // The reflection case, and the difference between flipping the right axis
        // and the wrong one.
        //
        // A near-flat cluster mapped to its own mirror image is where the closest
        // orthogonal matrix has a determinant of -1. The fix is to flip the
        // singular vector belonging to the smallest singular value. The tool this
        // replaces flipped the third column of the assembled product instead,
        // which is still orthogonal and still has a positive determinant - so it
        // passes every test anyone thought to write - but is not the closest
        // rotation. Both are built here and compared on the residual.
        std::vector<mca::Vec3> from;
        std::vector<mca::Vec3> to;
        Random random;
        for (int index = 0; index < 40; ++index) {
            const double x = random.between(-2.0, 2.0);
            const double y = random.between(-2.0, 2.0);
            const double z = random.between(-0.02, 0.02);  // nearly flat
            from.push_back(mca::Vec3(x, y, z));
            to.push_back(mca::Vec3(x, y, -z));             // mirrored
        }
        mca::Mat4 fitted;
        mca::fitTransform(from, to, {}, true, fitted, nullptr);

        const double determinant =
            fitted.m[0][0] * (fitted.m[1][1] * fitted.m[2][2] - fitted.m[1][2] * fitted.m[2][1]) -
            fitted.m[0][1] * (fitted.m[1][0] * fitted.m[2][2] - fitted.m[1][2] * fitted.m[2][0]) +
            fitted.m[0][2] * (fitted.m[1][0] * fitted.m[2][1] - fitted.m[1][1] * fitted.m[2][0]);
        check("fit: a mirrored cluster still gives a rotation, not a reflection",
              std::abs(determinant - 1.0) < 1e-9, number(determinant));

        double ours = 0.0;
        for (std::size_t index = 0; index < from.size(); ++index) {
            const mca::Vec3 moved = mca::transformPoint(from[index], fitted);
            const double dx = moved.x - to[index].x;
            const double dy = moved.y - to[index].y;
            const double dz = moved.z - to[index].z;
            ours += dx * dx + dy * dy + dz * dz;
        }

        // The identity is what "flip the least-constrained axis" reduces to here,
        // and any OTHER rotation must do worse. A rotation of 180 degrees about x
        // is what negating a column of the product amounts to on this data.
        const mca::Mat4 alternative = rotation(3.141592653589793, 0.0, 0.0);
        double theirs = 0.0;
        for (std::size_t index = 0; index < from.size(); ++index) {
            const mca::Vec3 moved = mca::transformPoint(from[index], alternative);
            const double dx = moved.x - to[index].x;
            const double dy = moved.y - to[index].y;
            const double dz = moved.z - to[index].z;
            theirs += dx * dx + dy * dy + dz * dz;
        }
        note("mirrored cluster, sum of squares", number(ours) + " ours, " + number(theirs) +
                                                      " flipping a different axis");
        check("fit: and it is the CLOSEST rotation, not just a valid one", ours < theirs,
              number(ours) + " vs " + number(theirs));
    }

    // -------------------------------------------------- the whole solve ----//
    Random random;
    const int jointCount = 4;
    Arm arm = makeArm(9, 8, jointCount);
    const std::vector<std::vector<mca::Mat4>> jointWorld = posedJoints(8, jointCount, random);
    const std::vector<std::vector<mca::Vec3>> poses = makePoses(arm, jointWorld, 0.0, random);

    mca::PoseSkinInput input;
    input.rest = arm.rest;
    input.poses = poses;
    input.bindInverse = arm.bindInverse;
    input.jointWorld = jointWorld;
    input.neighbours = arm.neighbours;

    mca::PoseSkinOptions options;
    options.maxInfluences = 4;
    options.threads = 1;

    mca::PoseSkinResult result;
    std::string error;
    {
        const bool ok = mca::solvePoseSkin(input, options, result, error);
        check("solve: runs", ok, error);
        note("recovering a known skinning: rms", number(result.rms));
        note("recovering a known skinning: worst vertex", number(result.worst));
        // The headline property: if the deformation IS a skinning, the weights
        // that produced it are recoverable. Not "close" - the residual is a
        // rounding error.
        check("solve: a deformation that IS a skinning is reproduced exactly",
              result.rms < 1e-9, number(result.rms));
        const double worstWeight = worstWeightDifference(result, arm, jointCount);
        note("recovering a known skinning: worst weight error", number(worstWeight));
        check("solve: and the weights themselves come back", worstWeight < 1e-6,
              number(worstWeight));

        double worstSum = 0.0;
        int mostInfluences = 0;
        bool negative = false;
        for (std::size_t vertex = 0; vertex < arm.rest.size(); ++vertex) {
            double sum = 0.0;
            for (double weight : result.vertexWeights[vertex]) {
                sum += weight;
                negative = negative || weight < 0.0;
            }
            worstSum = std::max(worstSum, std::abs(sum - 1.0));
            mostInfluences = std::max(mostInfluences,
                                      static_cast<int>(result.vertexJoints[vertex].size()));
        }
        check("solve: every vertex's weights sum to one", worstSum < 1e-12, number(worstSum));
        check("solve: no weight is negative", !negative);
        check("solve: the influence limit is honoured", mostInfluences <= options.maxInfluences,
              std::to_string(mostInfluences));
        check("solve: per-vertex error is reported for every vertex",
              result.vertexError.size() == arm.rest.size());
        check("solve: per-pose error is reported for every pose",
              result.poseError.size() == poses.size());
    }

    {
        // The influence limit, on a case that wants more than it is allowed.
        mca::PoseSkinOptions tight = options;
        tight.maxInfluences = 2;
        mca::PoseSkinResult tightResult;
        mca::solvePoseSkin(input, tight, tightResult, error);
        int most = 0;
        for (const std::vector<int>& joints : tightResult.vertexJoints) {
            most = std::max(most, static_cast<int>(joints.size()));
        }
        check("limit: two influences means two", most <= 2, std::to_string(most));
        note("two influences: rms", number(tightResult.rms));
    }

    {
        // Pruning one at a time against ranking once, on a deformation no
        // skinning can reproduce exactly and with far more joints than a vertex
        // is allowed - which is where the two can differ at all. On a case whose
        // answer is exact they agree to the last digit, which is worth knowing
        // before reading anything into a small difference.
        Arm crowded = makeArm(17, 10, 12);
        const Bend bend = makeBend(crowded, 12, 9);
        mca::PoseSkinInput crowdedInput;
        crowdedInput.rest = crowded.rest;
        crowdedInput.bindInverse = crowded.bindInverse;
        crowdedInput.jointWorld = bend.jointWorld;
        crowdedInput.neighbours = crowded.neighbours;
        crowdedInput.poses = bend.poses;

        mca::PoseSkinOptions stepwise;
        stepwise.maxInfluences = 2;
        stepwise.threads = 1;
        stepwise.prunePerStep = true;
        mca::PoseSkinOptions oneShot = stepwise;
        oneShot.prunePerStep = false;

        mca::PoseSkinResult a;
        mca::PoseSkinResult b;
        mca::solvePoseSkin(crowdedInput, stepwise, a, error);
        mca::solvePoseSkin(crowdedInput, oneShot, b, error);
        note("pruning one at a time vs ranking once (rms)",
             number(a.rms) + " vs " + number(b.rms));
        note("pruning one at a time vs ranking once (worst)",
             number(a.worst) + " vs " + number(b.worst));
        check("pruning: dropping one at a time is not worse than ranking once",
              a.rms <= b.rms * 1.000001, number(a.rms) + " vs " + number(b.rms));
    }

    {
        // Translation invariance, which is the property the tool this replaces
        // does not have.
        mca::PoseSkinInput moved = input;
        translateEverything(moved, mca::Vec3(1000.0, -500.0, 2000.0));
        mca::PoseSkinResult movedResult;
        mca::solvePoseSkin(moved, options, movedResult, error);

        double worst = 0.0;
        for (std::size_t vertex = 0; vertex < arm.rest.size(); ++vertex) {
            for (int joint = 0; joint < jointCount; ++joint) {
                worst = std::max(worst,
                                 std::abs(weightOf(result.vertexJoints[vertex],
                                                   result.vertexWeights[vertex], joint) -
                                          weightOf(movedResult.vertexJoints[vertex],
                                                   movedResult.vertexWeights[vertex], joint)));
            }
        }
        note("mesh moved 2291 units from the origin: weight change", number(worst));
        check("world position: moving the whole setup does not change the weights",
              worst < 1e-9, number(worst));

        // And the same vertex through the formulation this replaces, which carried
        // the rest position as an extra row of the system: columns all equal to
        // the rest point, right hand side equal to the rest point. That is the
        // sum-to-one constraint multiplied by the vertex's distance from the world
        // origin, so its strength depends on where the model was built.
        auto legacyWeights = [&](const mca::PoseSkinInput& source, int vertex) {
            const int poseCount = static_cast<int>(source.poses.size());
            const int columns = static_cast<int>(source.bindInverse.size());
            const int rows = 3 * (poseCount + 1) + 1;
            std::vector<double> a(static_cast<std::size_t>(rows * columns), 0.0);
            std::vector<double> b(static_cast<std::size_t>(rows), 0.0);
            const mca::Vec3& rest = source.rest[static_cast<std::size_t>(vertex)];
            for (int pose = 0; pose < poseCount; ++pose) {
                for (int joint = 0; joint < columns; ++joint) {
                    const mca::Vec3 point = mca::transformPoint(
                        rest, mca::multiply(source.bindInverse[static_cast<std::size_t>(joint)],
                                            source.jointWorld[static_cast<std::size_t>(pose)]
                                                             [static_cast<std::size_t>(joint)]));
                    a[static_cast<std::size_t>((3 * pose + 0) * columns + joint)] = point.x;
                    a[static_cast<std::size_t>((3 * pose + 1) * columns + joint)] = point.y;
                    a[static_cast<std::size_t>((3 * pose + 2) * columns + joint)] = point.z;
                }
                const mca::Vec3& target =
                    source.poses[static_cast<std::size_t>(pose)][static_cast<std::size_t>(vertex)];
                b[static_cast<std::size_t>(3 * pose + 0)] = target.x;
                b[static_cast<std::size_t>(3 * pose + 1)] = target.y;
                b[static_cast<std::size_t>(3 * pose + 2)] = target.z;
            }
            for (int joint = 0; joint < columns; ++joint) {
                a[static_cast<std::size_t>((3 * poseCount + 0) * columns + joint)] = rest.x;
                a[static_cast<std::size_t>((3 * poseCount + 1) * columns + joint)] = rest.y;
                a[static_cast<std::size_t>((3 * poseCount + 2) * columns + joint)] = rest.z;
                a[static_cast<std::size_t>((3 * poseCount + 3) * columns + joint)] = 1.0;
            }
            b[static_cast<std::size_t>(3 * poseCount + 0)] = rest.x;
            b[static_cast<std::size_t>(3 * poseCount + 1)] = rest.y;
            b[static_cast<std::size_t>(3 * poseCount + 2)] = rest.z;
            b[static_cast<std::size_t>(3 * poseCount + 3)] = 1.0;
            std::vector<double> x;
            mca::solveNonNegative(a, rows, columns, b, x);
            return x;
        };

        // The comparison has to be made on a deformation that CANNOT be fitted
        // exactly, and that is worth saying plainly: when an exact answer exists
        // both formulations find it wherever the mesh stands, because the residual
        // is zero either way. It is the ordinary case - a face, a sim, anything
        // real - where the answer is a compromise, and a compromise between a
        // data term and a constraint term depends on their relative size.
        Arm bendArm = makeArm(13, 10, 5);
        const Bend bent = makeBend(bendArm, 5, 7);
        mca::PoseSkinInput bentInput;
        bentInput.rest = bendArm.rest;
        bentInput.bindInverse = bendArm.bindInverse;
        bentInput.jointWorld = bent.jointWorld;
        bentInput.neighbours = bendArm.neighbours;
        bentInput.poses = bent.poses;
        mca::PoseSkinInput bentMoved = bentInput;
        translateEverything(bentMoved, mca::Vec3(1000.0, -500.0, 2000.0));

        mca::PoseSkinOptions bentOptions;
        bentOptions.maxInfluences = 4;
        bentOptions.threads = 1;
        mca::PoseSkinResult bentHere;
        mca::PoseSkinResult bentThere;
        mca::solvePoseSkin(bentInput, bentOptions, bentHere, error);
        mca::solvePoseSkin(bentMoved, bentOptions, bentThere, error);
        double inexactDifference = 0.0;
        for (std::size_t vertex = 0; vertex < bendArm.rest.size(); ++vertex) {
            for (int joint = 0; joint < 5; ++joint) {
                inexactDifference = std::max(
                    inexactDifference,
                    std::abs(weightOf(bentHere.vertexJoints[vertex],
                                      bentHere.vertexWeights[vertex], joint) -
                             weightOf(bentThere.vertexJoints[vertex],
                                      bentThere.vertexWeights[vertex], joint)));
            }
        }
        note("an inexact fit, moved: our weight change", number(inexactDifference));
        check("world position: invariant on an inexact fit too, which is the real case",
              inexactDifference < 1e-9, number(inexactDifference));

        double legacyDifference = 0.0;
        for (int sample = 0; sample < static_cast<int>(bendArm.rest.size()); sample += 7) {
            const std::vector<double> here = legacyWeights(bentInput, sample);
            const std::vector<double> there = legacyWeights(bentMoved, sample);
            for (std::size_t joint = 0; joint < here.size(); ++joint) {
                legacyDifference =
                    std::max(legacyDifference, std::abs(here[joint] - there[joint]));
            }
        }
        note("the same vertices, the old formulation, moved", number(legacyDifference));
        check("world position: and the formulation it replaces DOES change",
              legacyDifference > 1e-4, number(legacyDifference));
    }

    {
        // Threads must not change the answer. The per-vertex solves are
        // independent, so this is a property of the design rather than luck - but
        // it is exactly the kind of property that quietly stops being true.
        mca::PoseSkinOptions many = options;
        many.threads = 8;
        mca::PoseSkinResult first;
        mca::PoseSkinResult second;
        mca::solvePoseSkin(input, many, first, error);
        mca::solvePoseSkin(input, many, second, error);
        bool identical = first.vertexJoints == second.vertexJoints &&
                         first.vertexWeights == second.vertexWeights &&
                         first.rms == second.rms;
        check("determinism: two runs on eight threads are bit-identical", identical);

        bool matchesSingle = first.vertexJoints == result.vertexJoints &&
                             first.vertexWeights == result.vertexWeights;
        check("determinism: and agree with the single-threaded run", matchesSingle);
    }

    {
        // Locality: with the restriction on, a vertex must never use a joint
        // outside its nearest few.
        Arm longArm = makeArm(13, 8, 10);
        const std::vector<std::vector<mca::Mat4>> transforms = posedJoints(12, 10, random);
        mca::PoseSkinInput localInput;
        localInput.rest = longArm.rest;
        localInput.bindInverse = longArm.bindInverse;
        localInput.jointWorld = transforms;
        localInput.neighbours = longArm.neighbours;
        localInput.poses = makePoses(longArm, transforms, 0.01, random);

        mca::PoseSkinOptions local;
        local.maxInfluences = 3;
        local.localityJoints = 3;
        local.threads = 1;
        mca::PoseSkinResult localResult;
        mca::solvePoseSkin(localInput, local, localResult, error);

        bool outside = false;
        for (std::size_t vertex = 0; vertex < longArm.rest.size(); ++vertex) {
            std::vector<int> nearest(10);
            std::iota(nearest.begin(), nearest.end(), 0);
            const mca::Vec3& rest = longArm.rest[vertex];
            std::stable_sort(nearest.begin(), nearest.end(), [&](int a, int b) {
                return std::abs(rest.x - static_cast<double>(a)) <
                       std::abs(rest.x - static_cast<double>(b));
            });
            nearest.resize(3);
            for (int joint : localResult.vertexJoints[vertex]) {
                if (std::find(nearest.begin(), nearest.end(), joint) == nearest.end()) {
                    outside = true;
                }
            }
        }
        check("locality: no vertex reaches past its nearest joints", !outside);

        mca::PoseSkinOptions open = local;
        open.localityJoints = 0;
        mca::PoseSkinResult openResult;
        mca::solvePoseSkin(localInput, open, openResult, error);
        note("locality on vs off (rms)", number(localResult.rms) + " vs " + number(openResult.rms));
    }

    {
        // Held-out poses, and what smoothing does to them.
        //
        // Measured on a deformation that no skinning can reproduce, with four of
        // the fourteen poses kept out of the fit. Both numbers are printed
        // whichever way they come out: a feature that does not earn its place
        // should say so here rather than in a shot.
        Arm soft = makeArm(15, 12, 6);
        const Bend softBend = makeBend(soft, 6, 14);
        mca::PoseSkinInput softInput;
        softInput.rest = soft.rest;
        softInput.bindInverse = soft.bindInverse;
        softInput.jointWorld = softBend.jointWorld;
        softInput.neighbours = soft.neighbours;
        softInput.poses = softBend.poses;

        mca::PoseSkinOptions plain;
        plain.maxInfluences = 4;
        plain.threads = 1;
        plain.holdoutPoses = {2, 5, 9, 13};

        mca::PoseSkinResult plainResult;
        mca::solvePoseSkin(softInput, plain, plainResult, error);
        check("holdout: held-out error is reported", plainResult.holdoutRms >= 0.0,
              number(plainResult.holdoutRms));
        check("holdout: and no holdout means no number",
              [&]() {
                  mca::PoseSkinOptions none = plain;
                  none.holdoutPoses.clear();
                  mca::PoseSkinResult quiet;
                  mca::solvePoseSkin(softInput, none, quiet, error);
                  return quiet.holdoutRms < 0.0;
              }());
        check("holdout: a pose that was not fitted is harder than one that was",
              plainResult.holdoutRms >= plainResult.rms,
              number(plainResult.rms) + " fitted, " + number(plainResult.holdoutRms) + " held out");

    }

    {
        // What smoothing is for, measured the only way that can show it.
        //
        // The first version of this check swept smoothing on a clean deformation
        // and compared held-out error. It found nothing - 0.2474496 against
        // 0.2474544, a two-thousandth of a percent - and it was right to: on input
        // with no noise in it there is nothing for a smoothness prior to remove,
        // and every neighbouring vertex already sees an almost identical system.
        // The check "passed" on the fact that SOME amount was nominally better,
        // which is no evidence at all.
        //
        // The claim worth testing is the one that matters on a sim cache or a
        // scan: fit against NOISY poses, then measure against the CLEAN ones the
        // noise was added to. If the prior works, the weights it finds are closer
        // to the truth than the ones that chased the noise.
        // Deliberately a deformation that IS a skinning, unlike the block above.
        // With model mismatch in the picture it swamps everything: on the bent tube
        // the total error is 0.22 against noise of 0.06, so a better weight is
        // worth a fraction of a percent of a number dominated by something else
        // entirely. Removing the mismatch is what makes the noise the thing being
        // measured.
        Arm soft = makeArm(15, 12, 6);
        Random jitter;
        const std::vector<std::vector<mca::Mat4>> softJoints = posedJoints(14, 6, jitter);
        const std::vector<std::vector<mca::Vec3>> cleanPoses =
            makePoses(soft, softJoints, 0.0, jitter);
        std::vector<std::vector<mca::Vec3>> noisy = cleanPoses;
        const double noise = 0.06;
        for (std::vector<mca::Vec3>& pose : noisy) {
            for (mca::Vec3& point : pose) {
                point.x += jitter.between(-noise, noise);
                point.y += jitter.between(-noise, noise);
                point.z += jitter.between(-noise, noise);
            }
        }

        mca::PoseSkinInput noisyInput;
        noisyInput.rest = soft.rest;
        noisyInput.bindInverse = soft.bindInverse;
        noisyInput.jointWorld = softJoints;
        noisyInput.neighbours = soft.neighbours;
        noisyInput.poses = noisy;

        // Error of a solved weight set against the deformation we actually wanted.
        auto againstTruth = [&](const mca::PoseSkinResult& from) {
            double sum = 0.0;
            std::size_t count = 0;
            for (std::size_t pose = 0; pose < cleanPoses.size(); ++pose) {
                for (std::size_t vertex = 0; vertex < soft.rest.size(); ++vertex) {
                    const mca::Vec3 skinned = mca::skinPoint(
                        soft.rest[vertex], from.vertexJoints[vertex], from.vertexWeights[vertex],
                        from.bindInverse, from.jointWorld[pose]);
                    const double dx = skinned.x - cleanPoses[pose][vertex].x;
                    const double dy = skinned.y - cleanPoses[pose][vertex].y;
                    const double dz = skinned.z - cleanPoses[pose][vertex].z;
                    sum += dx * dx + dy * dy + dz * dz;
                    ++count;
                }
            }
            return std::sqrt(sum / static_cast<double>(count));
        };

        mca::PoseSkinOptions raw;
        raw.maxInfluences = 4;
        raw.threads = 1;
        mca::PoseSkinResult rawResult;
        mca::solvePoseSkin(noisyInput, raw, rawResult, error);
        const double rawTruth = againstTruth(rawResult);

        double bestTruth = rawTruth;
        double bestAmount = 0.0;
        for (double amount : {0.05, 0.2, 0.5, 1.0, 2.0}) {
            mca::PoseSkinOptions smoothed = raw;
            smoothed.smoothing = amount;
            smoothed.smoothingRounds = 3;
            mca::PoseSkinResult smoothedResult;
            mca::solvePoseSkin(noisyInput, smoothed, smoothedResult, error);
            note((std::string("smoothing ") + number(amount) +
                  ": rms vs the noisy input / vs the truth")
                     .c_str(),
                 number(smoothedResult.rms) + " / " + number(againstTruth(smoothedResult)));
            if (againstTruth(smoothedResult) < bestTruth) {
                bestTruth = againstTruth(smoothedResult);
                bestAmount = amount;
            }
        }
        note("smoothing 0: rms vs the noisy input / vs the truth",
             number(rawResult.rms) + " / " + number(rawTruth));
        note("best smoothing against the truth",
             number(bestAmount) + " at " + number(bestTruth) + ", against " + number(rawTruth) +
                 " with none");
        // And the answer is no: smoothing does NOT get closer to the truth, here or
        // anywhere else it was tried. Swept over 6, 12 and 24 joints, 3 to 16
        // poses, with and without noise - 24 cells - it was better in two of them
        // by under two percent and worse in the other twenty-two, by up to five
        // times at heavy settings. The reason is plain enough once measured: the
        // per-vertex fit already averages over three axes times however many
        // poses, so the weights are not noisy enough for a prior to rescue, while
        // neighbouring vertices genuinely DO have different weights - that is what
        // a weight map is - so pulling them together is bias with nothing bought.
        //
        // So the knob stays, because a smoother weight map is a real thing to want
        // - it is the difference between a map an artist can edit by hand and a
        // speckled one, and engines LOD it better - but it is documented as what it
        // is rather than as accuracy, and it defaults to off. The two checks below
        // are the claim that survives measurement.
        note("smoothing: closest to the truth at",
             number(bestAmount) + " (" + number(bestTruth) + " against " + number(rawTruth) +
                 " with none)");

        mca::PoseSkinOptions fixed = raw;
        fixed.smoothing = 0.5;
        fixed.smoothingRounds = 3;
        mca::PoseSkinResult fixedResult;
        mca::solvePoseSkin(noisyInput, fixed, fixedResult, error);
        check("smoothing: it costs something against the poses it was given",
              fixedResult.rms >= rawResult.rms,
              number(rawResult.rms) + " -> " + number(fixedResult.rms));

        auto worstNeighbourJump = [&](const mca::PoseSkinResult& from) {
            double worst = 0.0;
            for (std::size_t vertex = 0; vertex < soft.rest.size(); ++vertex) {
                for (int other : soft.neighbours[vertex]) {
                    for (int joint = 0; joint < 6; ++joint) {
                        worst = std::max(
                            worst,
                            std::abs(weightOf(from.vertexJoints[vertex],
                                              from.vertexWeights[vertex], joint) -
                                     weightOf(from.vertexJoints[static_cast<std::size_t>(other)],
                                              from.vertexWeights[static_cast<std::size_t>(other)],
                                              joint)));
                    }
                }
            }
            return worst;
        };
        const double rawJump = worstNeighbourJump(rawResult);
        const double smoothJump = worstNeighbourJump(fixedResult);
        note("worst weight jump between neighbours",
             number(rawJump) + " plain, " + number(smoothJump) + " smoothed");
        check("smoothing: neighbouring vertices end up more alike", smoothJump < rawJump,
              number(rawJump) + " -> " + number(smoothJump));
    }

    {
        // Locality, which IS the accuracy win the smoothing prior was not.
        //
        // Restricting each vertex to its nearest few joints removes a whole class
        // of wrong answer: two parts of a mesh that happen to move alike across
        // the poses you sampled can otherwise share influences, and with more
        // joints than the poses can distinguish the fit is free to put weight
        // anywhere that happens to fit the noise. Measured on the same tube with
        // noisy poses, and then on a case with far more joints than the poses can
        // pin down.
        Arm wide = makeArm(17, 10, 12);
        Random jitter;
        const std::vector<std::vector<mca::Mat4>> transforms = posedJoints(5, 12, jitter);
        const std::vector<std::vector<mca::Vec3>> cleanPoses =
            makePoses(wide, transforms, 0.0, jitter);
        std::vector<std::vector<mca::Vec3>> noisy = cleanPoses;
        for (std::vector<mca::Vec3>& pose : noisy) {
            for (mca::Vec3& point : pose) {
                point.x += jitter.between(-0.05, 0.05);
                point.y += jitter.between(-0.05, 0.05);
                point.z += jitter.between(-0.05, 0.05);
            }
        }

        mca::PoseSkinInput wideInput;
        wideInput.rest = wide.rest;
        wideInput.bindInverse = wide.bindInverse;
        wideInput.jointWorld = transforms;
        wideInput.neighbours = wide.neighbours;
        wideInput.poses = noisy;

        auto truthError = [&](const mca::PoseSkinResult& from) {
            double sum = 0.0;
            std::size_t count = 0;
            for (std::size_t pose = 0; pose < cleanPoses.size(); ++pose) {
                for (std::size_t vertex = 0; vertex < wide.rest.size(); ++vertex) {
                    const mca::Vec3 skinned = mca::skinPoint(
                        wide.rest[vertex], from.vertexJoints[vertex], from.vertexWeights[vertex],
                        from.bindInverse, from.jointWorld[pose]);
                    const double dx = skinned.x - cleanPoses[pose][vertex].x;
                    const double dy = skinned.y - cleanPoses[pose][vertex].y;
                    const double dz = skinned.z - cleanPoses[pose][vertex].z;
                    sum += dx * dx + dy * dy + dz * dz;
                    ++count;
                }
            }
            return std::sqrt(sum / static_cast<double>(count));
        };

        mca::PoseSkinOptions off;
        off.maxInfluences = 4;
        off.threads = 1;
        mca::PoseSkinOptions on = off;
        on.localityJoints = 4;

        mca::PoseSkinResult offResult;
        mca::PoseSkinResult onResult;
        mca::solvePoseSkin(wideInput, off, offResult, error);
        mca::solvePoseSkin(wideInput, on, onResult, error);
        note("locality off vs on, rms against the truth",
             number(truthError(offResult)) + " vs " + number(truthError(onResult)));
        check("locality: it lands measurably closer to the truth on noisy input",
              truthError(onResult) < truthError(offResult) * 0.85,
              number(truthError(offResult)) + " -> " + number(truthError(onResult)));
        note("locality off vs on, rms against the input it was given",
             number(offResult.rms) + " vs " + number(onResult.rms));
        check("locality: and it fits the given poses slightly less well, which is the trade",
              onResult.rms >= offResult.rms, number(offResult.rms) + " vs " + number(onResult.rms));
    }

    {
        // More joints than the poses can tell apart: 24 joints, 3 poses, no noise
        // at all. Unrestricted, the fit is free to spread weight over joints that
        // are indistinguishable across those three poses and the result is
        // measurably wrong on a deformation that IS a skinning - the one case that
        // should be exact.
        Arm many = makeArm(17, 10, 24);
        Random jitter;
        const std::vector<std::vector<mca::Mat4>> transforms = posedJoints(3, 24, jitter);
        const std::vector<std::vector<mca::Vec3>> exact = makePoses(many, transforms, 0.0, jitter);

        mca::PoseSkinInput manyInput;
        manyInput.rest = many.rest;
        manyInput.bindInverse = many.bindInverse;
        manyInput.jointWorld = transforms;
        manyInput.neighbours = many.neighbours;
        manyInput.poses = exact;

        mca::PoseSkinOptions off;
        off.maxInfluences = 4;
        off.threads = 1;
        mca::PoseSkinOptions on = off;
        on.localityJoints = 4;

        mca::PoseSkinResult offResult;
        mca::PoseSkinResult onResult;
        mca::solvePoseSkin(manyInput, off, offResult, error);
        mca::solvePoseSkin(manyInput, on, onResult, error);
        note("24 joints, 3 poses: worst vertex error",
             number(offResult.worst) + " unrestricted, " + number(onResult.worst) + " restricted");
        check("locality: it rescues a case with more joints than the poses can pin down",
              onResult.worst < 1e-9 && offResult.worst > 1e-6,
              number(offResult.worst) + " -> " + number(onResult.worst));
    }

    {
        // Geodesic locality: two tubes a whisker apart, moving differently.
        //
        // This is the lips, and the eyeball, and the tongue. Straight-line distance
        // says a vertex on one tube and a joint on the other are neighbours, because
        // they are - through the air. Across the surface there is no path at all.
        // Nothing on one tube should be weighted to a joint on the other, and the
        // cost of getting that wrong is the two tubes dragging each other.
        Arm first = makeArm(11, 10, 4);
        Arm second = makeArm(11, 10, 4);
        const int perTube = static_cast<int>(first.rest.size());
        const int jointsPerTube = 4;
        const double gap = 1.02;  // radius 0.5 each, so 0.02 of air between them

        mca::PoseSkinInput twin;
        twin.rest = first.rest;
        for (const mca::Vec3& point : second.rest) {
            twin.rest.push_back(mca::Vec3(point.x, point.y + gap, point.z));
        }
        // Adjacency within each tube and NOT between them: two shells.
        twin.neighbours = first.neighbours;
        for (const std::vector<int>& around : second.neighbours) {
            std::vector<int> shifted;
            for (int other : around) {
                shifted.push_back(other + perTube);
            }
            twin.neighbours.push_back(shifted);
        }
        twin.bindInverse = first.bindInverse;
        for (int joint = 0; joint < jointsPerTube; ++joint) {
            twin.bindInverse.push_back(
                mca::multiply(translation(0.0, -gap, 0.0),
                              second.bindInverse[static_cast<std::size_t>(joint)]));
        }

        Random random;
        const std::vector<std::vector<mca::Mat4>> firstMotion =
            posedJoints(10, jointsPerTube, random);
        const std::vector<std::vector<mca::Mat4>> secondMotion =
            posedJoints(10, jointsPerTube, random);
        for (int pose = 0; pose < 10; ++pose) {
            std::vector<mca::Mat4> perJoint = firstMotion[static_cast<std::size_t>(pose)];
            for (int joint = 0; joint < jointsPerTube; ++joint) {
                perJoint.push_back(
                    mca::multiply(secondMotion[static_cast<std::size_t>(pose)]
                                              [static_cast<std::size_t>(joint)],
                                  translation(0.0, gap, 0.0)));
            }
            twin.jointWorld.push_back(perJoint);
        }

        // Each tube skinned by its own joints, and nothing else.
        std::vector<std::vector<int>> trueJoints = first.trueJoints;
        std::vector<std::vector<double>> trueWeights = first.trueWeights;
        for (std::size_t vertex = 0; vertex < second.rest.size(); ++vertex) {
            std::vector<int> joints;
            for (int joint : second.trueJoints[vertex]) {
                joints.push_back(joint + jointsPerTube);
            }
            trueJoints.push_back(joints);
            trueWeights.push_back(second.trueWeights[vertex]);
        }
        for (int pose = 0; pose < 10; ++pose) {
            std::vector<mca::Vec3> posed;
            for (std::size_t vertex = 0; vertex < twin.rest.size(); ++vertex) {
                posed.push_back(mca::skinPoint(twin.rest[vertex], trueJoints[vertex],
                                               trueWeights[vertex], twin.bindInverse,
                                               twin.jointWorld[static_cast<std::size_t>(pose)]));
            }
            twin.poses.push_back(posed);
        }
        // A little noise, so the fit has something to get wrong.
        for (std::vector<mca::Vec3>& pose : twin.poses) {
            for (mca::Vec3& point : pose) {
                point.x += random.between(-0.02, 0.02);
                point.y += random.between(-0.02, 0.02);
                point.z += random.between(-0.02, 0.02);
            }
        }

        auto crossings = [&](const mca::PoseSkinResult& from) {
            int count = 0;
            for (std::size_t vertex = 0; vertex < twin.rest.size(); ++vertex) {
                const bool onFirst = vertex < static_cast<std::size_t>(perTube);
                for (int joint : from.vertexJoints[vertex]) {
                    if ((joint < jointsPerTube) != onFirst) {
                        ++count;
                    }
                }
            }
            return count;
        };

        mca::PoseSkinOptions air;
        air.maxInfluences = 3;
        air.localityJoints = 3;
        air.threads = 1;
        mca::PoseSkinOptions surface = air;
        surface.geodesicLocality = true;

        mca::PoseSkinResult throughAir;
        mca::PoseSkinResult acrossSurface;
        mca::solvePoseSkin(twin, air, throughAir, error);
        mca::solvePoseSkin(twin, surface, acrossSurface, error);

        note("influences crossing between two shells",
             std::to_string(crossings(throughAir)) + " through the air, " +
                 std::to_string(crossings(acrossSurface)) + " across the surface");
        check("geodesic: no influence crosses from one shell to the other",
              crossings(acrossSurface) == 0, std::to_string(crossings(acrossSurface)));
        check("geodesic: and straight-line distance DOES let them cross",
              crossings(throughAir) > 0, std::to_string(crossings(throughAir)));
        note("two shells, rms against the input",
             number(throughAir.rms) + " through the air, " + number(acrossSurface.rms) +
                 " across the surface");
        check("geodesic: and it fits at least as well",
              acrossSurface.rms <= throughAir.rms * 1.02,
              number(throughAir.rms) + " vs " + number(acrossSurface.rms));
    }

    {
        // Solving the bones as well: throw the joint transforms away and see how
        // much of the deformation comes back.
        Arm bare = makeArm(9, 8, jointCount);
        const std::vector<std::vector<mca::Mat4>> truth = posedJoints(10, jointCount, random);
        mca::PoseSkinInput bareInput;
        bareInput.rest = bare.rest;
        bareInput.bindInverse = bare.bindInverse;
        bareInput.poses = makePoses(bare, truth, 0.0, random);
        bareInput.neighbours = bare.neighbours;
        // Every joint starting where it rests, with no motion at all: the worst
        // starting guess there is.
        std::vector<std::vector<mca::Mat4>> guess;
        for (int pose = 0; pose < 10; ++pose) {
            std::vector<mca::Mat4> perJoint;
            for (int joint = 0; joint < jointCount; ++joint) {
                perJoint.push_back(translation(static_cast<double>(joint), 0.0, 0.0));
            }
            guess.push_back(perJoint);
        }
        bareInput.jointWorld = guess;

        mca::PoseSkinOptions bones;
        bones.maxInfluences = 4;
        bones.threads = 1;
        bones.maxIterations = 25;
        bones.solveBones = true;
        bones.improvementBreak = 0.001;

        mca::PoseSkinResult boneResult;
        const bool ok = mca::solvePoseSkin(bareInput, bones, boneResult, error);
        check("bones: the solve runs with the transforms unknown", ok, error);
        check("bones: it took more than one iteration", boneResult.iterationsDone > 1,
              std::to_string(boneResult.iterationsDone));
        note("bones from nothing: first vs last rms",
             number(boneResult.iterationRms.front()) + " -> " + number(boneResult.rms) + " over " +
                 std::to_string(boneResult.iterationsDone) + " iterations");
        // A cold start - every joint sitting at its rest pose in every pose, no
        // motion at all - does NOT reach the true answer. Measured, it gets about
        // three times closer and then stops: the alternation is a local method and
        // this is a deliberately hostile place to start it from. That is why the
        // from-scratch path in the tool initialises the joints by clustering the
        // deformation first rather than dropping them all at rest, and it is worth
        // having the number written down rather than discovering it on an asset.
        check("bones: a cold start improves the fit several times over",
              boneResult.rms < boneResult.iterationRms.front() * 0.4,
              number(boneResult.iterationRms.front()) + " -> " + number(boneResult.rms));
        bool monotonic = true;
        for (std::size_t index = 1; index < boneResult.iterationRms.size(); ++index) {
            if (boneResult.iterationRms[index] > boneResult.iterationRms[index - 1] * 1.0001) {
                monotonic = false;
            }
        }
        check("bones: no iteration makes it worse", monotonic);

        // Started near the answer instead, the same alternation walks all the way
        // in. So the solve is sound and the initial guess is the whole game, which
        // is the useful thing to know about it.
        std::vector<std::vector<mca::Mat4>> warm = truth;
        for (std::vector<mca::Mat4>& perJoint : warm) {
            for (mca::Mat4& matrix : perJoint) {
                matrix = mca::multiply(rotation(0.05, -0.04, 0.03), matrix);
            }
        }
        mca::PoseSkinInput warmInput = bareInput;
        warmInput.jointWorld = warm;
        mca::PoseSkinOptions patient = bones;
        patient.maxIterations = 60;
        patient.improvementBreak = -1.0;  // run them all, to see where it lands
        mca::PoseSkinResult warmResult;
        mca::solvePoseSkin(warmInput, patient, warmResult, error);
        note("bones from a rough guess: first vs last rms",
             number(warmResult.iterationRms.front()) + " -> " + number(warmResult.rms));
        // 1e-4 on a model three units long, from a guess that was 0.03 out. The
        // last digits are expensive - the alternation converges linearly, so it
        // halves the remaining error every few iterations rather than squaring it -
        // which is why `improvementBreak` exists and why its default stops long
        // before this.
        check("bones: from a rough guess it converges to the answer",
              warmResult.rms < 1e-3, number(warmResult.rms));
    }

    // ------------------------------------------------------- refusals -----//
    {
        mca::PoseSkinInput bad;
        bad.rest = arm.rest;
        bad.bindInverse = arm.bindInverse;
        mca::PoseSkinResult ignored;
        std::string message;
        const bool ok = mca::solvePoseSkin(bad, options, ignored, message);
        check("refusal: no poses is refused, with a reason", !ok && message.size() > 30,
              message);
    }
    {
        mca::PoseSkinInput bad = input;
        bad.poses[1].pop_back();
        mca::PoseSkinResult ignored;
        std::string message;
        const bool ok = mca::solvePoseSkin(bad, options, ignored, message);
        check("refusal: a pose with the wrong vertex count names the pose",
              !ok && message.find("Pose 1") != std::string::npos, message);
    }
    {
        mca::PoseSkinInput bad = input;
        bad.jointWorld.pop_back();
        mca::PoseSkinResult ignored;
        std::string message;
        const bool ok = mca::solvePoseSkin(bad, options, ignored, message);
        check("refusal: missing joint transforms are refused", !ok, message);
    }
    {
        mca::PoseSkinOptions all = options;
        all.holdoutPoses.clear();
        for (int pose = 0; pose < static_cast<int>(input.poses.size()); ++pose) {
            all.holdoutPoses.push_back(pose);
        }
        mca::PoseSkinResult ignored;
        std::string message;
        const bool ok = mca::solvePoseSkin(input, all, ignored, message);
        check("refusal: holding every pose out is refused rather than fitted to nothing",
              !ok, message);
    }

    // ---- additive mode: add joints to a skin that already exists ------------ //
    //
    // The case this feature exists for, reduced to something with a known answer.
    //
    // A strip of vertices is skinned entirely to joint A, which never moves. A second
    // joint B moves, and the truth is built by skinning with KNOWN weights: the first
    // half of the strip shares itself between A and B, the second half stays fully on
    // A. Solved additively with A as the donor, the answer must be exactly those
    // weights - and, the part that matters, **B must come out at zero on the half of
    // the strip it does not drive**, which is the "cheek joint on the back of the
    // head" problem in miniature.
    {
        const int count = 40;
        const int half = count / 2;
        const int poses = 6;

        mca::PoseSkinInput add;
        for (int vertex = 0; vertex < count; ++vertex) {
            add.rest.push_back(mca::Vec3(static_cast<double>(vertex) * 0.5, 0.0, 0.0));
        }
        // Joint A at the origin, joint B further along. Row-vector convention.
        mca::Mat4 aRest;
        mca::Mat4 bRest;
        bRest.m[3][0] = 10.0;
        add.bindInverse.push_back(mca::inverse(aRest));   // joint 0 = A, the donor
        add.bindInverse.push_back(mca::inverse(bRest));   // joint 1 = B, the new joint

        // The truth: half the strip is 0.4 on B, the rest is 0 on B.
        std::vector<double> truth(static_cast<std::size_t>(count), 0.0);
        for (int vertex = 0; vertex < half; ++vertex) {
            truth[static_cast<std::size_t>(vertex)] = 0.4;
        }

        for (int pose = 0; pose < poses; ++pose) {
            const double lift = 0.3 * (pose + 1);
            mca::Mat4 aWorld = aRest;                     // A never moves
            mca::Mat4 bWorld = bRest;
            bWorld.m[3][1] += lift;                       // B translates in Y

            std::vector<mca::Mat4> world;
            world.push_back(aWorld);
            world.push_back(bWorld);
            add.jointWorld.push_back(world);

            std::vector<mca::Vec3> baseline;
            std::vector<mca::Vec3> donorPoint;
            std::vector<mca::Vec3> target;
            for (int vertex = 0; vertex < count; ++vertex) {
                const mca::Vec3& rest = add.rest[static_cast<std::size_t>(vertex)];
                const mca::Vec3 throughA =
                    mca::transformPoint(rest, mca::multiply(add.bindInverse[0], aWorld));
                const mca::Vec3 throughB =
                    mca::transformPoint(rest, mca::multiply(add.bindInverse[1], bWorld));
                // The existing skin is 100% A, so baseline and the donor's point agree.
                baseline.push_back(throughA);
                donorPoint.push_back(throughA);
                const double w = truth[static_cast<std::size_t>(vertex)];
                target.push_back(mca::Vec3(
                    (1.0 - w) * throughA.x + w * throughB.x,
                    (1.0 - w) * throughA.y + w * throughB.y,
                    (1.0 - w) * throughA.z + w * throughB.z));
            }
            add.baseline.push_back(baseline);
            add.donorPoint.push_back(donorPoint);
            add.poses.push_back(target);
        }
        add.donorWeight.assign(static_cast<std::size_t>(count), 1.0);

        mca::PoseSkinOptions additive;
        additive.additive = true;
        additive.maxInfluences = 2;
        additive.maxIterations = 1;
        additive.threads = 1;

        mca::PoseSkinResult got;
        std::string message;
        const bool ok = mca::solvePoseSkin(add, additive, got, message);
        check("additive: the solve runs", ok, message);

        if (ok) {
            double worstWeight = 0.0;
            double worstOffStrip = 0.0;
            int touchedBeyond = 0;
            for (int vertex = 0; vertex < count; ++vertex) {
                double onB = 0.0;
                const std::vector<int>& joints = got.vertexJoints[static_cast<std::size_t>(vertex)];
                const std::vector<double>& weights =
                    got.vertexWeights[static_cast<std::size_t>(vertex)];
                for (std::size_t slot = 0; slot < joints.size(); ++slot) {
                    if (joints[slot] == 1) {
                        onB += weights[slot];
                    }
                }
                const double want = truth[static_cast<std::size_t>(vertex)];
                worstWeight = std::max(worstWeight, std::fabs(onB - want));
                if (vertex >= half) {
                    worstOffStrip = std::max(worstOffStrip, onB);
                    if (onB > 1e-9) {
                        ++touchedBeyond;
                    }
                }
            }
            note("additive: worst weight error against the truth", number(worstWeight));
            note("additive: most weight B stole where it does not belong",
                 number(worstOffStrip));
            check("additive: the known weights are recovered", worstWeight < 1e-9,
                  number(worstWeight));
            check("additive: and the new joint takes NOTHING where it does not belong",
                  touchedBeyond == 0, std::to_string(touchedBeyond) + " vertices");
            check("additive: the fit is exact", got.rms < 1e-9, number(got.rms));
            check("additive: nothing was capped", got.cappedVertices == 0,
                  std::to_string(got.cappedVertices));
            check("additive: no vertex is reported as unweighted, which is normal here",
                  got.unweightedVertices.empty(),
                  std::to_string(got.unweightedVertices.size()));
        }

        // The same solve where the donor only holds a third: every weight must be
        // capped to what is actually available, rather than overdrawing the donor.
        mca::PoseSkinInput thin = add;
        thin.donorWeight.assign(static_cast<std::size_t>(count), 0.1);
        mca::PoseSkinResult capped;
        std::string capMessage;
        if (mca::solvePoseSkin(thin, additive, capped, capMessage)) {
            double most = 0.0;
            for (int vertex = 0; vertex < count; ++vertex) {
                double total = 0.0;
                for (double value : capped.vertexWeights[static_cast<std::size_t>(vertex)]) {
                    total += value;
                }
                most = std::max(most, total);
            }
            note("additive: most weight taken when the donor holds 0.1", number(most));
            check("additive: a new joint cannot take more than the donor has",
                  most <= 0.1 + 1e-12, number(most));
            check("additive: and capping is reported", capped.cappedVertices > 0,
                  std::to_string(capped.cappedVertices));
        }

        // A donor holding nothing can give nothing.
        mca::PoseSkinInput empty = add;
        empty.donorWeight.assign(static_cast<std::size_t>(count), 0.0);
        mca::PoseSkinResult none;
        std::string noneMessage;
        if (mca::solvePoseSkin(empty, additive, none, noneMessage)) {
            bool anything = false;
            for (int vertex = 0; vertex < count; ++vertex) {
                if (!none.vertexJoints[static_cast<std::size_t>(vertex)].empty()) {
                    anything = true;
                }
            }
            check("additive: a donor with no weight hands out none", !anything);
        }

        // And the inputs are checked rather than trusted.
        mca::PoseSkinInput short_ = add;
        short_.donorWeight.pop_back();
        mca::PoseSkinResult ignored;
        std::string why;
        check("additive: a donorWeight of the wrong length is refused, with a reason",
              !mca::solvePoseSkin(short_, additive, ignored, why) && why.size() > 20, why);
    }

    std::printf("%d/%d passed\n", gChecks - gFailures, gChecks);
    return gFailures == 0 ? 0 : 1;
}
