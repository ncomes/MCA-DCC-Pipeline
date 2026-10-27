// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// Off-DCC tests for the cage maths. No Maya, no licence, no viewport.
//
// Build and run with tests/run_tests.bat, or by hand:
//     cl /EHsc /std:c++17 /I..\include /I..\..\common\include test_cage.cpp ..\source\mca_cage_wrap.cpp
//
// Every accuracy number in the docs comes from here. The properties being checked
// are the ones a cage deformer has to have for a rigger to trust it:
//
//   * with the cage at rest, the mesh is exactly where it was modelled,
//   * move the cage rigidly and the mesh moves rigidly,
//   * scale the cage and the mesh scales,
//   * twist the cage and the mesh twists WITHOUT shearing - which is the whole
//     reason to carry the face normals, and is measured against not carrying them,
//   * and nothing produces a NaN, however degenerate the arrangement.

#include "mca_cage_wrap.h"

#include <cmath>
#include <cstdio>
#include <ctime>
#include <string>
#include <vector>

using mca::cage::ApplyOptions;
using mca::cage::Bind;
using mca::cage::BindOptions;
using mca::cage::Cage;
using mca::cage::Triangle;
using mca::cage::Vec3;

namespace {

int gChecks = 0;
int gFailures = 0;

void check(const std::string& label, bool condition, const std::string& detail = "") {
    ++gChecks;
    if (!condition) {
        ++gFailures;
        std::printf("FAIL  %s%s%s\n", label.c_str(), detail.empty() ? "" : "  |  ",
                    detail.c_str());
    }
}

void checkClose(const std::string& label, double got, double want, double tolerance) {
    const bool ok = std::fabs(got - want) <= tolerance;
    check(label, ok, ok ? "" : ("got " + std::to_string(got) + ", want " + std::to_string(want)));
}

std::string number(double value) {
    char text[64];
    std::snprintf(text, sizeof(text), "%.3e", value);
    return std::string(text);
}

/// An axis-aligned box cage, triangulated, wound outward.
Cage boxCage(double half) {
    Cage cage;
    cage.points = {
        Vec3(-half, -half, -half), Vec3(half, -half, -half), Vec3(half, half, -half),
        Vec3(-half, half, -half),  Vec3(-half, -half, half), Vec3(half, -half, half),
        Vec3(half, half, half),    Vec3(-half, half, half),
    };
    cage.triangles = {
        Triangle(0, 2, 1), Triangle(0, 3, 2),  // -Z
        Triangle(4, 5, 6), Triangle(4, 6, 7),  // +Z
        Triangle(0, 1, 5), Triangle(0, 5, 4),  // -Y
        Triangle(3, 7, 6), Triangle(3, 6, 2),  // +Y
        Triangle(0, 4, 7), Triangle(0, 7, 3),  // -X
        Triangle(1, 2, 6), Triangle(1, 6, 5),  // +X
    };
    return cage;
}

/// A grid of points well inside a box of the given half-size.
std::vector<Vec3> insidePoints(double half, int perSide) {
    std::vector<Vec3> points;
    const double reach = half * 0.6;
    for (int ii = 0; ii < perSide; ++ii) {
        for (int jj = 0; jj < perSide; ++jj) {
            for (int kk = 0; kk < perSide; ++kk) {
                const double t = perSide > 1 ? 1.0 / (perSide - 1) : 0.0;
                points.push_back(Vec3(-reach + 2.0 * reach * ii * t,
                                      -reach + 2.0 * reach * jj * t,
                                      -reach + 2.0 * reach * kk * t));
            }
        }
    }
    return points;
}

Cage moved(const Cage& cage, const Vec3& by) {
    Cage out = cage;
    for (size_t index = 0; index < out.points.size(); ++index) {
        out.points[index] = out.points[index] + by;
    }
    return out;
}

Cage scaled(const Cage& cage, double by) {
    Cage out = cage;
    for (size_t index = 0; index < out.points.size(); ++index) {
        out.points[index] = out.points[index] * by;
    }
    return out;
}

Vec3 turnedAboutY(const Vec3& point, double radians) {
    const double c = std::cos(radians);
    const double s = std::sin(radians);
    return Vec3(point.x * c + point.z * s, point.y, -point.x * s + point.z * c);
}

Cage turned(const Cage& cage, double radians) {
    Cage out = cage;
    for (size_t index = 0; index < out.points.size(); ++index) {
        out.points[index] = turnedAboutY(out.points[index], radians);
    }
    return out;
}

/// Twisted about Y: the rotation grows with height, which is the deformation that
/// shears a cage built out of positions alone.
Cage twisted(const Cage& cage, double radiansPerUnit) {
    Cage out = cage;
    for (size_t index = 0; index < out.points.size(); ++index) {
        const Vec3& point = out.points[index];
        out.points[index] = turnedAboutY(point, radiansPerUnit * point.y);
    }
    return out;
}

/// Sheared sideways, growing with height: a cage deformation that HAS a conformal
/// answer, so a method that finds it comes out with no skew at all.
Cage sheared(const Cage& cage, double amount) {
    Cage out = cage;
    for (size_t index = 0; index < out.points.size(); ++index) {
        const Vec3& point = out.points[index];
        out.points[index] = Vec3(point.x + amount * point.y * point.y, point.y, point.z);
    }
    return out;
}

double worstDistance(const std::vector<Vec3>& got, const std::vector<Vec3>& want) {
    double worst = 0.0;
    for (size_t index = 0; index < got.size() && index < want.size(); ++index) {
        worst = std::max(worst, (got[index] - want[index]).length());
    }
    return worst;
}

bool allFinite(const std::vector<Vec3>& points) {
    for (size_t index = 0; index < points.size(); ++index) {
        const Vec3& point = points[index];
        if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z)) {
            return false;
        }
    }
    return true;
}

