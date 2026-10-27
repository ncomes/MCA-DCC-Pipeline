// MCA-DCC Pipeline - cage deformation by Green coordinates.
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_cage_wrap.h"

#include <algorithm>
#include <map>
#include <utility>

#include "mca_parallel.h"

namespace mca {
namespace cage {

namespace {

const double kPi = 3.14159265358979323846;

/// Below this, a length or an area is treated as zero.
///
/// Absolute rather than relative because it guards divisions inside the integral,
/// where the quantities have already been reduced to direction cosines and unit
/// normals - so they are not in scene units and cannot be scaled away.
const double kTiny = 1e-12;

/// A sine this small is treated as zero, and as approached from above.
const double kSinTiny = 1e-12;

/// How flat a wedge has to be before it counts as having no area at all.
///
/// This is a SINE, measured directly from a cross product, and that is the first half of
/// the point. The angles in the integral come out of `acos`, which loses half its
/// significant digits near 1: a point sitting on the line of a cage edge gives an angle
/// of 2e-8 rather than 0, so no tolerance expressed in angles can separate "on the line"
/// from "near it". A cross product over the two lengths gives the sine to full precision.
///
/// The second half is the SIZE, and 1e-7 is not a round number picked for comfort - it
/// comes from Maya. Mesh points arrive as float32, so a vertex that ought to sit exactly
/// on a cage triangle's diagonal arrives 3e-8 off it. That is the worst of both worlds:
/// far enough off to be called generic by a tight threshold, close enough that `acos`
/// has nothing left to say about it. At 1e-9, six points of a polySphere in a polyCube
/// cage came back with their coordinates summing to 0.75 instead of 1 - a quarter
/// missing, the mesh 0.4 units out at those points - and every synthetic version of the
/// case passed, because a point placed by hand is either exactly on the line or a long
/// way off it.
///
/// So the threshold has to sit above float32's idea of "on the line" (about 1e-8
/// relative) and below anything a person would call a real angle. 1e-7 does, and the cost
/// of treating a wedge that thin as flat is of the same order as the float noise already
/// in the stored weights.
const double kDegenerateSine = 1e-7;

double clamped(double value, double low, double high) {
    return value < low ? low : (value > high ? high : value);
}

/// The integral at the heart of Green coordinates.
///
/// This is the paper's GCTriInt: the contribution of one triangle, seen from one
/// point, along one edge. Everything else in the bind is bookkeeping around three
/// calls to this per triangle.
///
/// **The degenerate cases are the whole difficulty, and they are not rare.** When
/// the point's projection lands on the line of an edge, `alpha` is zero, `sin(theta)`
/// is zero, and two of the terms below are 0/0. The obvious reading is that a
/// sub-triangle with no area contributes nothing, so both the reference
/// implementation and the first version of this file returned zero there.
///
/// That is wrong, and measurably so. The individual terms of the sum are NOT each
/// continuous - only their total is - and the limit as alpha goes to zero is
/// `pi * sqrt(c) / 2`, not zero. Dropping it loses exactly `sqrt(c) / 8` from that
/// face's coordinate: on a box cage, every point on the axis through a pair of
/// triangulated faces came out at HALF the weight it should have, and the mesh
/// landed at half the distance. It reproduces as a crease down the middle of
/// anything symmetrically cased - which is most props - and it is invisible in a
/// generic test, because a randomly placed point never hits the line exactly.
///
/// So nothing is skipped here. Each division is guarded at the point of division
/// and given the value the limit takes, and `test_cage.cpp` checks continuity
/// directly: the coordinates at a degenerate point have to agree with the
/// coordinates a hair away from it.
double triangleIntegral(const Vec3& p, const Vec3& v1, const Vec3& v2, const Vec3& eta) {
    const Vec3 edge = v2 - v1;
    const Vec3 toP = p - v1;
    if (edge.lengthSquared() < kTiny || toP.lengthSquared() < kTiny) {
        return 0.0;
    }

    const Vec3 fromV1 = v1 - p;
    const Vec3 fromV2 = v2 - p;
    if (fromV1.lengthSquared() < kTiny || fromV2.lengthSquared() < kTiny) {
        return 0.0;
    }

    // The wedge from p out to this edge is flat: p lies on the line through v1 and
    // v2, so this edge covers no area and contributes nothing.
    //
    // Caught here, geometrically, rather than by the angles below. On a box cage
    // this is not an edge case at all - the projection of any point on the axis
    // through a triangulated face pair lands exactly on that pair's shared diagonal,
    // which is every point down the middle of the mesh. Left to the angles, the term
    // comes out at a quarter of the distance to that face instead of zero, with the
    // sign decided by rounding, and the deformation is wrong by a factor of two
    // along a seam while looking perfectly smooth.
    const double flatness = fromV1.cross(fromV2).length();
    if (flatness <= kDegenerateSine * fromV1.length() * fromV2.length()) {
        return 0.0;
    }

    const double alpha = std::acos(clamped(edge.unit().dot(toP.unit()), -1.0, 1.0));
    const double beta = std::acos(clamped(fromV1.unit().dot(fromV2.unit()), -1.0, 1.0));

    const double sinAlpha = std::sin(alpha);
    const double lambda = fromV1.lengthSquared() * sinAlpha * sinAlpha;
    const double c = (p - eta).lengthSquared();
    const double rootC = std::sqrt(c);
    const double rootLambda = std::sqrt(lambda);

    const double theta[2] = {kPi - alpha, kPi - alpha - beta};
    double integral[2] = {0.0, 0.0};

    for (int which = 0; which < 2; ++which) {
        const double s = std::sin(theta[which]);
        const double cosine = std::cos(theta[which]);

        // A sine of zero has to count as POSITIVE, and not by its floating-point
        // sign bit. Where the point's projection sits on an edge, both thetas come
        // out at zero to within rounding, and whether the arithmetic lands on -1e-17
        // or +1e-17 decides the sign of a term worth a quarter of the cage's
        // distance to that face. Reading the sign bit made the same geometry give
        // the right answer on one face pair of a box and an answer off by
        // sqrt(c)/4 on another, which looks like the method being fragile and is
        // really this line.
        //
        // Positive is the correct side: theta is pi - alpha, and alpha + beta only
        // passes pi where the edge is degenerate, which is exactly where the limit
        // below applies.
        const double sign = s < -kSinTiny ? -1.0 : 1.0;

        double first = 0.0;
        if (c > kTiny) {
            const double denominator = std::sqrt(lambda + s * s * c);
            if (denominator > kSinTiny) {
                first = 2.0 * rootC * std::atan((rootC * cosine) / denominator);
            } else {
                // Both lambda and sin(theta) have gone to zero, so the argument of
                // the arctangent has gone to plus or minus infinity. This is the
                // term the naive reading throws away.
                const double limit = cosine > 0.0 ? kPi / 2.0 : (cosine < 0.0 ? -kPi / 2.0 : 0.0);
                first = 2.0 * rootC * limit;
            }
        }

        double second = 0.0;
        if (lambda > kTiny) {
            const double oneMinusCos = 1.0 - cosine;
            const double under = c * (1.0 + cosine) + lambda +
                                 std::sqrt(lambda * lambda + lambda * c * s * s);
            if (oneMinusCos > kTiny && under > kTiny) {
                const double argument = (2.0 * rootLambda * s * s) / (oneMinusCos * oneMinusCos) *
                                        (1.0 - (2.0 * c * cosine) / under);
                // A logarithm of a non-positive number is the other way this goes
                // NaN, and where it happens the term itself is vanishing.
                if (argument > kTiny) {
                    second = rootLambda * std::log(argument);
                }
            }
        }

        integral[which] = (-sign / 2.0) * (first + second);
    }

    const double value = integral[0] - integral[1] - rootC * beta;
    return -1.0 / (4.0 * kPi) * std::fabs(value);
}

/// Solve the 4x4 system that binds a point outside the cage to its closest
/// triangle: three barycentric shares of the triangle's corners, plus a distance
/// along its normal.
///
/// Small enough that Gaussian elimination with partial pivoting is the whole
/// story, which keeps Eigen out of this file - one less thing to be careful about
/// on a worker thread.
bool solveLocalFrame(const Vec3& a, const Vec3& b, const Vec3& c, const Vec3& normal,
                     const Vec3& point, double out[4]) {
    double m[4][5] = {
        {a.x, b.x, c.x, normal.x, point.x},
        {a.y, b.y, c.y, normal.y, point.y},
        {a.z, b.z, c.z, normal.z, point.z},
        {1.0, 1.0, 1.0, 0.0, 1.0},
    };

    for (int column = 0; column < 4; ++column) {
        int pivot = column;
        for (int row = column + 1; row < 4; ++row) {
            if (std::fabs(m[row][column]) > std::fabs(m[pivot][column])) {
                pivot = row;
            }
        }
        if (std::fabs(m[pivot][column]) < kTiny) {
            return false;
        }
        if (pivot != column) {
            for (int k = 0; k < 5; ++k) {
                std::swap(m[column][k], m[pivot][k]);
            }
        }
        for (int row = 0; row < 4; ++row) {
            if (row == column) {
                continue;
            }
            const double factor = m[row][column] / m[column][column];
            for (int k = column; k < 5; ++k) {
                m[row][k] -= factor * m[column][k];
            }
        }
    }

    for (int row = 0; row < 4; ++row) {
        out[row] = m[row][4] / m[row][row];
    }
    return true;
}

/// Closest point on one triangle, and its distance. Plain geometry, no acceleration
/// structure: the fallback runs for the handful of vertices outside the cage, and a
/// bounding hierarchy for that many points costs more to build than it saves.
double distanceToTriangle(const Vec3& point, const Vec3& a, const Vec3& b, const Vec3& c) {
    const Vec3 ab = b - a;
    const Vec3 ac = c - a;
    const Vec3 ap = point - a;

    const double d1 = ab.dot(ap);
    const double d2 = ac.dot(ap);
    if (d1 <= 0.0 && d2 <= 0.0) {
        return ap.length();
    }

    const Vec3 bp = point - b;
    const double d3 = ab.dot(bp);
    const double d4 = ac.dot(bp);
    if (d3 >= 0.0 && d4 <= d3) {
        return bp.length();
    }

    const double vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0) {
        const double t = d1 / std::max(d1 - d3, kTiny);
        return (ap - ab * t).length();
    }

