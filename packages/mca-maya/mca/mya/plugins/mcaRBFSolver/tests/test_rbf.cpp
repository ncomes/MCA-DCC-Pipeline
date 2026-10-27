// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// Off-DCC tests for the RBF maths. No Maya, no licence, no viewport.
//
// The checks that matter most are the three the tool this replaces got wrong: a
// 3D key, a single pose, and two poses sharing a key. Each is marked below.

#include "mca_rbf.h"

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

bool near(double a, double b, double tolerance = 1e-9) {
    return std::fabs(a - b) <= tolerance;
}

std::string number(double value) {
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.12g", value);
    return std::string(buffer);
}

}  // namespace

int main() {
    // --- distance ------------------------------------------------------------ //
    {
        const std::vector<double> origin{0.0, 0.0, 0.0};
        const std::vector<double> point{1.0, 2.0, 2.0};

        // THE BUG. A 3-4-5 style triangle: the straight-line distance from the
        // origin to (1, 2, 2) is exactly 3. The original summed |d|^3 and took a
        // cube root, giving 2.5713, and called it Euclidean.
        check("Euclidean distance on a 3D key is the straight line",
              near(mca::distance(mca::Distance::Euclidean, origin, point), 3.0),
              number(mca::distance(mca::Distance::Euclidean, origin, point)));

        const double pnorm = mca::distance(mca::Distance::PNorm, origin, point);
        check("the p-norm is kept, and is NOT the same thing on a 3D key",
              !near(pnorm, 3.0) && near(pnorm, std::pow(1.0 + 8.0 + 8.0, 1.0 / 3.0)),
              number(pnorm));

        // ...and agrees with Euclidean on a 2D key, which is why the bug hid.
        const std::vector<double> flatOrigin{0.0, 0.0};
        const std::vector<double> flatPoint{3.0, 4.0};
        check("the two agree on a 2D key, which is why nobody noticed",
              near(mca::distance(mca::Distance::Euclidean, flatOrigin, flatPoint), 5.0) &&
                  near(mca::distance(mca::Distance::PNorm, flatOrigin, flatPoint), 5.0));

        const std::vector<double> right{1.0, 0.0, 0.0};
        const std::vector<double> up{0.0, 1.0, 0.0};
        check("a right angle measures pi/2",
              near(mca::distance(mca::Distance::Angular, right, up), 3.14159265358979 / 2.0,
                   1e-9));

        // The original required callers to normalise and never checked.
        const std::vector<double> longUp{0.0, 7.0, 0.0};
        check("angular distance normalises for you",
              near(mca::distance(mca::Distance::Angular, right, longUp),
                   mca::distance(mca::Distance::Angular, right, up)));
        const std::vector<double> zero{0.0, 0.0, 0.0};
        check("and a zero-length key does not produce a NaN",
              mca::distance(mca::Distance::Angular, right, zero) == 0.0);
    }

    // --- kernels -------------------------------------------------------------- //
    {
        check("gaussian is 1 at zero", near(mca::kernel(mca::Kernel::Gaussian, 0.0), 1.0));
        check("gaussian falls off", mca::kernel(mca::Kernel::Gaussian, 2.0) <
                                        mca::kernel(mca::Kernel::Gaussian, 1.0));
        check("linear is the distance", near(mca::kernel(mca::Kernel::Linear, 2.5), 2.5));
        // The original returned d*d*d + 1.
        check("cubic is d cubed, with no constant bolted on",
              near(mca::kernel(mca::Kernel::Cubic, 2.0), 8.0),
              number(mca::kernel(mca::Kernel::Cubic, 2.0)));
        check("thin plate survives zero rather than taking log(0)",
              std::isfinite(mca::kernel(mca::Kernel::ThinPlate, 0.0)));
        check("inverse multiquadric is 1 at zero",
              near(mca::kernel(mca::Kernel::InverseMultiquadric, 0.0), 1.0));
    }

    // --- interpolation passes through its poses -------------------------------- //
    {
        const std::vector<std::vector<double>> keys{{0.0}, {1.0}, {2.0}};
        const std::vector<std::vector<double>> values{{0.0}, {10.0}, {0.0}};
        mca::RbfSetup setup;
        setup.kernel = mca::Kernel::Gaussian;
        std::string error;
        mca::RbfSolver solver;
        check("a three-pose system builds", solver.build(keys, values, setup, error), error);
        check("and is not reported degenerate", !solver.degenerate());

        std::vector<double> out;
        for (std::size_t i = 0u; i < keys.size(); ++i) {
            solver.evaluate(keys[i], out);
            check("it passes exactly through each pose", near(out[0], values[i][0], 1e-7),
                  number(out[0]) + " at pose " + std::to_string(i));
        }

        solver.evaluate({0.5}, out);
        check("and interpolates between them rather than jumping",
              out[0] > 0.0 && out[0] < 10.0, number(out[0]));
    }

    // --- N-dimensional key, M-dimensional value --------------------------------- //
    {
        // The use it was built for: an aim vector in, a set of weights out.
        const std::vector<std::vector<double>> keys{
            {1.0, 0.0, 0.0}, {0.0, 1.0, 0.0}, {0.0, 0.0, 1.0}};
        const std::vector<std::vector<double>> values{
            {1.0, 0.0}, {0.0, 1.0}, {0.5, 0.5}};
        mca::RbfSetup setup;
        setup.distance = mca::Distance::Angular;
        std::string error;
        mca::RbfSolver solver;
        check("a 3D key driving a 2D value builds",
              solver.build(keys, values, setup, error), error);
        check("the dimensions are read back correctly",
              solver.keyDimension() == 3 && solver.valueDimension() == 2 &&
                  solver.poseCount() == 3);

        std::vector<double> out;
        for (std::size_t i = 0u; i < keys.size(); ++i) {
            solver.evaluate(keys[i], out);
            check("every value dimension passes through its pose",
                  near(out[0], values[i][0], 1e-7) && near(out[1], values[i][1], 1e-7),
                  number(out[0]) + ", " + number(out[1]));
        }
    }

    // --- ONE POSE. The original returned nothing at all here. -------------------- //
    {
        const std::vector<std::vector<double>> keys{{1.0, 2.0, 3.0}};
        const std::vector<std::vector<double>> values{{4.0, 5.0}};
        mca::RbfSetup setup;
        std::string error;
        mca::RbfSolver solver;
        check("a single pose builds instead of failing silently",
              solver.build(keys, values, setup, error), error);

        std::vector<double> out;
        solver.evaluate({1.0, 2.0, 3.0}, out);
        check("and returns that pose's value at the pose",
              near(out[0], 4.0, 1e-7) && near(out[1], 5.0, 1e-7),
              number(out[0]) + ", " + number(out[1]));
        solver.evaluate({50.0, -20.0, 7.0}, out);
        check("a single pose stays finite far away from itself",
              std::isfinite(out[0]) && std::isfinite(out[1]));
    }

    // --- TWO POSES ON THE SAME KEY. The original produced garbage. --------------- //
    {
        const std::vector<std::vector<double>> keys{{0.0}, {1.0}, {1.0}};
        const std::vector<std::vector<double>> values{{0.0}, {5.0}, {7.0}};
        mca::RbfSetup setup;
        std::string error;
        mca::RbfSolver solver;
        const bool built = solver.build(keys, values, setup, error);
        check("a duplicated key still builds rather than dividing by a zero pivot",
              built, error);
        check("and is reported as degenerate so the rigger can be told",
              built && solver.degenerate());

        std::vector<double> out;
        if (built) {
            solver.evaluate({1.0}, out);
            check("the answer is finite", std::isfinite(out[0]), number(out[0]));
            check("and lands between the two values it was given, not outside them",
                  out[0] >= 5.0 - 1e-6 && out[0] <= 7.0 + 1e-6, number(out[0]));
        }

        // Regularisation is the documented way out of it.
        setup.regularisation = 1e-3;
        mca::RbfSolver regularised;
        check("regularisation solves the same system without complaint",
              regularised.build(keys, values, setup, error), error);
    }

    // --- bad input is refused with a sentence ------------------------------------ //
    {
        mca::RbfSetup setup;
        std::string error;
        mca::RbfSolver solver;

        check("no poses is refused", !solver.build({}, {}, setup, error));
        check("and says so", error.find("No poses") != std::string::npos, error);

        check("mismatched key and value counts are refused",
              !solver.build({{0.0}, {1.0}}, {{0.0}}, setup, error));
        check("ragged keys are refused",
              !solver.build({{0.0}, {1.0, 2.0}}, {{0.0}, {1.0}}, setup, error));
        check("and the message names the offending pose",
              error.find("Pose 1") != std::string::npos, error);

        check("evaluating a solver that was never built returns false",
              !mca::RbfSolver().evaluate({0.0}, *(new std::vector<double>())));

        mca::RbfSolver good;
        good.build({{0.0}, {1.0}}, {{0.0}, {1.0}}, setup, error);
        std::vector<double> out;
        check("an input of the wrong size is refused rather than read off the end",
              !good.evaluate({0.0, 0.0}, out));
    }

    // --- normalisation makes scale mean one thing -------------------------------- //
    {
        // The same poses, a thousand times bigger. With normalisation on, the
        // shape of the interpolation should not care what units the keys are in.
        mca::RbfSetup setup;
        setup.normalise = true;
        std::string error;

        mca::RbfSolver small;
        mca::RbfSolver large;
        small.build({{0.0}, {1.0}, {2.0}}, {{0.0}, {10.0}, {0.0}}, setup, error);
        large.build({{0.0}, {1000.0}, {2000.0}}, {{0.0}, {10.0}, {0.0}}, setup, error);

        std::vector<double> a;
        std::vector<double> b;
        small.evaluate({0.5}, a);
        large.evaluate({500.0}, b);
        check("normalised, the same shape gives the same answer whatever the units",
              near(a[0], b[0], 1e-6), number(a[0]) + " vs " + number(b[0]));
        check("and the applied scale reflects the normalisation",
              !near(small.appliedScale(), large.appliedScale()));
    }

    std::printf("\n%d/%d checks passed.\n", gChecks - gFailures, gChecks);
    return gFailures == 0 ? 0 : 1;
}