// --- the checks ------------------------------------------------------------- //

void testCageChecks() {
    std::string problem;
    check("a closed box cage is accepted", mca::cage::checkCage(boxCage(1.0), &problem), problem);

    Cage holed = boxCage(1.0);
    holed.triangles.pop_back();
    check("a hole is refused", !mca::cage::checkCage(holed, &problem));
    check("and the refusal says hole", problem.find("hole") != std::string::npos, problem);

    Cage flipped = boxCage(1.0);
    std::swap(flipped.triangles[0].b, flipped.triangles[0].c);
    check("a face wound the wrong way is refused", !mca::cage::checkCage(flipped, &problem));
    check("and the refusal says which way round",
          problem.find("wound") != std::string::npos, problem);

    Cage degenerate = boxCage(1.0);
    degenerate.points[1] = degenerate.points[0];
    check("a triangle with no area is refused", !mca::cage::checkCage(degenerate, &problem));

    Cage outOfRange = boxCage(1.0);
    outOfRange.triangles[0].a = 99;
    check("a triangle pointing at a point that does not exist is refused",
          !mca::cage::checkCage(outOfRange, &problem));

    Cage tiny;
    tiny.points = {Vec3(), Vec3(1.0, 0.0, 0.0)};
    check("two points cannot be a cage", !mca::cage::checkCage(tiny, &problem));

    // Consistently wound is not the same as wound OUTWARD. An inside-out cage passes
    // every other check and then behaves as though everything in the world were inside
    // it - every point falls to the fallback, the deformation is poor, and without this
    // nothing says why. Found by a test cage of mine that was wound the wrong way.
    Cage insideOut = boxCage(1.0);
    for (size_t index = 0; index < insideOut.triangles.size(); ++index) {
        std::swap(insideOut.triangles[index].b, insideOut.triangles[index].c);
    }
    check("the signed volume of a good cage is positive",
          mca::cage::signedVolume(boxCage(1.0)) > 0.0);
    check("an inside-out cage is refused", !mca::cage::checkCage(insideOut, &problem));
    check("and the refusal says inside out",
          problem.find("inside out") != std::string::npos, problem);
}

void testWinding() {
    const Cage cage = boxCage(1.0);
    checkClose("the winding number is 1 at the centre", mca::cage::windingNumber(cage, Vec3()),
               1.0, 1e-9);
    checkClose("and 1 near a corner, inside",
               mca::cage::windingNumber(cage, Vec3(0.9, 0.9, 0.9)), 1.0, 1e-6);
    checkClose("and 0 outside", mca::cage::windingNumber(cage, Vec3(3.0, 0.0, 0.0)), 0.0, 1e-9);
    checkClose("and 0 just outside a face",
               mca::cage::windingNumber(cage, Vec3(0.0, 0.0, 1.001)), 0.0, 1e-6);
}