    const Vec3 cp = point - c;
    const double d5 = ab.dot(cp);
    const double d6 = ac.dot(cp);
    if (d6 >= 0.0 && d5 <= d6) {
        return cp.length();
    }

    const double vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0 && d2 >= 0.0 && d6 <= 0.0) {
        const double t = d2 / std::max(d2 - d6, kTiny);
        return (ap - ac * t).length();
    }

    const double va = d3 * d6 - d5 * d4;
    if (va <= 0.0 && (d4 - d3) >= 0.0 && (d5 - d6) >= 0.0) {
        const double t = (d4 - d3) / std::max((d4 - d3) + (d5 - d6), kTiny);
        return (bp - (c - b) * t).length();
    }

    const double denominator = std::max(va + vb + vc, kTiny);
    const double v = vb / denominator;
    const double w = vc / denominator;
    return (ap - ab * v - ac * w).length();
}

/// Longest side of the cage's bounding box, which is what every scale-free
/// tolerance in here is a fraction of.
double cageSize(const Cage& cage) {
    if (cage.points.empty()) {
        return 0.0;
    }
    Vec3 low = cage.points[0];
    Vec3 high = cage.points[0];
    for (size_t index = 1; index < cage.points.size(); ++index) {
        const Vec3& point = cage.points[index];
        low.x = std::min(low.x, point.x);
        low.y = std::min(low.y, point.y);
        low.z = std::min(low.z, point.z);
        high.x = std::max(high.x, point.x);
        high.y = std::max(high.y, point.y);
        high.z = std::max(high.z, point.z);
    }
    return (high - low).length();
}

}  // namespace

