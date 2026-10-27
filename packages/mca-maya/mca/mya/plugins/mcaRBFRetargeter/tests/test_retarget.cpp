// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// Off-DCC tests for the retarget maths. No Maya, no licence, no viewport.
//
// The interesting checks are the ones that state a property the transfer must
// have rather than a number it happens to produce: if the target IS the source,
// a shape must come back unchanged; if the target is the source moved, a shape
// must move by exactly that much. Those hold regardless of mesh, point count or
// kernel, which is what makes them worth asserting.

#include "mca_retarget.h"

#include <cmath>
#include <cstdio>
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

/// A lumpy blob, so the points are not on any convenient plane.
std::vector<mca::Vec3> blob(int count) {
    std::vector<mca::Vec3> points;
    points.reserve(static_cast<std::size_t>(count));
    for (int i = 0; i < count; ++i) {
        const double t = static_cast<double>(i);
        points.push_back(mca::Vec3(std::sin(t * 1.7) * 3.0 + std::cos(t * 0.3),
                                   std::cos(t * 1.1) * 2.0 + std::sin(t * 0.7),
                                   std::sin(t * 0.9) * 2.5));
    }
    return points;
}

std::vector<int> everyNth(int count, int step) {
    std::vector<int> ids;
    for (int i = 0; i < count; i += step) {
        ids.push_back(i);
    }
    return ids;
}

double worstDistance(const std::vector<mca::Vec3>& a, const std::vector<mca::Vec3>& b) {
    double worst = 0.0;
    for (std::size_t i = 0u; i < a.size() && i < b.size(); ++i) {
        const double dx = a[i].x - b[i].x;
        const double dy = a[i].y - b[i].y;
        const double dz = a[i].z - b[i].z;
        worst = std::max(worst, std::sqrt(dx * dx + dy * dy + dz * dz));
    }
    return worst;
}

}  // namespace