void testRestAndRigid() {
    const Cage rest = boxCage(2.0);
    const std::vector<Vec3> points = insidePoints(2.0, 4);

    Bind bind;
    std::string problem;
    check("binding a box cage works", mca::cage::bind(rest, points, BindOptions(), bind, &problem),
          problem);

    std::printf("  rest error %s over %d points, %d exterior, partition off by %s\n",
                number(bind.worstRestError).c_str(), static_cast<int>(points.size()),
                bind.exteriorCount, number(bind.worstPartitionError).c_str());

    check("the rest cage puts every point back where it was, to a micron",
          bind.worstRestError < 1e-6, number(bind.worstRestError));
    check("no point inside the cage is treated as outside", bind.exteriorCount == 0,
          std::to_string(bind.exteriorCount));

    // Translation.
    std::vector<Vec3> got;
    ApplyOptions apply;
    check("applying a moved cage works",
          mca::cage::apply(bind, moved(rest, Vec3(3.0, -2.0, 5.0)), apply, got, &problem), problem);
    std::vector<Vec3> want;
    for (size_t index = 0; index < points.size(); ++index) {
        want.push_back(points[index] + Vec3(3.0, -2.0, 5.0));
    }
    const double translation = worstDistance(got, want);
    std::printf("  translation error %s\n", number(translation).c_str());
    // 1e-9 would be the answer if the weights were doubles. They are floats, which
    // is what keeps a cloth mesh's bind inside a few hundred megabytes, and the price
    // is about 1e-7 of the cage's size - 5 microns on a 200-unit character. Measured
    // rather than assumed, and one typedef away if anyone ever needs it tighter.
    check("moving the cage moves the mesh exactly, to the precision the weights are stored at",
          translation < 1e-6, number(translation));

    // Rotation.
    check("applying a turned cage works",
          mca::cage::apply(bind, turned(rest, 1.0), apply, got, &problem), problem);
    want.clear();
    for (size_t index = 0; index < points.size(); ++index) {
        want.push_back(turnedAboutY(points[index], 1.0));
    }
    const double rotation = worstDistance(got, want);
    std::printf("  rotation error %s\n", number(rotation).c_str());
    check("turning the cage turns the mesh exactly", rotation < 1e-6, number(rotation));
}

void testScale() {
    const Cage rest = boxCage(2.0);
    const std::vector<Vec3> points = insidePoints(2.0, 4);

    Bind bind;
    std::string problem;
    mca::cage::bind(rest, points, BindOptions(), bind, &problem);

    std::vector<Vec3> want;
    for (size_t index = 0; index < points.size(); ++index) {
        want.push_back(points[index] * 2.0);
    }

    ApplyOptions full;
    full.stretch = 1.0;
    std::vector<Vec3> got;
    mca::cage::apply(bind, scaled(rest, 2.0), full, got, &problem);
    const double withStretch = worstDistance(got, want);

    ApplyOptions none;
    none.stretch = 0.0;
    mca::cage::apply(bind, scaled(rest, 2.0), none, got, &problem);
    const double withoutStretch = worstDistance(got, want);

    std::printf("  a cage scaled 2x: with stretch %s, without %s\n",
                number(withStretch).c_str(), number(withoutStretch).c_str());

    check("at full stretch, doubling the cage doubles the mesh exactly", withStretch < 1e-6,
          number(withStretch));
    check("and at no stretch it deliberately does not - the shape keeps its thickness",
          withoutStretch > 1e-3, number(withoutStretch));
}

/// Numerically estimate the local 3x3 map at one point, by binding the point plus
/// three tiny offsets and seeing where the four of them land.
void localMap(const Cage& rest, const Cage& deformed, const Vec3& at, double step,
              bool useNormals, double out[3][3]) {
    std::vector<Vec3> probe = {at, at + Vec3(step, 0.0, 0.0), at + Vec3(0.0, step, 0.0),
                               at + Vec3(0.0, 0.0, step)};

    Bind bind;
    std::string problem;
    mca::cage::bind(rest, probe, BindOptions(), bind, &problem);

    if (!useNormals) {
        // The same deformation with the face term thrown away, which is what a cage
        // built out of vertex positions alone can do.
        bind.dropFaceWeights();
    }

    ApplyOptions apply;
    apply.stretch = 1.0;
    std::vector<Vec3> got;
    mca::cage::apply(bind, deformed, apply, got, &problem);

    for (int column = 0; column < 3; ++column) {
        const Vec3 delta = (got[static_cast<size_t>(column) + 1] - got[0]) * (1.0 / step);
        out[0][column] = delta.x;
        out[1][column] = delta.y;
        out[2][column] = delta.z;
    }
}

/// How far from a rotation-times-scale this map is: the off-diagonal of J^T J,
/// relative to its diagonal. Zero means angles are preserved exactly.
double shearOf(const double map[3][3]) {
    double gram[3][3];
    for (int row = 0; row < 3; ++row) {
        for (int column = 0; column < 3; ++column) {
            gram[row][column] = 0.0;
            for (int k = 0; k < 3; ++k) {
                gram[row][column] += map[k][row] * map[k][column];
            }
        }
    }
    const double size = std::max((gram[0][0] + gram[1][1] + gram[2][2]) / 3.0, 1e-12);
    double worst = 0.0;
    for (int row = 0; row < 3; ++row) {
        for (int column = 0; column < 3; ++column) {
            if (row != column) {
                worst = std::max(worst, std::fabs(gram[row][column]) / size);
            }
        }
    }
    return worst;
}