Vec3 faceNormal(const Cage& cage, size_t triangle) {
    const Triangle& face = cage.triangles[triangle];
    const Vec3& a = cage.points[static_cast<size_t>(face.a)];
    const Vec3& b = cage.points[static_cast<size_t>(face.b)];
    const Vec3& c = cage.points[static_cast<size_t>(face.c)];
    return (b - a).cross(c - a).unit();
}

double faceArea(const Cage& cage, size_t triangle) {
    const Triangle& face = cage.triangles[triangle];
    const Vec3& a = cage.points[static_cast<size_t>(face.a)];
    const Vec3& b = cage.points[static_cast<size_t>(face.b)];
    const Vec3& c = cage.points[static_cast<size_t>(face.c)];
    return 0.5 * (b - a).cross(c - a).length();
}

bool checkCage(const Cage& cage, std::string* problem) {
    const auto fail = [problem](const std::string& text) {
        if (problem) {
            *problem = text;
        }
        return false;
    };

    if (cage.points.size() < 4) {
        return fail("A cage needs at least four points to enclose anything.");
    }
    if (cage.triangles.empty()) {
        return fail("The cage has no triangles.");
    }

    const int vertexCount = static_cast<int>(cage.points.size());
    std::map<std::pair<int, int>, int> edges;

    for (size_t index = 0; index < cage.triangles.size(); ++index) {
        const Triangle& face = cage.triangles[index];
        const int corner[3] = {face.a, face.b, face.c};

        for (int which = 0; which < 3; ++which) {
            if (corner[which] < 0 || corner[which] >= vertexCount) {
                return fail("Cage triangle " + std::to_string(index) + " refers to point " +
                            std::to_string(corner[which]) + ", which does not exist.");
            }
        }
        if (corner[0] == corner[1] || corner[1] == corner[2] || corner[0] == corner[2]) {
            return fail("Cage triangle " + std::to_string(index) +
                        " uses the same point twice, so it has no area or direction.");
        }
        if (faceArea(cage, index) < kTiny) {
            return fail("Cage triangle " + std::to_string(index) +
                        " has no area. Weld or delete it - a triangle with no area has no "
                        "normal, and the deformation is built out of the normals.");
        }

        // Each directed edge must appear exactly once. Twice means two faces wound
        // the same way, which is a flipped normal; not at all means a hole.
        for (int which = 0; which < 3; ++which) {
            const std::pair<int, int> directed(corner[which], corner[(which + 1) % 3]);
            if (++edges[directed] > 1) {
                return fail(
                    "Two cage triangles share the edge between points " +
                    std::to_string(directed.first) + " and " + std::to_string(directed.second) +
                    " in the same direction, which means one of them is wound the wrong way "
                    "round. Every normal has to point outward.");
            }
        }
    }

    for (const auto& entry : edges) {
        const std::pair<int, int> opposite(entry.first.second, entry.first.first);
        if (edges.find(opposite) == edges.end()) {
            return fail("The cage has a hole: the edge between points " +
                        std::to_string(entry.first.first) + " and " +
                        std::to_string(entry.first.second) +
                        " has a triangle on one side only. A cage has to be closed, because "
                        "the coordinates are an integral over a surface that encloses "
                        "something.");
        }
    }

    // Consistent winding is not the same as OUTWARD winding. A cage built from a mesh
    // whose normals are reversed passes every check above and then behaves as though
    // the whole world were inside it and the mesh outside: every point falls to the
    // closest-triangle fallback, the deformation is poor, and nothing says why. Found
    // exactly that way, by a test cage whose triangles were wound the wrong way round.
    if (signedVolume(cage) <= 0.0) {
        return fail("The cage is inside out - its faces point inward, so it encloses "
                    "everything except what it is meant to. Reverse them (Mesh Display > "
                    "Reverse, or polyNormal -normalMode 0).");
    }

    if (problem) {
        problem->clear();
    }
    return true;
}

