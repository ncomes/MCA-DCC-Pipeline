// MCA-DCC Pipeline - pose skinner stress harness.
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// The access violation this exists to catch is INTERMITTENT and only appears at
// face scale: a hundred-odd poses, thousands of vertices, dozens of joints, and
// enough threads to lose a race. `test_solver.cpp` is the correctness suite and
// its cases are deliberately small, so it has never touched this.
//
// The whole reason the solver core is Maya-free is so a fault in it can be chased
// here rather than inside a DCC. Built with the DEBUG CRT and
// _ITERATOR_DEBUG_LEVEL=2, every container access is bounds-checked, so a bad
// index stops the program AT THE LINE instead of corrupting a heap and faulting
// somewhere unrelated minutes later. Built at /O2 with the release CRT it is the
// same code artists run, hammered.
//
//     stress_solver.exe [repeats] [threads] [vertices] [poses] [joints]
//
// **The defaults are deliberately small, and the checked build is deliberately
// single-threaded.** An earlier version of this file defaulted to face scale on
// every core in the debug CRT; run beside a compile and an open Maya it took a
// whole workstation down. Bounds checking does not need scale to work - it needs
// the code paths, which the problem below reaches at any size. Face scale is for
// the release build, and it is opt-in:
//
//     stress_solver.exe 6 8 5400 173 81
//
// The problem it builds is not a real face, but it is shaped like the paths the
// real one takes through the solver, and specifically the ones the crash stack
// named - the weight-solve region and solveNonNegative underneath it:
//
//   * near-duplicate joints, so the NNLS free set is rank-deficient and the
//     complete-orthogonal fallback runs,
//   * joints that move identically, so the "numerically stuck" escape and the
//     `abandoned` list run,
//   * more candidates than maxInfluences, so the prune loop runs to the end,
//   * a mesh with a SEPARATE SHELL no joint can reach across the surface, so
//     geodesic locality produces vertices with the fewest candidates it ever
//     produces,
//   * a couple of vertices whose poses are exactly their rest position, and a
//     couple that are wild, so the degenerate branches run.

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstdio>
#include <string>
#include <vector>

// Heap integrity checking, in the checked build only.
//
// The fault this harness is hunting is a VICTIM, not a culprit: a minidump of the
// real crash put it inside std::vector's copy constructor, reading a member through
// a null pointer, in code that cannot do that - and two different crashes gave two
// different addresses AND two different directions (a write to 0x0, a read of 0x30).
// That is the signature of a heap already corrupted by something earlier, tripping
// over the damage on the next big allocation. It also explains why it only ever
// happened deep into a long session and why fixing things at the fault site never
// helped.
//
// _CrtCheckMemory walks the debug heap and reports damage at the point of the call,
// so a check between solves narrows the culprit to one solve instead of one session.
#if defined(_MSC_VER) && defined(_DEBUG)
#include <crtdbg.h>
#define MCA_HEAP_OK() _CrtCheckMemory()
#else
#define MCA_HEAP_OK() 1
#endif

#include "mca_pose_skin.h"