/// Shear a cage sideways and the enclosed shape must not skew with it.
///
/// **This is the reason the face normals are carried at all**, so it is measured
/// against not carrying them: the same bind, the same cage, with the face term
/// thrown away, which is what a cage built from vertex positions alone can do.
///
/// Two deformations, because they are not equally hard. A sideways shear of the cage
/// has a conformal answer and Green coordinates find it - the enclosed shape comes
/// out with essentially no skew at all. A twist does not: no map can twist a solid
/// and preserve every angle, so both methods distort, and the honest claim is that
/// this one distorts several times less.
void testNoShear() {
    const Cage rest = boxCage(2.0);
    const Vec3 spots[3] = {Vec3(0.7, 0.8, -0.5), Vec3(0.0, 1.2, 0.0), Vec3(-1.0, -1.0, 0.9)};

    double worstGreen = 0.0;
    double worstPositions = 0.0;
    for (int spot = 0; spot < 3; ++spot) {
        double withNormals[3][3];
        double withoutNormals[3][3];
        localMap(rest, sheared(rest, 0.15), spots[spot], 1e-3, true, withNormals);
        localMap(rest, sheared(rest, 0.15), spots[spot], 1e-3, false, withoutNormals);
        worstGreen = std::max(worstGreen, shearOf(withNormals));
        worstPositions = std::max(worstPositions, shearOf(withoutNormals));
    }
    std::printf("  a sheared cage: skew %s carrying the normals, %s without\n",
                number(worstGreen).c_str(), number(worstPositions).c_str());
    check("a sheared cage barely skews what it encloses at all", worstGreen < 1e-3,
          number(worstGreen));
    check("and dropping the face term is worse by orders of magnitude - which is why it is "
          "there",
          worstPositions > worstGreen * 100.0,
          number(worstGreen) + " against " + number(worstPositions));

    double twistGreen = 0.0;
    double twistPositions = 0.0;
    for (int spot = 0; spot < 3; ++spot) {
        double withNormals[3][3];
        double withoutNormals[3][3];
        localMap(rest, twisted(rest, 0.2), spots[spot], 1e-3, true, withNormals);
        localMap(rest, twisted(rest, 0.2), spots[spot], 1e-3, false, withoutNormals);
        twistGreen = std::max(twistGreen, shearOf(withNormals));
        twistPositions = std::max(twistPositions, shearOf(withoutNormals));
    }
    std::printf("  a twisted cage: skew %s carrying the normals, %s without\n",
                number(twistGreen).c_str(), number(twistPositions).c_str());
    check("a twist skews less with the normals than without", twistGreen * 1.5 < twistPositions,
          number(twistGreen) + " against " + number(twistPositions));
    check("and stays within what a twist of this size has to cost", twistGreen < 0.25,
          number(twistGreen));
}

/// The coordinates have to be CONTINUOUS. A point sitting exactly where two cage
/// triangles meet, or exactly on the axis through a pair of them, must get
/// essentially the same weights as a point a hair away - and the degenerate case is
/// the one where the integral has terms that are individually 0/0.
///
/// This is the check that found the halved weights. Every generic point passed; the
/// exact ones came out at half, and the deformation looked plausible while being
/// wrong by a factor of two down the middle of the mesh.
void testContinuity() {
    const Cage cage = boxCage(1.0);

    const std::vector<Vec3> awkward = {
        Vec3(0.0, 0.0, 0.6),    // on the axis through a triangulated face pair
        Vec3(0.0, 0.0, 0.0),    // the centre, on three of those axes at once
        Vec3(0.5, 0.5, 0.0),    // in the plane of a face diagonal
        Vec3(0.0, 0.4, 0.4),    // on the diagonal of another pair
        Vec3(0.9, 0.9, 0.9),    // near a corner, on the main diagonal
        Vec3(-0.3, 0.3, 0.0),
    };

    double worstWeight = 0.0;
    double worstSum = 0.0;
    double worstPlace = 0.0;

    for (size_t index = 0; index < awkward.size(); ++index) {
        const Vec3& point = awkward[index];

        std::vector<double> phi, psi;
        const double total = mca::cage::coordinates(cage, point, phi, psi);
        worstSum = std::max(worstSum, std::fabs(total - 1.0));

        // Where do these coordinates put the point back?
        Vec3 rebuilt;
        for (size_t vertex = 0; vertex < phi.size(); ++vertex) {
            rebuilt += cage.points[vertex] * phi[vertex];
        }
        for (size_t face = 0; face < psi.size(); ++face) {
            rebuilt += mca::cage::faceNormal(cage, face) * psi[face];
        }
        worstPlace = std::max(worstPlace, (rebuilt - point).length());

        // And a hair away, in a direction that lines up with nothing.
        const Vec3 nudged = point + Vec3(1e-6, 0.37e-6, -0.71e-6);
        std::vector<double> nudgedPhi, nudgedPsi;
        mca::cage::coordinates(cage, nudged, nudgedPhi, nudgedPsi);
        for (size_t vertex = 0; vertex < phi.size(); ++vertex) {
            worstWeight = std::max(worstWeight, std::fabs(phi[vertex] - nudgedPhi[vertex]));
        }
        for (size_t face = 0; face < psi.size(); ++face) {
            worstWeight = std::max(worstWeight, std::fabs(psi[face] - nudgedPsi[face]));
        }
    }

    std::printf("  awkward points: weights sum off by %s, rebuilt %s away, jitter moves a "
                "weight by %s\n",
                number(worstSum).c_str(), number(worstPlace).c_str(),
                number(worstWeight).c_str());

    check("the coordinates sum to one even where the integral is degenerate",
          worstSum < 1e-9, number(worstSum));
    check("and they put the point back exactly where it was", worstPlace < 1e-9,
          number(worstPlace));
    check("and a point a millionth of a unit away gets the same weights",
          worstWeight < 1e-5, number(worstWeight));
}