double signedVolume(const Cage& cage) {
    double total = 0.0;
    for (size_t index = 0; index < cage.triangles.size(); ++index) {
        const Triangle& face = cage.triangles[index];
        const Vec3& a = cage.points[static_cast<size_t>(face.a)];
        const Vec3& b = cage.points[static_cast<size_t>(face.b)];
        const Vec3& c = cage.points[static_cast<size_t>(face.c)];
        total += a.dot(b.cross(c));
    }
    return total;
}

double windingNumber(const Cage& cage, const Vec3& point) {
    double total = 0.0;

    for (size_t index = 0; index < cage.triangles.size(); ++index) {
        const Triangle& face = cage.triangles[index];
        const Vec3 a = cage.points[static_cast<size_t>(face.a)] - point;
        const Vec3 b = cage.points[static_cast<size_t>(face.b)] - point;
        const Vec3 c = cage.points[static_cast<size_t>(face.c)] - point;

        const double lengthA = a.length();
        const double lengthB = b.length();
        const double lengthC = c.length();
        if (lengthA < kTiny || lengthB < kTiny || lengthC < kTiny) {
            return 1.0;  // the point is ON the cage; call it inside
        }

        // Van Oosterom and Strackee: the signed solid angle of a triangle seen
        // from the origin, in one atan2.
        const double numerator = a.dot(b.cross(c));
        const double denominator = lengthA * lengthB * lengthC + a.dot(b) * lengthC +
                                   b.dot(c) * lengthA + c.dot(a) * lengthB;
        total += 2.0 * std::atan2(numerator, denominator);
    }

    return total / (4.0 * kPi);
}

