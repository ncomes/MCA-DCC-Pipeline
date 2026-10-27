// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// The driver: alternating weight and bone solves, the error report, and the
// pieces that make the weights usable as a skinCluster rather than merely
// optimal - the influence limit, the neighbourhood prior and the locality
// restriction.

#include "mca_pose_skin.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <queue>
#include <sstream>

namespace mca {
namespace {

constexpr double kTiny = 1e-12;

double distance(const Vec3& a, const Vec3& b) {
    const double dx = a.x - b.x;
    const double dy = a.y - b.y;
    const double dz = a.z - b.z;
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

/// The bounding-box diagonal of the rest mesh.
///
/// Every tunable in here is a fraction of this rather than a number in scene
/// units, so that `smoothing = 0.1` means the same thing on a mesh built in
/// centimetres and one built in metres. The tool this replaces took a raw
/// `lagragian` in scene units and defaulted it to 1.0, which on a 2-unit test
/// sphere behaves like a hard constraint and on a 200-unit character like
/// nothing at all - the same number doing two different jobs depending on how
/// big the model is.
double meshDiagonal(const std::vector<Vec3>& points) {
    if (points.empty()) {
        return 1.0;
    }
    Vec3 low = points[0];
    Vec3 high = points[0];
    for (const Vec3& point : points) {
        low.x = std::min(low.x, point.x);
        low.y = std::min(low.y, point.y);
        low.z = std::min(low.z, point.z);
        high.x = std::max(high.x, point.x);
        high.y = std::max(high.y, point.y);
        high.z = std::max(high.z, point.z);
    }
    const double diagonal = distance(low, high);
    return diagonal > kTiny ? diagonal : 1.0;
}

/// Everything about one vertex's weight solve that does not change between
/// pruning steps.
struct VertexSystem {
    /// Per candidate joint, the column of the data block plus the affinity entry.
    /// Column-major, because pruning drops columns and keeps rows.
    std::vector<std::vector<double>> columns;
    std::vector<double> rightHandSide;
    int dataRows = 0;
};

/// The per-vertex linear system, built once per vertex per round.
///
/// **The target position is subtracted from every column**, which is what makes
/// the fit independent of where the mesh sits in the world.
///
/// The system being solved is "find weights summing to one such that the weighted
/// sum of this vertex seen through each joint lands on where the vertex actually
/// is". Written the obvious way - columns are the candidate positions, the right
/// hand side is the target - the entries are absolute positions, so a character
/// standing 1000 units from the origin has entries a thousand times larger than
/// the same character at the origin, and the constraint rows that are NOT
/// positions then weigh a thousand times less against them. Same mesh, same
/// poses, different answer.
///
/// Subtracting the target from each column costs nothing and fixes it exactly:
/// since the weights sum to one, sum(w * (candidate - target)) is the same
/// residual as sum(w * candidate) - target, and now every entry is a deviation
/// rather than a position. Translate the whole setup and the system is
/// unchanged, to the bit.
void buildVertexSystem(const PoseSkinInput& input, const std::vector<int>& fittedPoses,
                       const std::vector<std::vector<Mat4>>& skin, int vertex,
                       const std::vector<int>& candidates, double affinityTerm,
                       bool additive, VertexSystem& out) {
    const int poseCount = static_cast<int>(fittedPoses.size());
    const int candidateCount = static_cast<int>(candidates.size());
    // No sum-to-one row in additive mode: the constraint there is a cap on the total
    // (what the donors hold), not an equality, and a penalty pulling the total toward
    // 1.0 would ask every vertex to hand its whole weight to the new joints.
    const bool useAffinity = affinityTerm > 0.0 && !additive;

    out.dataRows = 3 * poseCount + (useAffinity ? 1 : 0);
    out.columns.assign(static_cast<std::size_t>(candidateCount),
                       std::vector<double>(static_cast<std::size_t>(out.dataRows), 0.0));
    out.rightHandSide.assign(static_cast<std::size_t>(out.dataRows), 0.0);

    const Vec3& rest = input.rest[static_cast<std::size_t>(vertex)];

    for (int pose = 0; pose < poseCount; ++pose) {
        const std::size_t frame =
            static_cast<std::size_t>(fittedPoses[static_cast<std::size_t>(pose)]);
        const Vec3& target = input.poses[frame][static_cast<std::size_t>(vertex)];

        // What each candidate is subtracted from, and what the right-hand side is.
        //
        // Ordinary mode: subtract the TARGET from every column and leave the
        // right-hand side at zero. Since the weights sum to one,
        // sum(w * (moved - target)) is the same residual as sum(w * moved) - target,
        // and every entry is a deviation rather than a position - which is what makes
        // the fit independent of where the mesh sits in the world.
        //
        // Additive mode: subtract the DONOR's point, because weight given to a new
        // joint is weight taken off the donors, so what the joint changes is the
        // difference between the two. The right-hand side is then the residual the
        // existing skin cannot reach, and it is zero wherever that skin already fits.
        Vec3 subtract = target;
        Vec3 rightHand(0.0, 0.0, 0.0);
        if (additive) {
            subtract = input.donorPoint[frame][static_cast<std::size_t>(vertex)];
            const Vec3& base = input.baseline[frame][static_cast<std::size_t>(vertex)];
            rightHand = Vec3(target.x - base.x, target.y - base.y, target.z - base.z);
            out.rightHandSide[static_cast<std::size_t>(3 * pose + 0)] = rightHand.x;
            out.rightHandSide[static_cast<std::size_t>(3 * pose + 1)] = rightHand.y;
            out.rightHandSide[static_cast<std::size_t>(3 * pose + 2)] = rightHand.z;
        }

        for (int index = 0; index < candidateCount; ++index) {
            const int joint = candidates[static_cast<std::size_t>(index)];
            const Vec3 moved = transformPoint(
                rest, skin[static_cast<std::size_t>(pose)][static_cast<std::size_t>(joint)]);
            std::vector<double>& column = out.columns[static_cast<std::size_t>(index)];
            column[static_cast<std::size_t>(3 * pose + 0)] = moved.x - subtract.x;
            column[static_cast<std::size_t>(3 * pose + 1)] = moved.y - subtract.y;
            column[static_cast<std::size_t>(3 * pose + 2)] = moved.z - subtract.z;
        }
    }

    if (useAffinity) {
        const int row = 3 * poseCount;
        for (int index = 0; index < candidateCount; ++index) {
            out.columns[static_cast<std::size_t>(index)][static_cast<std::size_t>(row)] =
                affinityTerm;
        }
        out.rightHandSide[static_cast<std::size_t>(row)] = affinityTerm;
    }
}

/// Assemble the row-major matrix for a subset of the candidates, adding one
/// neighbourhood-prior row per kept candidate when there is a prior to apply.
void assemble(const VertexSystem& system, const std::vector<int>& keep,
              const std::vector<double>& prior, double smoothTerm,
              std::vector<double>& matrix, std::vector<double>& target, int& rows,
              int& columns) {
    const bool usePrior = smoothTerm > 0.0 && !prior.empty();
    columns = static_cast<int>(keep.size());
    rows = system.dataRows + (usePrior ? columns : 0);
    matrix.assign(static_cast<std::size_t>(rows) * static_cast<std::size_t>(columns), 0.0);
    target.assign(static_cast<std::size_t>(rows), 0.0);

    for (int row = 0; row < system.dataRows; ++row) {
        target[static_cast<std::size_t>(row)] =
            system.rightHandSide[static_cast<std::size_t>(row)];
        for (int column = 0; column < columns; ++column) {
            matrix[static_cast<std::size_t>(row) * static_cast<std::size_t>(columns) +
                   static_cast<std::size_t>(column)] =
                system.columns[static_cast<std::size_t>(keep[static_cast<std::size_t>(column)])]
                              [static_cast<std::size_t>(row)];
        }
    }

    if (!usePrior) {
        return;
    }
    for (int column = 0; column < columns; ++column) {
        const int row = system.dataRows + column;
        matrix[static_cast<std::size_t>(row) * static_cast<std::size_t>(columns) +
               static_cast<std::size_t>(column)] = smoothTerm;
        target[static_cast<std::size_t>(row)] =
            smoothTerm * prior[static_cast<std::size_t>(keep[static_cast<std::size_t>(column)])];
    }
}

/// Sort by descending weight, ties broken by ascending joint index so that two
/// runs of the same input cannot disagree about the order.
void sortByWeight(std::vector<int>& joints, std::vector<double>& weights) {
    std::vector<int> order(joints.size());
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
        if (weights[static_cast<std::size_t>(a)] != weights[static_cast<std::size_t>(b)]) {
            return weights[static_cast<std::size_t>(a)] > weights[static_cast<std::size_t>(b)];
        }
        return joints[static_cast<std::size_t>(a)] < joints[static_cast<std::size_t>(b)];
    });
    std::vector<int> sortedJoints(joints.size());
    std::vector<double> sortedWeights(weights.size());
    for (std::size_t index = 0; index < order.size(); ++index) {
        sortedJoints[index] = joints[static_cast<std::size_t>(order[index])];
        sortedWeights[index] = weights[static_cast<std::size_t>(order[index])];
    }
    joints.swap(sortedJoints);
    weights.swap(sortedWeights);
}

}  // namespace