void testDegenerateArrangements() {
    // The arrangements that make the reference implementation produce NaN: a point
    // exactly on a cage vertex, exactly on an edge, exactly in the plane of a face,
    // and exactly on a face.
    const Cage rest = boxCage(1.0);
    std::vector<Vec3> points = {
        Vec3(1.0, 1.0, 1.0),      // on a cage corner
        Vec3(1.0, 0.0, 1.0),      // on a cage edge
        Vec3(0.0, 0.0, 1.0),      // on the middle of a face
        Vec3(0.5, 1.0, 0.0),      // on a face, off centre
        Vec3(0.0, 0.0, 0.0),      // dead centre
        Vec3(1.0 - 1e-12, 0.0, 0.0),
    };

    Bind bind;
    std::string problem;
    check("a point on the cage itself still binds",
          mca::cage::bind(rest, points, BindOptions(), bind, &problem), problem);

    std::vector<Vec3> got;
    ApplyOptions apply;
    apply.stretch = 1.0;
    mca::cage::apply(bind, moved(rest, Vec3(1.0, 1.0, 1.0)), apply, got, &problem);

    check("and produces no NaN or infinity", allFinite(got));
    for (size_t index = 0; index < got.size(); ++index) {
        const double error = (got[index] - (points[index] + Vec3(1.0, 1.0, 1.0))).length();
        check("a degenerate point still follows a moved cage, point " + std::to_string(index),
              error < 1e-6, number(error));
    }
}

void testOutsideTheCage() {
    const Cage rest = boxCage(1.0);
    std::vector<Vec3> points = {
        Vec3(0.0, 0.0, 0.0),   // inside
        Vec3(0.0, 0.0, 2.5),   // outside, past a face
        Vec3(3.0, 3.0, 3.0),   // outside, past a corner
    };

    Bind bind;
    std::string problem;
    check("a mesh poking through the cage still binds",
          mca::cage::bind(rest, points, BindOptions(), bind, &problem), problem);
    check("and the ones outside are counted", bind.exteriorCount == 2,
          std::to_string(bind.exteriorCount));
    check("the inside one is not flagged", !bind.exterior[0]);
    check("the outside ones are", bind.exterior[1] && bind.exterior[2]);

    std::vector<Vec3> got;
    ApplyOptions apply;
    apply.stretch = 1.0;
    mca::cage::apply(bind, moved(rest, Vec3(0.0, 4.0, 0.0)), apply, got, &problem);
    double worst = 0.0;
    for (size_t index = 0; index < points.size(); ++index) {
        worst = std::max(worst, (got[index] - (points[index] + Vec3(0.0, 4.0, 0.0))).length());
    }
    std::printf("  outside the cage, moved rigidly: worst error %s\n", number(worst).c_str());
    check("a point outside the cage still moves rigidly with it", worst < 1e-6, number(worst));

    mca::cage::apply(bind, turned(rest, 0.7), apply, got, &problem);
    worst = 0.0;
    for (size_t index = 0; index < points.size(); ++index) {
        worst = std::max(worst, (got[index] - turnedAboutY(points[index], 0.7)).length());
    }
    std::printf("  outside the cage, turned: worst error %s\n", number(worst).c_str());
    check("and turns with it", worst < 1e-5, number(worst));
}