double coordinates(const Cage& restCage, const Vec3& point, std::vector<double>& phi,
                   std::vector<double>& psi) {
    const size_t cageVertices = restCage.vertexCount();
    const size_t cageFaces = restCage.triangleCount();

    phi.assign(cageVertices, 0.0);
    psi.assign(cageFaces, 0.0);

    for (size_t face = 0; face < cageFaces; ++face) {
        const Triangle& triangle = restCage.triangles[face];
        const int corner[3] = {triangle.a, triangle.b, triangle.c};
        const Vec3 normal = faceNormal(restCage, face);

        Vec3 toCorner[3];
        for (int which = 0; which < 3; ++which) {
            toCorner[which] = restCage.points[static_cast<size_t>(corner[which])] - point;
        }

        // The point projected onto the triangle's plane, measured from the point.
        const Vec3 projected = normal * toCorner[0].dot(normal);

        double integral[3];
        double edgeIntegral[3];
        double sign[3];
        Vec3 edgeNormal[3];
        const Vec3 origin;

        for (int which = 0; which < 3; ++which) {
            const int next = (which + 1) % 3;

            const double side =
                (toCorner[which] - projected).cross(toCorner[next] - projected).dot(normal);
            sign[which] = side < 0.0 ? -1.0 : 1.0;

            integral[which] = triangleIntegral(projected, toCorner[which], toCorner[next], origin);
            edgeIntegral[which] = triangleIntegral(origin, toCorner[next], toCorner[which], origin);
            edgeNormal[which] = toCorner[next].cross(toCorner[which]).unit();
        }

        const double facePart =
            std::fabs(sign[0] * integral[0] + sign[1] * integral[1] + sign[2] * integral[2]);
        psi[face] = facePart;

        Vec3 combined = normal * (-facePart);
        for (int which = 0; which < 3; ++which) {
            combined += edgeNormal[which] * edgeIntegral[which];
        }

        if (combined.length() > 1e-9) {
            for (int which = 0; which < 3; ++which) {
                const int next = (which + 1) % 3;
                const double denominator = edgeNormal[next].dot(toCorner[which]);
                if (std::fabs(denominator) > kTiny) {
                    phi[static_cast<size_t>(corner[which])] +=
                        edgeNormal[next].dot(combined) / denominator;
                }
            }
        }
    }

    double total = 0.0;
    for (size_t vertex = 0; vertex < cageVertices; ++vertex) {
        total += phi[vertex];
    }
    return total;
}