int main() {
    const int kPoints = 200;
    const std::vector<mca::Vec3> source = blob(kPoints);
    const std::vector<int> ids = everyNth(kPoints, 4);   // 50 solver points

    // --- the sphere anchors --------------------------------------------------- //
    {
        const std::vector<mca::Vec3> sphere =
            mca::pointsOnSphere(64, mca::Vec3(1.0, 2.0, 3.0), mca::Vec3(5.0, 5.0, 5.0));
        check("it makes the number of anchors asked for", sphere.size() == 64u);

        double worst = 0.0;
        for (const mca::Vec3& point : sphere) {
            const double dx = point.x - 1.0;
            const double dy = point.y - 2.0;
            const double dz = point.z - 3.0;
            worst = std::max(worst, std::fabs(std::sqrt(dx * dx + dy * dy + dz * dz) - 5.0));
        }
        check("and they all sit on the sphere", worst < 1e-9, number(worst));

        check("zero anchors is not an error", mca::pointsOnSphere(0, mca::Vec3(),
                                                                 mca::Vec3()).empty());
    }

    // --- identity: the target IS the source ------------------------------------ //
    {
        mca::RetargetOptions options;
        std::string error;
        mca::RetargetSolver solver;
        check("an identity transfer builds", solver.build(source, source, ids, options,
                                                          error), error);
        check("and is not degenerate", !solver.report().degenerate);
        std::vector<mca::Vec3> shape = blob(kPoints);
        const std::vector<mca::Vec3> original = shape;
        solver.evaluate(shape);
        check("a shape comes back unchanged", worstDistance(shape, original) < 1e-6,
              number(worstDistance(shape, original)));
    }

    // --- a pure translation. THE affine case. ---------------------------------- //
    //
    // If the target is the source moved, every shape must move by exactly that
    // much - anywhere, not just at the solver points. A linear RBF cannot do
    // that on its own; the polynomial block is what makes it exact. This is the
    // check that decides whether affineTerm earns being on by default.
    {
        const mca::Vec3 offset(7.0, -3.0, 2.5);
        std::vector<mca::Vec3> moved;
        for (const mca::Vec3& point : source) {
            moved.push_back(mca::Vec3(point.x + offset.x, point.y + offset.y,
                                      point.z + offset.z));
        }

        std::vector<mca::Vec3> wanted;
        const std::vector<mca::Vec3> shape = blob(kPoints);
        for (const mca::Vec3& point : shape) {
            wanted.push_back(mca::Vec3(point.x + offset.x, point.y + offset.y,
                                       point.z + offset.z));
        }

        std::string error;

        mca::RetargetOptions withAffine;
        mca::RetargetSolver good;
        good.build(source, moved, ids, withAffine, error);
        std::vector<mca::Vec3> withTerm = shape;
        good.evaluate(withTerm);
        const double exact = worstDistance(withTerm, wanted);

        mca::RetargetOptions withoutAffine;
        withoutAffine.affineTerm = false;
        mca::RetargetSolver plain;
        plain.build(source, moved, ids, withoutAffine, error);
        std::vector<mca::Vec3> withoutTerm = shape;
        plain.evaluate(withoutTerm);
        const double drift = worstDistance(withoutTerm, wanted);

        std::printf("  translation error: with affine term %s, without %s\n",
                    number(exact).c_str(), number(drift).c_str());

        check("with the affine term, a plain move is reproduced exactly",
              exact < 1e-6, number(exact));
        check("without it, the same move drifts - which is why it is on by default",
              drift > exact * 10.0,
              "with " + number(exact) + ", without " + number(drift));
    }

    // --- a uniform scale ------------------------------------------------------- //
    {
        std::vector<mca::Vec3> scaled;
        for (const mca::Vec3& point : source) {
            scaled.push_back(mca::Vec3(point.x * 2.0, point.y * 2.0, point.z * 2.0));
        }
        std::vector<mca::Vec3> wanted;
        const std::vector<mca::Vec3> shape = blob(kPoints);
        for (const mca::Vec3& point : shape) {
            wanted.push_back(mca::Vec3(point.x * 2.0, point.y * 2.0, point.z * 2.0));
        }

        mca::RetargetOptions options;
        std::string error;
        mca::RetargetSolver solver;
        solver.build(source, scaled, ids, options, error);
        std::vector<mca::Vec3> result = shape;
        solver.evaluate(result);
        check("a uniform scale is reproduced exactly too",
              worstDistance(result, wanted) < 1e-6,
              number(worstDistance(result, wanted)));
    }

    // --- it passes through its solver points ------------------------------------ //
    {
        std::vector<mca::Vec3> target = blob(kPoints);
        for (mca::Vec3& point : target) {
            point.x += std::sin(point.y) * 0.5;   // something non-affine
            point.y *= 1.2;
        }

        mca::RetargetOptions options;
        std::string error;
        mca::RetargetSolver solver;
        check("a non-affine transfer builds", solver.build(source, target, ids, options,
                                                           error), error);

        std::vector<mca::Vec3> probe;
        std::vector<mca::Vec3> wanted;
        for (int id : ids) {
            probe.push_back(source[static_cast<std::size_t>(id)]);
            wanted.push_back(target[static_cast<std::size_t>(id)]);
        }
        solver.evaluate(probe);
        check("and lands exactly on every solver point",
              worstDistance(probe, wanted) < 1e-6,
              number(worstDistance(probe, wanted)));
    }

    // --- the guard --------------------------------------------------------------- //
    {
        mca::RetargetOptions options;
        options.maxSolverPoints = 20;
        std::string error;
        mca::RetargetSolver solver;
        check("solving on more points than allowed is refused",
              !solver.build(source, source, ids, options, error));
        check("and the message says how many and how much memory",
              error.find("50 points") != std::string::npos &&
                  error.find("MB") != std::string::npos, error);
        check("and suggests what to do about it",
              error.find("fewer solver vertices") != std::string::npos, error);

        options.maxSolverPoints = 0;
        mca::RetargetSolver unguarded;
        check("setting the guard to zero removes it",
              unguarded.build(source, source, ids, options, error), error);
    }

    // --- bad input --------------------------------------------------------------- //
    {
        mca::RetargetOptions options;
        std::string error;
        mca::RetargetSolver solver;

        check("no source is refused", !solver.build({}, {}, ids, options, error));

        std::vector<mca::Vec3> shorter(source.begin(), source.begin() + 10);
        check("mismatched vertex counts are refused",
              !solver.build(source, shorter, {}, options, error));
        check("and the message says both counts and why it matters",
              error.find("200") != std::string::npos &&
                  error.find("topology") != std::string::npos, error);

        check("a solver id off the end of the mesh is refused",
              !solver.build(source, source, {0, 5, 99999}, options, error));

        check("evaluating a solver that was never built returns false",
              !mca::RetargetSolver().evaluate(*(new std::vector<mca::Vec3>())));
    }

    // --- duplicate solver points --------------------------------------------------- //
    {
        // Two ids pointing at the same vertex: the matrix cannot tell them apart.
        std::vector<int> duplicated = ids;
        duplicated.push_back(ids.front());

        mca::RetargetOptions options;
        std::string error;
        mca::RetargetSolver solver;
        const bool built = solver.build(source, source, duplicated, options, error);
        check("a duplicated solver point still builds rather than dividing by a zero "
              "pivot", built, error);
        check("and is reported as degenerate", built && solver.report().degenerate);

        options.regularisation = 1e-6;
        mca::RetargetSolver regularised;
        check("regularisation solves the same set without complaint",
              regularised.build(source, source, duplicated, options, error), error);
    }

    // --- sphere anchors do not break an identity transfer ---------------------------- //
    {
        mca::RetargetOptions options;
        options.sphereSamples = 32;
        std::string error;
        mca::RetargetSolver solver;
        check("anchors build", solver.build(source, source, ids, options, error), error);
        check("and are counted in the report", solver.report().solverPoints == 50 + 32,
              std::to_string(solver.report().solverPoints));

        std::vector<mca::Vec3> shape = blob(kPoints);
        const std::vector<mca::Vec3> original = shape;
        solver.evaluate(shape);
        check("an identity transfer is still identity with anchors on",
              worstDistance(shape, original) < 1e-5,
              number(worstDistance(shape, original)));
    }

    // --- repeatable ------------------------------------------------------------------ //
    {
        std::vector<mca::Vec3> target = blob(kPoints);
        for (mca::Vec3& point : target) {
            point.z += std::cos(point.x) * 0.4;
        }
        mca::RetargetOptions options;
        std::string error;

        mca::RetargetSolver first;
        mca::RetargetSolver second;
        first.build(source, target, ids, options, error);
        second.build(source, target, ids, options, error);

        std::vector<mca::Vec3> a = blob(kPoints);
        std::vector<mca::Vec3> b = a;
        first.evaluate(a);
        second.evaluate(b);
        check("two identical solves give identical answers",
              worstDistance(a, b) == 0.0, number(worstDistance(a, b)));
    }

    std::printf("\n%d/%d checks passed.\n", gChecks - gFailures, gChecks);
    return gFailures == 0 ? 0 : 1;
}