void testRefusals() {
    const Cage rest = boxCage(1.0);
    const std::vector<Vec3> points = insidePoints(1.0, 2);

    Bind bind;
    std::string problem;
    mca::cage::bind(rest, points, BindOptions(), bind, &problem);

    Cage bigger = boxCage(1.0);
    bigger.points.push_back(Vec3(2.0, 2.0, 2.0));

    std::vector<Vec3> got;
    check("applying a cage with a different point count is refused",
          !mca::cage::apply(bind, bigger, ApplyOptions(), got, &problem));
    check("and the refusal says both counts",
          problem.find("bound with") != std::string::npos, problem);

    Bind empty;
    check("binding no points is refused",
          !mca::cage::bind(rest, std::vector<Vec3>(), BindOptions(), empty, &problem));
}

/// What the bind costs to hold, and that a thread count never changes it.
///
/// The memory number is the one that decides whether this is usable on cloth, and it is
/// arithmetic rather than a measurement: one float per cage element per mesh point. It is
/// printed here so it is impossible to be vague about it.
///
/// There is no pruning knob any more. The first version had one, on the assumption that
/// most weights would be negligible; at every floor from 1e-6 to 1e-2 it dropped exactly
/// none, because Green coordinates are global. What it did do was let a floor set too high
/// satisfy the rest-pose check by rebinding interior points to their closest triangle -
/// exact at rest, 0.7 units out when deformed. Removing it halved the memory, because the
/// index each weight carried was only there to support the pruning that never happened.
void testCostAndThreads() {
    const Cage rest = boxCage(2.0);
    const std::vector<Vec3> points = insidePoints(2.0, 6);

    BindOptions one;
    one.threads = 1;
    Bind single;
    std::string problem;
    mca::cage::bind(rest, points, one, single, &problem);

    const size_t bytes = single.termCount * sizeof(float);
    std::printf("  %d points on a %d-element cage: %d weights, %.2f KB (%.2f bytes a point)\n",
                static_cast<int>(points.size()),
                static_cast<int>(single.cageVertexCount + single.restFaces.size()),
                static_cast<int>(single.termCount), double(bytes) / 1024.0,
                double(bytes) / double(points.size()));

    check("every point gets a weight for every cage element",
          single.termCount == points.size() * (rest.vertexCount() + rest.triangleCount()),
          std::to_string(single.termCount));
    check("and the rest pose is exact", single.worstRestError < 1e-5,
          number(single.worstRestError));

    // One thread and many have to agree to the last bit, for the same reason as the pose
    // skinner: a result that wobbles with the schedule cannot be measured.
    BindOptions many;
    many.threads = 8;
    Bind threaded;
    mca::cage::bind(rest, points, many, threaded, &problem);

    bool identical = threaded.weights.size() == single.weights.size() &&
                     threaded.exterior == single.exterior;
    for (size_t index = 0; identical && index < single.weights.size(); ++index) {
        identical = single.weights[index] == threaded.weights[index];
    }
    check("eight threads give bit-identical weights to one", identical);
}