void Bind::dropFaceWeights() {
    for (size_t point = 0; point < pointCount; ++point) {
        float* values = row(point);
        for (size_t face = 0; face < restFaces.size(); ++face) {
            values[cageVertexCount + face] = 0.0f;
        }
    }
}

bool bind(const Cage& restCage, const std::vector<Vec3>& points, const BindOptions& options,
          Bind& out, std::string* problem) {
    if (!checkCage(restCage, problem)) {
        return false;
    }
    if (points.empty()) {
        if (problem) {
            *problem = "There are no points to bind.";
        }
        return false;
    }

    const size_t cageVertices = restCage.vertexCount();
    const size_t cageFaces = restCage.triangleCount();

    // Rest measurements, once.
    std::vector<Vec3> normals(cageFaces);
    out.restFaces.assign(cageFaces, FaceRest());
    for (size_t index = 0; index < cageFaces; ++index) {
        normals[index] = faceNormal(restCage, index);

        const Triangle& face = restCage.triangles[index];
        const Vec3 u = restCage.points[static_cast<size_t>(face.b)] -
                       restCage.points[static_cast<size_t>(face.a)];
        const Vec3 v = restCage.points[static_cast<size_t>(face.c)] -
                       restCage.points[static_cast<size_t>(face.a)];

        FaceRest& rest = out.restFaces[index];
        rest.area = faceArea(restCage, index);
        rest.uu = u.lengthSquared();
        rest.vv = v.lengthSquared();
        rest.uv = u.dot(v);
    }

    out.cageVertexCount = cageVertices;
    out.pointCount = points.size();
    out.termCount = points.size() * (cageVertices + cageFaces);

    // One allocation for the whole bind. Every point owns its own row, so the loop below
    // is thread-safe without a single lock or a per-point allocation.
    out.weights.assign(out.termCount, 0.0f);
    out.exterior.assign(points.size(), 0);

    const double size = cageSize(restCage);

    std::vector<double> partitionError(points.size(), 0.0);
    std::vector<char> healed(points.size(), 0);
    std::vector<double> restError(points.size(), 0.0);

    // Write one point's coordinates into its row.
    const auto store = [&](const std::vector<double>& phi, const std::vector<double>& psi,
                           size_t point) {
        float* values = out.row(point);
        for (size_t vertex = 0; vertex < cageVertices; ++vertex) {
            values[vertex] = static_cast<float>(phi[vertex]);
        }
        for (size_t face = 0; face < cageFaces; ++face) {
            values[cageVertices + face] = static_cast<float>(psi[face]);
        }
    };

    // Where do these stored weights actually put the point, with the cage at rest?
    // Stored, not computed: this is what the deformer will evaluate, floats and all.
    const auto replay = [&](size_t point) {
        const float* values = out.row(point);
        Vec3 landed;
        for (size_t vertex = 0; vertex < cageVertices; ++vertex) {
            landed += restCage.points[vertex] * static_cast<double>(values[vertex]);
        }
        for (size_t face = 0; face < cageFaces; ++face) {
            landed += normals[face] * static_cast<double>(values[cageVertices + face]);
        }
        return landed;
    };

    // Bind one point to its closest cage triangle: three barycentric shares and a
    // distance along the normal. Exact for any affine motion of that triangle, and
    // sensible for the rest.
    const auto localFrame = [&](const Vec3& point, std::vector<double>& phi,
                                std::vector<double>& psi) {
        phi.assign(cageVertices, 0.0);
        psi.assign(cageFaces, 0.0);

        size_t closest = 0;
        double best = -1.0;
        for (size_t face = 0; face < cageFaces; ++face) {
            const Triangle& triangle = restCage.triangles[face];
            const double distance =
                distanceToTriangle(point, restCage.points[static_cast<size_t>(triangle.a)],
                                   restCage.points[static_cast<size_t>(triangle.b)],
                                   restCage.points[static_cast<size_t>(triangle.c)]);
            if (best < 0.0 || distance < best) {
                best = distance;
                closest = face;
            }
        }

        const Triangle& triangle = restCage.triangles[closest];
        double share[4] = {0.0, 0.0, 0.0, 0.0};
        if (!solveLocalFrame(restCage.points[static_cast<size_t>(triangle.a)],
                             restCage.points[static_cast<size_t>(triangle.b)],
                             restCage.points[static_cast<size_t>(triangle.c)], normals[closest],
                             point, share)) {
            // Nothing sensible to say about this point, so it is left where it is rather
            // than sent somewhere arbitrary.
            phi[static_cast<size_t>(triangle.a)] = 1.0;
            return;
        }

        phi[static_cast<size_t>(triangle.a)] = share[0];
        phi[static_cast<size_t>(triangle.b)] = share[1];
        phi[static_cast<size_t>(triangle.c)] = share[2];
        psi[closest] = share[3];
    };

    // What counts as the bind having failed for one point. Well above the noise the float
    // storage leaves behind, which is around 1e-7 of the cage's size.
    const double allowed = 1e-5 * (size > 0.0 ? size : 1.0);

    std::string trouble;
    parallelFor(static_cast<int>(points.size()), options.threads, [&](int which) {
        const size_t index = static_cast<size_t>(which);
        const Vec3& point = points[index];

        std::vector<double> phi;
        std::vector<double> psi;
        const double total = coordinates(restCage, point, phi, psi);
        partitionError[index] = std::fabs(total - 1.0);

        // The vertex coordinates sum to the winding number, so a total near zero means the
        // point is outside the cage and the integral above describes nothing. Those points
        // go to the local frame instead - replaced rather than added to, which is what the
        // reference does with coordinates it has just decided are meaningless.
        bool useLocal = !(total > 0.5);
        if (!useLocal) {
            // Normalise. The integral is accurate to about a part in a million, and the
            // property this method leans on is that the vertex weights sum to exactly one
            // - that is what makes a translated cage translate the mesh exactly rather
            // than nearly.
            for (size_t vertex = 0; vertex < cageVertices; ++vertex) {
                phi[vertex] /= total;
            }
        } else {
            localFrame(point, phi, psi);
        }

        store(phi, psi, index);
        double error = (replay(index) - point).length();

        // And then the part that makes this trustworthy: every point is checked against
        // itself, and a point the coordinates cannot reproduce is bound another way.
        //
        // The case that needs it is a mesh point sitting ON the cage surface, where the
        // integral is genuinely singular - the face weight grows without bound and there
        // is no precision left to hold it. That is not an exotic input: it is what a cage
        // offset by zero, or snapped to the silhouette, produces. Before this check those
        // points flew off by half the mesh and nothing said which ones or why.
        if (error > allowed && !useLocal) {
            std::vector<double> localPhi;
            std::vector<double> localPsi;
            localFrame(point, localPhi, localPsi);

            // Keep whichever reproduces the point better, and say which was used.
            std::vector<float> kept(out.row(index), out.row(index) + out.stride());
            store(localPhi, localPsi, index);
            const double attemptError = (replay(index) - point).length();

            if (attemptError < error) {
                error = attemptError;
                useLocal = true;
                healed[index] = 1;
            } else {
                std::copy(kept.begin(), kept.end(), out.row(index));
            }
        }

        out.exterior[index] = useLocal ? 1 : 0;
        restError[index] = error;
    }, &trouble);

    if (!trouble.empty()) {
        if (problem) {
            *problem = trouble;
        }
        return false;
    }

    out.exteriorCount = 0;
    out.healedCount = 0;
    out.worstPartitionError = 0.0;
    out.worstRestError = 0.0;
    out.worstRestVertex = -1;
    for (size_t index = 0; index < points.size(); ++index) {
        out.exteriorCount += (out.exterior[index] != 0 && healed[index] == 0) ? 1 : 0;
        out.healedCount += healed[index] != 0 ? 1 : 0;
        out.worstPartitionError = std::max(out.worstPartitionError, partitionError[index]);
        if (restError[index] > out.worstRestError) {
            out.worstRestError = restError[index];
            out.worstRestVertex = static_cast<int>(index);
        }
    }

    if (problem) {
        problem->clear();
    }
    return true;
}