namespace {

/// Vertices per ring of the tube. run() works out where the separate shell starts
/// from this and build() lays the mesh out with it, so there is exactly one of it.
constexpr int kRing = 12;

double angle(int seed) {
    // Deterministic, and no <random>: two runs must pose the same problem.
    return std::sin(seed * 12.9898) * 43758.5453 - std::floor(std::sin(seed * 12.9898) * 43758.5453);
}

mca::Mat4 rotationY(double radians, double x, double y, double z) {
    mca::Mat4 out;
    const double c = std::cos(radians);
    const double s = std::sin(radians);
    out.m[0][0] = c;   out.m[0][2] = -s;
    out.m[2][0] = s;   out.m[2][2] = c;
    out.m[3][0] = x;   out.m[3][1] = y;   out.m[3][2] = z;
    return out;
}

struct Problem {
    mca::PoseSkinInput input;
    int jointCount = 0;
};

Problem build(int vertices, int poses, int joints, int shellStart) {
    Problem problem;
    problem.jointCount = joints;

    // A long cylinder of vertices, plus a separate shell past shellStart that
    // shares no edge with it.
    const int ring = kRing;
    for (int vertex = 0; vertex < vertices; ++vertex) {
        const double along = static_cast<double>(vertex / ring);
        const double around = 2.0 * 3.14159265358979 * (vertex % ring) / ring;
        const double offset = vertex >= shellStart ? 50.0 : 0.0;
        problem.input.rest.push_back(mca::Vec3(std::cos(around) + offset,
                                               std::sin(around),
                                               along * 0.1));
    }

    problem.input.neighbours.assign(static_cast<std::size_t>(vertices), std::vector<int>());
    for (int vertex = 0; vertex < vertices; ++vertex) {
        const bool inShell = vertex >= shellStart;
        for (int step : {-ring, -1, 1, ring}) {
            const int other = vertex + step;
            if (other < 0 || other >= vertices) {
                continue;
            }
            // The shell is a separate piece: no edge crosses the boundary.
            if ((other >= shellStart) != inShell) {
                continue;
            }
            problem.input.neighbours[static_cast<std::size_t>(vertex)].push_back(other);
        }
    }

    for (int joint = 0; joint < joints; ++joint) {
        const double z = 0.1 * (static_cast<double>(vertices) / ring) * joint / joints;
        // Every third joint is a near-duplicate of the one before it, which is
        // what makes the free set rank deficient.
        const double nudge = (joint % 3 == 0) ? 0.0 : 1e-7;
        mca::Mat4 rest = rotationY(0.0, 0.0, 0.0, z + nudge);
        problem.input.bindInverse.push_back(mca::inverse(rest));
    }

    for (int pose = 0; pose < poses; ++pose) {
        std::vector<mca::Mat4> world;
        for (int joint = 0; joint < joints; ++joint) {
            const double z = 0.1 * (static_cast<double>(vertices) / ring) * joint / joints;
            // Joints in the same third of the skeleton move IDENTICALLY on some
            // poses, which is the input with no unique answer.
            const double turn = (joint / 3) * 0.02 * angle(pose * 31 + joint / 3);
            world.push_back(rotationY(turn, 0.0, 0.0, z));
        }
        problem.input.jointWorld.push_back(world);

        std::vector<mca::Vec3> posed;
        for (int vertex = 0; vertex < vertices; ++vertex) {
            const int joint = std::min(joints - 1, vertex / std::max(1, vertices / joints));
            mca::Mat4 skin = mca::multiply(problem.input.bindInverse[static_cast<std::size_t>(joint)],
                                          world[static_cast<std::size_t>(joint)]);
            mca::Vec3 point = mca::transformPoint(problem.input.rest[static_cast<std::size_t>(vertex)],
                                                 skin);
            if (vertex % 977 == 0) {
                // A vertex that does not move at all.
                point = problem.input.rest[static_cast<std::size_t>(vertex)];
            } else if (vertex % 1013 == 0) {
                // And one that moves absurdly, so nothing can fit it.
                point.y += 40.0;
            }
            posed.push_back(point);
        }
        problem.input.poses.push_back(posed);
    }
    return problem;
}

int run(int repeats, int threads, int vertices, int poses, int joints) {
    const int ring = kRing;
    // The last two rings are a separate piece of geometry that shares no edge with
    // the rest, so geodesic locality leaves them with the fewest candidates it ever
    // produces. That is a code path, not a size, which is why this stays honest at
    // 900 vertices as well as at 5400.
    const int shellStart = std::max(ring, (vertices / ring - 2) * ring);

    Problem problem = build(vertices, poses, joints, shellStart);

    std::printf("stress: %d vertices, %d poses, %d joints, %d in a separate shell, "
                "%d threads, %d repeats\n",
                vertices, poses, joints, vertices - shellStart, threads, repeats);

    if (!MCA_HEAP_OK()) {
        std::printf("stress: the heap was already damaged before any solve ran\n");
        return 1;
    }
    for (int repeat = 0; repeat < repeats; ++repeat) {
        for (int geodesic = 0; geodesic < 2; ++geodesic) {
            mca::PoseSkinOptions options;
            options.maxInfluences = 8;
            options.localityJoints = 32;
            options.geodesicLocality = geodesic != 0;
            options.prunePerStep = true;
            options.maxIterations = 2;
            options.solveBones = true;
            options.rigidBones = repeat % 2 == 0;
            options.threads = threads;
            options.smoothing = (repeat % 3 == 0) ? 0.1 : 0.0;
            options.smoothingRounds = 2;
            for (int pose = 7; pose < poses; pose += 8) {
                options.holdoutPoses.push_back(pose);
            }

            std::printf("  repeat %2d  %-9s rigid=%d smooth=%.2f  starting...\n",
                        repeat, geodesic ? "geodesic" : "euclid",
                        options.rigidBones ? 1 : 0, options.smoothing);
            mca::PoseSkinResult result;
            std::string error;
            const auto started = std::chrono::steady_clock::now();
            const bool ok = mca::solvePoseSkin(problem.input, options, result, error);
            const double seconds = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - started).count();
            std::printf("  repeat %2d  %-9s rigid=%d smooth=%.2f  %5.1fs  %s  rms %.6f  "
                        "unweighted %d  degenerate %d\n",
                        repeat, geodesic ? "geodesic" : "euclid",
                        options.rigidBones ? 1 : 0, options.smoothing, seconds,
                        ok ? "ok  " : "FAIL", result.rms,
                        static_cast<int>(result.unweightedVertices.size()),
                        static_cast<int>(result.degenerateJoints.size()));
            if (!MCA_HEAP_OK()) {
                std::printf("  HEAP CORRUPTED by this solve (repeat %d, %s)\n",
                            repeat, geodesic ? "geodesic" : "euclid");
                return 1;
            }
            std::fflush(stdout);
            if (!ok) {
                std::printf("  FAILED: %s\n", error.c_str());
                return 1;
            }
            // A result that is structurally wrong is a bug even when nothing
            // faults, so it is checked here rather than assumed.
            if (result.vertexJoints.size() != static_cast<std::size_t>(vertices)) {
                std::printf("  WRONG SHAPE: %d weight rows for %d vertices\n",
                            static_cast<int>(result.vertexJoints.size()), vertices);
                return 1;
            }
            for (int vertex = 0; vertex < vertices; ++vertex) {
                const std::vector<int>& js = result.vertexJoints[static_cast<std::size_t>(vertex)];
                const std::vector<double>& ws =
                    result.vertexWeights[static_cast<std::size_t>(vertex)];
                if (js.empty() || js.size() != ws.size() ||
                    js.size() > static_cast<std::size_t>(options.maxInfluences)) {
                    std::printf("  WRONG SHAPE at vertex %d: %d joints, %d weights\n",
                                vertex, static_cast<int>(js.size()), static_cast<int>(ws.size()));
                    return 1;
                }
                double total = 0.0;
                for (std::size_t slot = 0; slot < js.size(); ++slot) {
                    if (js[slot] < 0 || js[slot] >= joints) {
                        std::printf("  JOINT OUT OF RANGE at vertex %d: %d\n", vertex, js[slot]);
                        return 1;
                    }
                    if (!(ws[slot] == ws[slot])) {
                        std::printf("  NaN WEIGHT at vertex %d\n", vertex);
                        return 1;
                    }
                    total += ws[slot];
                }
                if (std::fabs(total - 1.0) > 1e-9) {
                    std::printf("  WEIGHTS DO NOT SUM TO ONE at vertex %d: %.12f\n", vertex, total);
                    return 1;
                }
            }
        }
    }
    std::printf("stress: no fault, no bad result\n");
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    // Unbuffered, because the whole point is to survive a crash. A block-buffered
    // stdout redirected to a file loses everything printed since the last flush,
    // and the first run of this harness to fault left a ZERO BYTE log - which reads
    // exactly like "it died before it started" and is nothing of the kind.
    std::setvbuf(stdout, NULL, _IONBF, 0);

#if defined(_MSC_VER) && defined(_DEBUG)
    // Asserts and CRT errors go to stderr, never to a dialog box. A bounds check
    // that pops a modal window on somebody's desktop and waits is worse than no
    // bounds check: the harness looks hung, and on a machine running other work it
    // is one more thing to hunt down and close.
    _CrtSetReportMode(_CRT_ERROR, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_ERROR, _CRTDBG_FILE_STDERR);
    _CrtSetReportMode(_CRT_ASSERT, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_ASSERT, _CRTDBG_FILE_STDERR);
    _CrtSetReportMode(_CRT_WARN, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_WARN, _CRTDBG_FILE_STDERR);
    _set_abort_behavior(0, _WRITE_ABORT_MSG | _CALL_REPORTFAULT);
#endif

    const int repeats = argc > 1 ? std::atoi(argv[1]) : 4;
    // One thread by default, not "all of them". A harness whose default setting can
    // wedge the machine it runs on is a harness people stop running.
    const int threads = argc > 2 ? std::atoi(argv[2]) : 1;
    const int vertices = argc > 3 ? std::atoi(argv[3]) : 900;
    const int poses = argc > 4 ? std::atoi(argv[4]) : 40;
    const int joints = argc > 5 ? std::atoi(argv[5]) : 21;
    if (vertices < 24 || poses < 2 || joints < 2) {
        std::printf("stress: need at least 24 vertices, 2 poses and 2 joints\n");
        return 2;
    }
    return run(repeats, threads, vertices, poses, joints);
}