/// A cage with a ring of extra points round its middle, and mesh points sitting exactly
/// on the axis planes - which is what a polyCube cage with subdivisions and a polySphere
/// inside it actually look like.
///
/// This case exists because the Maya side reported six points of a sphere as needing to
/// be rebound, in a cage that plainly contained it, and the report called them "outside
/// the cage" - which sent me looking at containment when the real question was accuracy
/// near the cage surface. Both halves are now counted separately and both are checked
/// here.
void testSubdividedCage() {
    // A middle ring, as polyCube -subdivisionsY 2 gives: split each side face in two.
    // Done by hand rather than by subdividing, because what matters is that the cage's
    // triangle diagonals land on the axis planes, which is where the integral is awkward.
    Cage ringed;
    const double half = 2.0;
    for (int level = 0; level < 3; ++level) {
        const double y = -half + half * level;
        ringed.points.push_back(Vec3(-half, y, -half));
        ringed.points.push_back(Vec3(half, y, -half));
        ringed.points.push_back(Vec3(half, y, half));
        ringed.points.push_back(Vec3(-half, y, half));
    }
    for (int level = 0; level < 2; ++level) {
        const int a = level * 4;
        const int b = (level + 1) * 4;
        for (int side = 0; side < 4; ++side) {
            const int next = (side + 1) % 4;
            ringed.triangles.push_back(Triangle(a + side, b + side, b + next));
            ringed.triangles.push_back(Triangle(a + side, b + next, a + next));
        }
    }
    // The caps, wound so they face OUT: down at the bottom, up at the top. Getting
    // these backwards is what checkCage is for, and it caught them.
    ringed.triangles.push_back(Triangle(0, 1, 2));
    ringed.triangles.push_back(Triangle(0, 2, 3));
    ringed.triangles.push_back(Triangle(8, 10, 9));
    ringed.triangles.push_back(Triangle(8, 11, 10));

    std::string problem;
    check("a cage with a middle ring is valid", mca::cage::checkCage(ringed, &problem), problem);

    // A sphere of points, with a ring landing exactly on x = 0 and another on z = 0.
    std::vector<Vec3> points;
    const double pi = 3.14159265358979323846;
    const double radius = 1.6;

    // The poles FIRST, and they are the reason this case exists. A sphere's pole sits at
    // x = z = 0 exactly, so its projection onto the cage's cap lands exactly on that
    // cap's triangulation diagonal - and a sphere in a box cage therefore always has at
    // least two points in the most awkward configuration the integral has. The first
    // version of this test swept rings of latitude and skipped the poles, so it reported
    // nothing wrong while Maya was rebinding six points of the same setup.
    points.push_back(Vec3(0.0, radius, 0.0));
    points.push_back(Vec3(0.0, -radius, 0.0));

    // And the poles as MAYA gives them, which is the case that actually bites. Mesh
    // points come out of Maya as float32, so a pole that ought to be at exactly x = z = 0
    // arrives at 5e-8 from it - NEAR degenerate rather than degenerate, which is the
    // worse of the two: `acos` has lost its precision by then, but a threshold set at
    // 1e-9 still calls the configuration generic and runs the full formula on numbers
    // that no longer mean anything.
    points.push_back(Vec3(-4.7e-8, radius, 2.6e-8));
    points.push_back(Vec3(3.1e-8, -radius, -5.2e-8));

    for (int ring = 1; ring < 12; ++ring) {
        const double phi = pi * double(ring) / 12.0;
        for (int step = 0; step < 24; ++step) {
            const double theta = 2.0 * pi * double(step) / 24.0;
            points.push_back(Vec3(radius * std::sin(phi) * std::cos(theta),
                                  radius * std::cos(phi),
                                  radius * std::sin(phi) * std::sin(theta)));
        }
    }

    Bind bind;
    const bool bound = mca::cage::bind(ringed, points, BindOptions(), bind, &problem);
    check("it binds", bound, problem);
    if (!bound) {
        return;  // nothing below means anything, and indexing the empty result crashes
    }
    std::printf("  a subdivided cage, %d points at 80%% of its half-width: rest error %s, "
                "%d outside, %d rebound\n",
                static_cast<int>(points.size()), number(bind.worstRestError).c_str(),
                bind.exteriorCount, bind.healedCount);

    check("nothing is called outside the cage when nothing is", bind.exteriorCount == 0,
          std::to_string(bind.exteriorCount));
    check("and every point is reproduced without having to be rebound",
          bind.healedCount == 0, std::to_string(bind.healedCount));
    check("and the rest pose is still exact", bind.worstRestError < 1e-5,
          number(bind.worstRestError));

    ApplyOptions apply;
    apply.stretch = 1.0;
    std::vector<Vec3> got;
    const bool applied =
        mca::cage::apply(bind, moved(ringed, Vec3(2.0, -1.0, 0.5)), apply, got, &problem);
    check("applying the moved cage works", applied && got.size() == points.size(), problem);
    if (!applied || got.size() != points.size()) {
        return;
    }
    double worst = 0.0;
    for (size_t index = 0; index < points.size(); ++index) {
        worst = std::max(worst, (got[index] - (points[index] + Vec3(2.0, -1.0, 0.5))).length());
    }
    check("and it follows a moved cage", worst < 1e-5, number(worst));
}