void stretchFactors(const Bind& bind, const Cage& deformedCage, std::vector<double>& out) {
    const size_t faces = bind.restFaces.size();
    out.assign(faces, 1.0);

    for (size_t index = 0; index < faces && index < deformedCage.triangleCount(); ++index) {
        const FaceRest& rest = bind.restFaces[index];
        if (rest.area < kTiny) {
            continue;
        }

        const Triangle& face = deformedCage.triangles[index];
        const Vec3 u = deformedCage.points[static_cast<size_t>(face.b)] -
                       deformedCage.points[static_cast<size_t>(face.a)];
        const Vec3 v = deformedCage.points[static_cast<size_t>(face.c)] -
                       deformedCage.points[static_cast<size_t>(face.a)];

        // The paper's stretch factor: how much this triangle grew, measured in a way
        // that is 1 when it did not change and equal to the scale when the whole
        // cage is scaled.
        const double inside = u.lengthSquared() * rest.vv - 2.0 * u.dot(v) * rest.uv +
                              v.lengthSquared() * rest.uu;
        if (inside <= 0.0) {
            continue;
        }
        out[index] = std::sqrt(inside) / (std::sqrt(8.0) * rest.area);
    }
}

bool apply(const Bind& bind, const Cage& deformedCage, const ApplyOptions& options,
           std::vector<Vec3>& out, std::string* problem) {
    if (deformedCage.vertexCount() != bind.cageVertexCount ||
        deformedCage.triangleCount() != bind.restFaces.size()) {
        if (problem) {
            *problem = "The cage has " + std::to_string(deformedCage.vertexCount()) +
                       " points and " + std::to_string(deformedCage.triangleCount()) +
                       " triangles; it was bound with " + std::to_string(bind.cageVertexCount) +
                       " and " + std::to_string(bind.restFaces.size()) +
                       ". The rest and deformed cages have to be the same mesh, moved.";
        }
        return false;
    }

    const size_t faces = deformedCage.triangleCount();
    const size_t cageVertices = deformedCage.vertexCount();

    std::vector<Vec3> normals(faces);
    for (size_t index = 0; index < faces; ++index) {
        normals[index] = faceNormal(deformedCage, index);
    }

    // At a stretch of zero every factor is one, so the whole pass is skipped. The
    // reference computes them on every evaluation whether they are used or not.
    std::vector<double> stretch;
    const bool useStretch = options.stretch > 0.0;
    if (useStretch) {
        stretchFactors(bind, deformedCage, stretch);
        for (size_t index = 0; index < stretch.size(); ++index) {
            stretch[index] = 1.0 + options.stretch * (stretch[index] - 1.0);
        }
    }

    out.assign(bind.pointCount, Vec3());

    std::string trouble;
    parallelFor(static_cast<int>(bind.pointCount), options.threads, [&](int which) {
        const size_t index = static_cast<size_t>(which);
        const float* values = bind.row(index);

        Vec3 moved;
        for (size_t vertex = 0; vertex < cageVertices; ++vertex) {
            const double weight = static_cast<double>(values[vertex]);
            if (weight != 0.0) {
                moved += deformedCage.points[vertex] * weight;
            }
        }
        for (size_t face = 0; face < faces; ++face) {
            const double weight = static_cast<double>(values[cageVertices + face]);
            if (weight == 0.0) {
                continue;
            }
            moved += normals[face] * (weight * (useStretch ? stretch[face] : 1.0));
        }
        out[index] = moved;
    }, &trouble);

    if (!trouble.empty()) {
        if (problem) {
            *problem = trouble;
        }
        return false;
    }
    if (problem) {
        problem->clear();
    }
    return true;
}

}  // namespace cage
}  // namespace mca