bool solvePoseSkin(const PoseSkinInput& input, const PoseSkinOptions& options,
                   PoseSkinResult& result, std::string& error) {
    error.clear();

    // Before anything goes parallel, and on this thread. See prepareParallel().
    prepareParallel();

    const int vertexCount = static_cast<int>(input.rest.size());
    const int poseCount = static_cast<int>(input.poses.size());
    const int jointCount = static_cast<int>(input.bindInverse.size());

    if (vertexCount <= 0) {
        error = "No rest positions - there is no mesh to fit.";
        return false;
    }
    if (poseCount <= 0) {
        error = "No poses. A skin cannot be solved from a rest shape alone: the weights "
                "are whatever reproduces the DIFFERENCE between rest and posed, and with "
                "no posed shape every weight fits equally well.";
        return false;
    }
    if (jointCount <= 0) {
        error = "No joints.";
        return false;
    }
    if (static_cast<int>(input.jointWorld.size()) != poseCount) {
        std::ostringstream stream;
        stream << "Got " << poseCount << " pose(s) but " << input.jointWorld.size()
               << " set(s) of joint transforms. They have to match, one set per pose.";
        error = stream.str();
        return false;
    }
    for (int pose = 0; pose < poseCount; ++pose) {
        if (static_cast<int>(input.poses[static_cast<std::size_t>(pose)].size()) !=
            vertexCount) {
            std::ostringstream stream;
            stream << "Pose " << pose << " has "
                   << input.poses[static_cast<std::size_t>(pose)].size()
                   << " vertices and the rest mesh has " << vertexCount
                   << ". Every pose must be the same mesh.";
            error = stream.str();
            return false;
        }
        if (static_cast<int>(input.jointWorld[static_cast<std::size_t>(pose)].size()) !=
            jointCount) {
            std::ostringstream stream;
            stream << "Pose " << pose << " carries "
                   << input.jointWorld[static_cast<std::size_t>(pose)].size()
                   << " joint transforms and there are " << jointCount << " joints.";
            error = stream.str();
            return false;
        }
    }
    if (!input.importance.empty() &&
        static_cast<int>(input.importance.size()) != vertexCount) {
        error = "importance must have one entry per vertex, or none at all.";
        return false;
    }
    if (options.additive) {
        // Checked here rather than trusted, because every one of these being the
        // wrong length produces a plausible-looking answer rather than a crash.
        if (static_cast<int>(input.donorWeight.size()) != vertexCount) {
            error = "additive mode needs one donorWeight per vertex.";
            return false;
        }
        if (input.baseline.size() != input.poses.size() ||
            input.donorPoint.size() != input.poses.size()) {
            error = "additive mode needs a baseline and a donorPoint for every pose.";
            return false;
        }
        for (std::size_t pose = 0; pose < input.poses.size(); ++pose) {
            if (static_cast<int>(input.baseline[pose].size()) != vertexCount ||
                static_cast<int>(input.donorPoint[pose].size()) != vertexCount) {
                error = "additive mode needs a baseline and a donorPoint per vertex per pose.";
                return false;
            }
        }
    }

    if (!input.candidates.empty() &&
        static_cast<int>(input.candidates.size()) != vertexCount) {
        error = "candidates must have one entry per vertex, or none at all.";
        return false;
    }

    const int maxInfluences = std::max(1, std::min(options.maxInfluences, jointCount));

    // Which poses are fitted and which are held back.
    std::vector<bool> heldOut(static_cast<std::size_t>(poseCount), false);
    for (int pose : options.holdoutPoses) {
        if (pose >= 0 && pose < poseCount) {
            heldOut[static_cast<std::size_t>(pose)] = true;
        }
    }
    std::vector<int> fittedPoses;
    std::vector<int> holdoutPoses;
    for (int pose = 0; pose < poseCount; ++pose) {
        if (heldOut[static_cast<std::size_t>(pose)]) {
            holdoutPoses.push_back(pose);
        } else {
            fittedPoses.push_back(pose);
        }
    }
    if (fittedPoses.empty()) {
        error = "Every pose was held out, so there is nothing left to fit.";
        return false;
    }

    const double scale = meshDiagonal(input.rest);
    const double affinityTerm = std::max(0.0, options.affinity) * scale;
    const double smoothTerm = std::max(0.0, options.smoothing) * scale;
    const bool useSmoothing = smoothTerm > 0.0 && !input.neighbours.empty();
    const int smoothingRounds = useSmoothing ? std::max(1, options.smoothingRounds) : 1;

    result = PoseSkinResult();
    result.bindInverse = input.bindInverse;
    result.jointWorld = input.jointWorld;
    result.vertexJoints.assign(static_cast<std::size_t>(vertexCount), std::vector<int>());
    result.vertexWeights.assign(static_cast<std::size_t>(vertexCount), std::vector<double>());
    result.vertexError.assign(static_cast<std::size_t>(vertexCount), 0.0);
    result.poseError.assign(static_cast<std::size_t>(poseCount), 0.0);

    // Candidate joints per vertex: an explicit restriction if the caller gave
    // one, else the nearest few if locality is on, else everything.
    std::vector<std::vector<int>> candidates(static_cast<std::size_t>(vertexCount));
    std::vector<int> allJoints(static_cast<std::size_t>(jointCount));
    std::iota(allJoints.begin(), allJoints.end(), 0);

    std::vector<Vec3> jointRest(static_cast<std::size_t>(jointCount));
    for (int joint = 0; joint < jointCount; ++joint) {
        const Mat4 forward = inverse(input.bindInverse[static_cast<std::size_t>(joint)]);
        jointRest[static_cast<std::size_t>(joint)] =
            Vec3(forward.m[3][0], forward.m[3][1], forward.m[3][2]);
    }

    const int locality = options.localityJoints > 0
                             ? std::max(maxInfluences, options.localityJoints)
                             : 0;

    // Surface distance from every joint to every vertex, when asked for: one
    // Dijkstra per joint over the mesh's own edges, seeded at the vertex nearest
    // that joint. J passes over V vertices, which on a face is 120 x 5,348 and
    // costs less than one iteration of the solve.
    //
    // A vertex no path reaches keeps its infinity and that joint is simply not a
    // candidate for it - which is how a separate eyeball or tongue shell stops
    // being weighted to the jaw.
    std::vector<std::vector<double>> surfaceDistance;
    const bool useGeodesic = locality > 0 && options.geodesicLocality &&
                             !input.neighbours.empty() &&
                             static_cast<int>(input.neighbours.size()) == vertexCount;
    if (useGeodesic) {
        surfaceDistance.assign(static_cast<std::size_t>(jointCount), std::vector<double>());
        const double infinity = std::numeric_limits<double>::infinity();
        for (int joint = 0; joint < jointCount; ++joint) {
            // Seed at the vertex closest to where the joint sits. A joint inside the
            // head is closest to the skin above it, which is the right place to walk
            // from.
            int seed = 0;
            double best = infinity;
            for (int vertex = 0; vertex < vertexCount; ++vertex) {
                const double d = distance(input.rest[static_cast<std::size_t>(vertex)],
                                          jointRest[static_cast<std::size_t>(joint)]);
                if (d < best) {
                    best = d;
                    seed = vertex;
                }
            }

            std::vector<double>& along = surfaceDistance[static_cast<std::size_t>(joint)];
            along.assign(static_cast<std::size_t>(vertexCount), infinity);
            // The distance from the joint to its seed counts, or two joints seeded
            // on the same vertex would be equally close to everything.
            along[static_cast<std::size_t>(seed)] = best;

            using Entry = std::pair<double, int>;
            std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>> queue;
            queue.push(Entry(best, seed));
            while (!queue.empty()) {
                const Entry top = queue.top();
                queue.pop();
                const int vertex = top.second;
                if (top.first > along[static_cast<std::size_t>(vertex)]) {
                    continue;
                }
                for (int other : input.neighbours[static_cast<std::size_t>(vertex)]) {
                    if (other < 0 || other >= vertexCount) {
                        continue;
                    }
                    const double step = top.first +
                                        distance(input.rest[static_cast<std::size_t>(vertex)],
                                                 input.rest[static_cast<std::size_t>(other)]);
                    if (step < along[static_cast<std::size_t>(other)]) {
                        along[static_cast<std::size_t>(other)] = step;
                        queue.push(Entry(step, other));
                    }
                }
            }
        }
    }

    for (int vertex = 0; vertex < vertexCount; ++vertex) {
        if (!input.candidates.empty() &&
            !input.candidates[static_cast<std::size_t>(vertex)].empty()) {
            std::vector<int> given;
            for (int joint : input.candidates[static_cast<std::size_t>(vertex)]) {
                if (joint >= 0 && joint < jointCount) {
                    given.push_back(joint);
                }
            }
            std::sort(given.begin(), given.end());
            given.erase(std::unique(given.begin(), given.end()), given.end());
            candidates[static_cast<std::size_t>(vertex)] = given;
        } else if (locality > 0 && locality < jointCount) {
            // The nearest joints, either through the air or across the surface.
            std::vector<int> order = allJoints;
            const Vec3& rest = input.rest[static_cast<std::size_t>(vertex)];
            const auto nearness = [&](int joint) {
                return useGeodesic
                           ? surfaceDistance[static_cast<std::size_t>(joint)]
                                            [static_cast<std::size_t>(vertex)]
                           : distance(rest, jointRest[static_cast<std::size_t>(joint)]);
            };
            std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
                const double da = nearness(a);
                const double db = nearness(b);
                if (da != db) {
                    return da < db;
                }
                return a < b;
            });
            order.resize(static_cast<std::size_t>(locality));
            // A joint the surface never reaches is not a candidate at all, however
            // few that leaves - unless it would leave the vertex with none, in which
            // case something is wrong with the mesh and the straight-line answer
            // beats no answer.
            if (useGeodesic) {
                std::vector<int> reachable;
                for (int joint : order) {
                    if (std::isfinite(nearness(joint))) {
                        reachable.push_back(joint);
                    }
                }
                if (!reachable.empty()) {
                    order.swap(reachable);
                }
            }
            std::sort(order.begin(), order.end());
            candidates[static_cast<std::size_t>(vertex)] = order;
        } else {
            candidates[static_cast<std::size_t>(vertex)] = allJoints;
        }
        if (candidates[static_cast<std::size_t>(vertex)].empty()) {
            candidates[static_cast<std::size_t>(vertex)] = allJoints;
        }
    }

    // The skinning matrix per fitted pose per joint, rebuilt whenever the bones
    // move.
    std::vector<std::vector<Mat4>> fittedSkin(fittedPoses.size());
    auto rebuildSkin = [&]() {
        for (std::size_t pose = 0; pose < fittedPoses.size(); ++pose) {
            fittedSkin[pose].resize(static_cast<std::size_t>(jointCount));
            for (int joint = 0; joint < jointCount; ++joint) {
                fittedSkin[pose][static_cast<std::size_t>(joint)] =
                    multiply(result.bindInverse[static_cast<std::size_t>(joint)],
                             result.jointWorld[static_cast<std::size_t>(
                                 fittedPoses[pose])][static_cast<std::size_t>(joint)]);
            }
        }
    };
    rebuildSkin();

    // Where a vertex ends up, which is not the same question in the two modes.
    //
    // Ordinary: the weighted sum of the vertex seen through each of its joints.
    // Additive: the existing skin's answer, plus what each new joint CHANGES - which
    // is its own point less the donor's, because its weight came out of the donor.
    //
    // One definition, used by every error pass and by the report, so a number in the
    // message can never disagree with the number a check recomputes.
    auto posedPoint = [&](int vertex, int pose) -> Vec3 {
        const std::size_t v = static_cast<std::size_t>(vertex);
        const std::size_t f = static_cast<std::size_t>(pose);
        if (!options.additive) {
            return skinPoint(input.rest[v], result.vertexJoints[v], result.vertexWeights[v],
                             result.bindInverse, result.jointWorld[f]);
        }
        const Vec3& donor = input.donorPoint[f][v];
        Vec3 out = input.baseline[f][v];
        const std::vector<int>& joints = result.vertexJoints[v];
        const std::vector<double>& weights = result.vertexWeights[v];
        for (std::size_t slot = 0; slot < joints.size(); ++slot) {
            const std::size_t joint = static_cast<std::size_t>(joints[slot]);
            const Vec3 moved = transformPoint(
                input.rest[v], multiply(result.bindInverse[joint], result.jointWorld[f][joint]));
            out.x += weights[slot] * (moved.x - donor.x);
            out.y += weights[slot] * (moved.y - donor.y);
            out.z += weights[slot] * (moved.z - donor.z);
        }
        return out;
    };

    const int threads = options.threads > 0 ? options.threads : 0;
    const int iterations = std::max(1, options.maxIterations);
    const bool solveBones = options.solveBones && iterations > 1;

    std::vector<double> previousRms;

    // Set by a worker thread that caught something, read after the region closes.
    // Plain bool and std::string rather than atomics: only ever set to the same
    // value, only ever read once the region has joined.
    bool failure = false;
    std::string failureText;

    for (int iteration = 0; iteration < iterations; ++iteration) {
        if (iteration > 0 && options.interrupted && options.interrupted()) {
            result.cancelled = true;
            break;
        }
        result.iterationsDone = iteration + 1;

        if (iteration > 0 && solveBones) {
            // Move each joint to the middle of what it actually weights, then
            // refit its transform in every pose. Bind pose first: the transform
            // fit below is relative to it.
            if (options.updateBindPose) {
                for (int joint = 0; joint < jointCount; ++joint) {
                    double total = 0.0;
                    Vec3 centroid;
                    for (int vertex = 0; vertex < vertexCount; ++vertex) {
                        const std::vector<int>& joints =
                            result.vertexJoints[static_cast<std::size_t>(vertex)];
                        for (std::size_t slot = 0; slot < joints.size(); ++slot) {
                            if (joints[slot] != joint) {
                                continue;
                            }
                            const double weight =
                                result.vertexWeights[static_cast<std::size_t>(vertex)][slot];
                            total += weight;
                            centroid.x += weight * input.rest[static_cast<std::size_t>(vertex)].x;
                            centroid.y += weight * input.rest[static_cast<std::size_t>(vertex)].y;
                            centroid.z += weight * input.rest[static_cast<std::size_t>(vertex)].z;
                        }
                    }
                    if (total <= kTiny) {
                        continue;
                    }
                    Mat4 forward = inverse(result.bindInverse[static_cast<std::size_t>(joint)]);
                    forward.m[3][0] = centroid.x / total;
                    forward.m[3][1] = centroid.y / total;
                    forward.m[3][2] = centroid.z / total;
                    result.bindInverse[static_cast<std::size_t>(joint)] = inverse(forward);
                }
            }

            // Bone transforms are per pose, so they are fitted for the held-out
            // poses too. What is being validated is the WEIGHTS - the thing that
            // is shared between poses and that an animator cannot change per
            // frame. Holding a pose's own bone transform out as well would
            // measure something nobody is asking for.
            std::vector<std::vector<int>> degeneratePerPose(
                static_cast<std::size_t>(poseCount));

            // Which vertices each joint actually weights, worked out ONCE rather
            // than per pose.
            //
            // The obvious loop - for each pose, for each joint, walk every vertex
            // looking for that joint - is poses x joints x vertices, and on a face
            // that is 173 x 60 x 5348 = 55 million passes to find the same lists
            // over and over. The lists do not depend on the pose.
            std::vector<std::vector<int>> jointVertices(static_cast<std::size_t>(jointCount));
            std::vector<std::vector<double>> jointWeights(static_cast<std::size_t>(jointCount));
            for (int vertex = 0; vertex < vertexCount; ++vertex) {
                const std::vector<int>& joints =
                    result.vertexJoints[static_cast<std::size_t>(vertex)];
                const std::vector<double>& weights =
                    result.vertexWeights[static_cast<std::size_t>(vertex)];
                for (std::size_t slot = 0; slot < joints.size(); ++slot) {
                    if (weights[slot] <= options.weightFloor) {
                        continue;
                    }
                    jointVertices[static_cast<std::size_t>(joints[slot])].push_back(vertex);
                    jointWeights[static_cast<std::size_t>(joints[slot])].push_back(weights[slot]);
                }
            }

            parallelFor(poseCount, threads, [&](int pose) {
                std::vector<Mat4> skin(static_cast<std::size_t>(jointCount));
                for (int joint = 0; joint < jointCount; ++joint) {
                    skin[static_cast<std::size_t>(joint)] =
                        multiply(result.bindInverse[static_cast<std::size_t>(joint)],
                                 result.jointWorld[static_cast<std::size_t>(pose)]
                                                  [static_cast<std::size_t>(joint)]);
                }

                for (int joint = 0; joint < jointCount; ++joint) {
                    std::vector<Vec3> from;
                    std::vector<Vec3> to;
                    std::vector<double> fitWeights;

                    const std::vector<int>& mine =
                        jointVertices[static_cast<std::size_t>(joint)];
                    for (std::size_t item = 0; item < mine.size(); ++item) {
                        const int vertex = mine[item];
                        const std::vector<int>& joints =
                            result.vertexJoints[static_cast<std::size_t>(vertex)];
                        const std::vector<double>& weights =
                            result.vertexWeights[static_cast<std::size_t>(vertex)];
                        const double own =
                            jointWeights[static_cast<std::size_t>(joint)][item];

                        // What this joint has to account for: the pose, less
                        // what every other joint on this vertex already
                        // contributes.
                        //
                        // In additive mode both halves shift. The pose becomes the
                        // residual the existing skin cannot reach, and each other
                        // joint contributes its point LESS the donor's, because its
                        // weight came out of the donor. Solving
                        // t_j*(T_j - donor) = residual - sum_other for T_j then puts
                        // the donor's point back, below.
                        const std::size_t frame = static_cast<std::size_t>(pose);
                        const std::size_t vindex = static_cast<std::size_t>(vertex);
                        Vec3 residual = input.poses[frame][vindex];
                        Vec3 donor(0.0, 0.0, 0.0);
                        if (options.additive) {
                            donor = input.donorPoint[frame][vindex];
                            const Vec3& base = input.baseline[frame][vindex];
                            residual.x -= base.x;
                            residual.y -= base.y;
                            residual.z -= base.z;
                        }
                        for (std::size_t slot = 0; slot < joints.size(); ++slot) {
                            if (joints[slot] == joint) {
                                continue;
                            }
                            const Vec3 moved = transformPoint(
                                input.rest[vindex],
                                skin[static_cast<std::size_t>(joints[slot])]);
                            residual.x -= weights[slot] * (moved.x - donor.x);
                            residual.y -= weights[slot] * (moved.y - donor.y);
                            residual.z -= weights[slot] * (moved.z - donor.z);
                        }

                        // Minimising |w * (rest * T) - residual| over T is the
                        // same weighted point fit as taking residual/w as the
                        // target with w^2 as the weight, which is how this reuses
                        // fitTransform rather than growing a second copy of it.
                        const double importance =
                            input.importance.empty()
                                ? 1.0
                                : std::max(0.0,
                                           input.importance[static_cast<std::size_t>(vertex)]);
                        if (importance <= 0.0) {
                            continue;
                        }
                        from.push_back(input.rest[vindex]);
                        to.push_back(Vec3(donor.x + residual.x / own,
                                          donor.y + residual.y / own,
                                          donor.z + residual.z / own));
                        fitWeights.push_back(own * own * importance);
                    }

                    if (from.size() < 3) {
                        // Fewer than three points cannot pin a rotation. Leaving
                        // the transform alone is right; saying so is the point.
                        degeneratePerPose[static_cast<std::size_t>(pose)].push_back(joint);
                        continue;
                    }

                    Mat4 fitted;
                    bool degenerate = false;
                    if (!fitTransform(from, to, fitWeights, options.rigidBones, fitted,
                                      &degenerate)) {
                        degeneratePerPose[static_cast<std::size_t>(pose)].push_back(joint);
                        continue;
                    }
                    if (degenerate) {
                        degeneratePerPose[static_cast<std::size_t>(pose)].push_back(joint);
                    }
                    skin[static_cast<std::size_t>(joint)] = fitted;
                    result.jointWorld[static_cast<std::size_t>(pose)]
                                     [static_cast<std::size_t>(joint)] =
                        multiply(inverse(result.bindInverse[static_cast<std::size_t>(joint)]),
                                 fitted);
                }
            }, &failureText);
            if (!failureText.empty()) {
                failure = true;
            }

            std::vector<int> degenerate;
            for (int pose = 0; pose < poseCount; ++pose) {
                for (int joint : degeneratePerPose[static_cast<std::size_t>(pose)]) {
                    degenerate.push_back(joint);
                }
            }
            std::sort(degenerate.begin(), degenerate.end());
            degenerate.erase(std::unique(degenerate.begin(), degenerate.end()),
                             degenerate.end());
            result.degenerateJoints = degenerate;

            rebuildSkin();
        }

        // ---- weights ------------------------------------------------------- //
        for (int round = 0; round < smoothingRounds; ++round) {
            if (round > 0 && options.interrupted && options.interrupted()) {
                result.cancelled = true;
                break;
            }
            const bool applyPrior = useSmoothing && round > 0;

            // The prior is read from the PREVIOUS round's weights, so every
            // vertex in a round sees the same neighbourhood - which is what keeps
            // the result independent of the order vertices are solved in, and
            // therefore independent of the thread count.
            std::vector<std::vector<int>> previousJoints;
            std::vector<std::vector<double>> previousWeights;
            if (applyPrior) {
                previousJoints = result.vertexJoints;
                previousWeights = result.vertexWeights;
            }

            std::vector<int> cappedPerVertex(static_cast<std::size_t>(vertexCount), 0);
            parallelFor(vertexCount, threads, [&](int vertex) {
                int capped = 0;
                const std::vector<int>& vertexCandidates =
                    candidates[static_cast<std::size_t>(vertex)];

                // A vertex the donors hold nothing at can receive nothing, so there
                // is nothing to solve. Leaving it empty is the answer, and it is what
                // keeps every influence the user did not nominate untouched.
                if (options.additive &&
                    input.donorWeight[static_cast<std::size_t>(vertex)] <= options.weightFloor) {
                    result.vertexJoints[static_cast<std::size_t>(vertex)].clear();
                    result.vertexWeights[static_cast<std::size_t>(vertex)].clear();
                    return;
                }

                VertexSystem system;
                buildVertexSystem(input, fittedPoses, fittedSkin, vertex, vertexCandidates,
                                  affinityTerm, options.additive, system);

                std::vector<double> prior;
                if (applyPrior) {
                    prior.assign(vertexCandidates.size(), 0.0);
                    const std::vector<int>& around =
                        input.neighbours[static_cast<std::size_t>(vertex)];
                    if (!around.empty()) {
                        std::vector<double> perJoint(static_cast<std::size_t>(jointCount), 0.0);
                        int counted = 0;
                        for (int other : around) {
                            if (other < 0 || other >= vertexCount) {
                                continue;
                            }
                            ++counted;
                            const std::vector<int>& joints =
                                previousJoints[static_cast<std::size_t>(other)];
                            const std::vector<double>& weights =
                                previousWeights[static_cast<std::size_t>(other)];
                            for (std::size_t slot = 0; slot < joints.size(); ++slot) {
                                perJoint[static_cast<std::size_t>(joints[slot])] += weights[slot];
                            }
                        }
                        if (counted > 0) {
                            for (std::size_t index = 0; index < vertexCandidates.size();
                                 ++index) {
                                prior[index] =
                                    perJoint[static_cast<std::size_t>(
                                        vertexCandidates[index])] /
                                    static_cast<double>(counted);
                            }
                        }
                    }
                }

                std::vector<int> keep(vertexCandidates.size());
                std::iota(keep.begin(), keep.end(), 0);

                std::vector<double> matrix;
                std::vector<double> target;
                std::vector<double> solution;
                int rows = 0;
                int columns = 0;

                while (true) {
                    assemble(system, keep, prior, applyPrior ? smoothTerm : 0.0, matrix, target,
                             rows, columns);
                    solveNonNegative(matrix, rows, columns, target, solution,
                                     options.nnlsIterations);

                    int used = 0;
                    for (double value : solution) {
                        if (value > options.weightFloor) {
                            ++used;
                        }
                    }
                    if (used <= maxInfluences) {
                        break;
                    }

                    if (options.prunePerStep) {
                        // Drop ONE - the smallest weight that is still in play -
                        // and solve again. Every drop changes the answer for
                        // everything that is left, so dropping several at once
                        // throws away joints that would have grown to matter.
                        int worst = -1;
                        double worstValue = std::numeric_limits<double>::infinity();
                        for (std::size_t index = 0; index < solution.size(); ++index) {
                            if (solution[index] > options.weightFloor &&
                                solution[index] < worstValue) {
                                worstValue = solution[index];
                                worst = static_cast<int>(index);
                            }
                        }
                        if (worst < 0) {
                            break;
                        }
                        keep.erase(keep.begin() + worst);
                    } else {
                        std::vector<int> order(solution.size());
                        std::iota(order.begin(), order.end(), 0);
                        std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
                            return solution[static_cast<std::size_t>(a)] >
                                   solution[static_cast<std::size_t>(b)];
                        });
                        order.resize(static_cast<std::size_t>(maxInfluences));
                        std::sort(order.begin(), order.end());
                        std::vector<int> reduced;
                        for (int index : order) {
                            reduced.push_back(keep[static_cast<std::size_t>(index)]);
                        }
                        keep.swap(reduced);
                        assemble(system, keep, prior, applyPrior ? smoothTerm : 0.0, matrix,
                                 target, rows, columns);
                        solveNonNegative(matrix, rows, columns, target, solution,
                                         options.nnlsIterations);
                        break;
                    }
                }

                std::vector<int> joints;
                std::vector<double> weights;
                double total = 0.0;
                for (std::size_t index = 0; index < keep.size(); ++index) {
                    const double value = solution[index];
                    if (value <= options.weightFloor) {
                        continue;
                    }
                    joints.push_back(
                        vertexCandidates[static_cast<std::size_t>(keep[index])]);
                    weights.push_back(value);
                    total += value;
                }

                if (options.additive) {
                    // **Neither of the two steps below may run in additive mode**, and
                    // each would be a bug of its own.
                    //
                    // The fallback would force weight onto a vertex that earned none -
                    // and a vertex earning none is the CORRECT answer for most of the
                    // mesh here. That is the whole feature: reintroducing a forced
                    // influence is precisely the "cheek joint on the back of the head"
                    // problem this mode exists to remove.
                    //
                    // Normalising would turn a vertex that legitimately takes 0.03 of
                    // the donor's weight into 1.0, wiping the donor out.
                    //
                    // What does apply is the cap. The donors only have so much to give.
                    const double available = input.donorWeight[static_cast<std::size_t>(vertex)];
                    if (total > available && total > kTiny) {
                        const double scale = available / total;
                        for (double& value : weights) {
                            value *= scale;
                        }
                        ++capped;
                    }
                } else {
                    if (joints.empty()) {
                        // Nothing came out above the floor. Rather than leave the
                        // vertex with no influence at all - which in Maya is a vertex
                        // that stays at the bind pose and reads as a hole in the mesh
                        // - give it the best single candidate. Recorded below, so the
                        // caller can say so.
                        int best = vertexCandidates.front();
                        double bestValue = -1.0;
                        for (std::size_t index = 0; index < keep.size(); ++index) {
                            if (solution[index] > bestValue) {
                                bestValue = solution[index];
                                best = vertexCandidates[static_cast<std::size_t>(keep[index])];
                            }
                        }
                        joints.assign(1, best);
                        weights.assign(1, 1.0);
                        total = 1.0;
                    }

                    for (double& value : weights) {
                        value /= total;
                    }
                }
                sortByWeight(joints, weights);

                result.vertexJoints[static_cast<std::size_t>(vertex)] = joints;
                result.vertexWeights[static_cast<std::size_t>(vertex)] = weights;
                cappedPerVertex[static_cast<std::size_t>(vertex)] = capped;
            }, &failureText);
            // Summed in vertex order rather than as the threads finish, so the number
            // is the same on any thread count.
            result.cappedVertices = 0;
            for (int each : cappedPerVertex) {
                result.cappedVertices += each;
            }
            if (!failureText.empty()) {
                failure = true;
                break;
            }
        }

        if (failure) {
            error = "The solve failed on at least one vertex or bone: " + failureText;
            return false;
        }

        // ---- error --------------------------------------------------------- //
        std::vector<double> poseSums(static_cast<std::size_t>(poseCount), 0.0);

        parallelFor(poseCount, threads, [&](int pose) {
            double sum = 0.0;
            for (int vertex = 0; vertex < vertexCount; ++vertex) {
                const Vec3 skinned = posedPoint(vertex, pose);
                const double d = distance(skinned, input.poses[static_cast<std::size_t>(pose)]
                                                             [static_cast<std::size_t>(vertex)]);
                sum += d * d;
            }
            poseSums[static_cast<std::size_t>(pose)] = sum;
            result.poseError[static_cast<std::size_t>(pose)] =
                std::sqrt(sum / static_cast<double>(vertexCount));
        }, nullptr);

        parallelFor(vertexCount, threads, [&](int vertex) {
            double worst = 0.0;
            for (int pose : fittedPoses) {
                const Vec3 skinned = posedPoint(vertex, pose);
                worst = std::max(worst,
                                 distance(skinned, input.poses[static_cast<std::size_t>(pose)]
                                                              [static_cast<std::size_t>(vertex)]));
            }
            result.vertexError[static_cast<std::size_t>(vertex)] = worst;
        }, nullptr);

        // Summed in pose order rather than as they finish, so the total is the
        // same every run.
        double fittedSum = 0.0;
        double fittedWorst = 0.0;
        for (int pose : fittedPoses) {
            fittedSum += poseSums[static_cast<std::size_t>(pose)];
            fittedWorst = std::max(fittedWorst, result.poseError[static_cast<std::size_t>(pose)]);
        }
        result.rms = std::sqrt(fittedSum / static_cast<double>(vertexCount) /
                               static_cast<double>(fittedPoses.size()));
        result.worst = 0.0;
        for (double value : result.vertexError) {
            result.worst = std::max(result.worst, value);
        }
        result.iterationRms.push_back(result.rms);

        if (!holdoutPoses.empty()) {
            double sum = 0.0;
            for (int pose : holdoutPoses) {
                sum += poseSums[static_cast<std::size_t>(pose)];
            }
            result.holdoutRms = std::sqrt(sum / static_cast<double>(vertexCount) /
                                          static_cast<double>(holdoutPoses.size()));
            // Per vertex first, then reduced in vertex order, so the answer does
            // not depend on which thread finished when. This was originally written
            // by hand because MSVC's /openmp is still OpenMP 2.0 and has no
            // `reduction(max:)`; it stays written by hand now that there is no
            // OpenMP here at all, for the determinism.
            std::vector<double> holdoutPerVertex(static_cast<std::size_t>(vertexCount), 0.0);
            parallelFor(vertexCount, threads, [&](int vertex) {
                double worst = 0.0;
                for (int pose : holdoutPoses) {
                    const Vec3 skinned = posedPoint(vertex, pose);
                    worst = std::max(
                        worst, distance(skinned, input.poses[static_cast<std::size_t>(pose)]
                                                            [static_cast<std::size_t>(vertex)]));
                }
                holdoutPerVertex[static_cast<std::size_t>(vertex)] = worst;
            }, nullptr);
            double worst = 0.0;
            for (double value : holdoutPerVertex) {
                worst = std::max(worst, value);
            }
            result.holdoutWorst = worst;
        }

        if (options.progress) {
            options.progress(result.iterationsDone, result.rms);
        }

        if (iteration > 0 && options.improvementBreak > 0.0) {
            const double previous = result.iterationRms[result.iterationRms.size() - 2];
            if (previous > kTiny) {
                const double improvement = (previous - result.rms) / previous;
                if (improvement < options.improvementBreak) {
                    break;
                }
            }
        }
    }

    // Not reported in additive mode: a vertex the new joints leave alone is the
    // expected answer there, not a hole in the skin.
    for (int vertex = 0; !options.additive && vertex < vertexCount; ++vertex) {
        if (result.vertexJoints[static_cast<std::size_t>(vertex)].size() == 1 &&
            result.vertexWeights[static_cast<std::size_t>(vertex)][0] >= 1.0 - 1e-9 &&
            result.vertexError[static_cast<std::size_t>(vertex)] > 0.5 * scale) {
            result.unweightedVertices.push_back(vertex);
        }
    }

    std::ostringstream stream;
    stream.setf(std::ios::fixed);
    stream.precision(4);
    stream << "Fitted " << fittedPoses.size() << " pose(s) on " << vertexCount
           << " vertices with " << jointCount << " joint(s), at most " << maxInfluences
           << " each. RMS " << result.rms << ", worst " << result.worst << ".";
    if (result.holdoutRms >= 0.0) {
        stream << "  Held out " << holdoutPoses.size() << " pose(s): RMS "
               << result.holdoutRms << ", worst " << result.holdoutWorst << ".";
    }
    if (result.cancelled) {
        stream << "  Stopped early on request, after " << result.iterationsDone
               << " iteration(s) - the weights are complete as of that iteration.";
    }
    if (!result.degenerateJoints.empty()) {
        stream << "  " << result.degenerateJoints.size()
               << " joint(s) could not be fitted for want of vertices spanning three "
                  "dimensions; their transforms were left alone.";
    }
    result.message = stream.str();
    return true;
}

}  // namespace mca