/// Maya's own box cage and the six points of a sphere it could not reproduce.
///
/// **This is real data, kept verbatim, because it is the case three rounds of tolerance
/// work still missed.** A polyCube with one Y subdivision, triangulated by Maya, and a
/// polySphere inside it: six of the sphere's points came back with their coordinates
/// summing to 0.75 or 1.25 instead of 1, and the bind had to rebind them to their
/// closest face.
///
/// What they have in common is that |x| = |z| to within 3e-8 - they sit a hair off the
/// diagonal Maya chose for the cage's cap. Exactly on it is handled; a hair off it is
/// worse, because `acos` has lost its precision by then while a tolerance of 1e-9 still
/// calls the configuration generic and runs the full formula on numbers that no longer
/// mean anything. Every synthetic version of this case missed it: the points had to come
/// out of Maya, at float32, to be wrong in the right way.
void testMayaBoxCage() {
    Cage cage;
    cage.points = {
        Vec3(-2.0, -2.0, 2.0), Vec3(2.0, -2.0, 2.0),  Vec3(-2.0, 0.0, 2.0),
        Vec3(2.0, 0.0, 2.0),   Vec3(-2.0, 2.0, 2.0),  Vec3(2.0, 2.0, 2.0),
        Vec3(-2.0, 2.0, -2.0), Vec3(2.0, 2.0, -2.0),  Vec3(-2.0, 0.0, -2.0),
        Vec3(2.0, 0.0, -2.0),  Vec3(-2.0, -2.0, -2.0), Vec3(2.0, -2.0, -2.0),
    };
    cage.triangles = {
        Triangle(0, 1, 2),  Triangle(2, 1, 3),  Triangle(2, 3, 4),  Triangle(4, 3, 5),
        Triangle(4, 5, 6),  Triangle(6, 5, 7),  Triangle(6, 7, 8),  Triangle(8, 7, 9),
        Triangle(8, 9, 10), Triangle(10, 9, 11), Triangle(10, 11, 0), Triangle(0, 11, 1),
        Triangle(1, 11, 3), Triangle(3, 11, 9), Triangle(3, 9, 5),  Triangle(5, 9, 7),
        Triangle(10, 0, 8), Triangle(8, 0, 2),  Triangle(8, 2, 6),  Triangle(6, 2, 4),
    };

    std::string problem;
    check("Maya's own box cage is valid", mca::cage::checkCage(cage, &problem), problem);

    const std::vector<Vec3> points = {
        Vec3(0.147673473, -1.586311817, -0.147673443),
        Vec3(-0.292820215, -1.545481324, -0.292820245),
        Vec3(-0.292820275, -1.545481324, 0.292820245),
        Vec3(-0.292820215, 1.545481324, -0.292820245),
        Vec3(-0.292820275, 1.545481324, 0.292820245),
        Vec3(0.147673473, 1.586311817, -0.147673443),
    };

    double worstSum = 0.0;
    double worstRebuild = 0.0;
    for (size_t index = 0; index < points.size(); ++index) {
        std::vector<double> phi, psi;
        const double total = mca::cage::coordinates(cage, points[index], phi, psi);
        worstSum = std::max(worstSum, std::fabs(total - 1.0));

        Vec3 rebuilt;
        for (size_t vertex = 0; vertex < phi.size(); ++vertex) {
            rebuilt += cage.points[vertex] * phi[vertex];
        }
        for (size_t face = 0; face < psi.size(); ++face) {
            rebuilt += mca::cage::faceNormal(cage, face) * psi[face];
        }
        worstRebuild = std::max(worstRebuild, (rebuilt - points[index]).length());
    }

    BindOptions options;
    options.threads = 1;
    Bind bind;
    mca::cage::bind(cage, points, options, bind, &problem);

    std::printf("  Maya's six awkward points: weights sum off by %s, rebuilt %s away, "
                "%d rebound\n", number(worstSum).c_str(), number(worstRebuild).c_str(),
                bind.healedCount);

    check("the coordinates of Maya's awkward points sum to one", worstSum < 1e-9,
          number(worstSum));
    check("and put the points back where they were", worstRebuild < 1e-9,
          number(worstRebuild));
    check("so none of them has to be rebound to its closest face", bind.healedCount == 0,
          std::to_string(bind.healedCount));
}

void testCost() {
    // Roughly a cape: a few thousand points on a small cage. Printed for the record
    // rather than asserted - a timing that fails on a busy machine teaches people
    // to ignore failures.
    const Cage rest = boxCage(10.0);
    const std::vector<Vec3> points = insidePoints(10.0, 14);

    const std::clock_t started = std::clock();
    Bind bind;
    std::string problem;
    mca::cage::bind(rest, points, BindOptions(), bind, &problem);
    const double bindSeconds = double(std::clock() - started) / CLOCKS_PER_SEC;

    const Cage deformed = twisted(rest, 0.3);
    std::vector<Vec3> got;
    ApplyOptions apply;
    apply.stretch = 0.5;

    const std::clock_t applyStarted = std::clock();
    for (int pass = 0; pass < 50; ++pass) {
        mca::cage::apply(bind, deformed, apply, got, &problem);
    }
    const double applySeconds = double(std::clock() - applyStarted) / CLOCKS_PER_SEC / 50.0;

    std::printf("  %d points on %d cage faces: bind %.3fs, apply %.5fs per frame, %d terms\n",
                static_cast<int>(points.size()), static_cast<int>(rest.triangleCount()),
                bindSeconds, applySeconds, static_cast<int>(bind.termCount));
    check("the cost run produced a usable bind", bind.worstRestError < 1e-5,
          number(bind.worstRestError));
}

}  // namespace

int main() {
    testCageChecks();
    testWinding();
    testRestAndRigid();
    testScale();
    testNoShear();
    testContinuity();
    testDegenerateArrangements();
    testOutsideTheCage();
    testRefusals();
    testCostAndThreads();
    testSubdividedCage();
    testMayaBoxCage();
    testCost();

    std::printf("\n%d/%d checks passed.\n", gChecks - gFailures, gChecks);
    return gFailures == 0 ? 0 : 1;
}
