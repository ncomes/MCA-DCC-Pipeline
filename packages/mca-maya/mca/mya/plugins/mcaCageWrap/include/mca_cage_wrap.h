// MCA-DCC Pipeline - cage deformation by Green coordinates.
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// A low-resolution "cage" wrapped around a mesh; move the cage, the mesh follows.
// Green coordinates (Lipman, Levin and Cohen-Or, SIGGRAPH 2008) rather than the
// barycentric or harmonic kind, and the difference is the whole point:
//
//   barycentric / harmonic:   p' = sum_i  phi_i * v_i'
//   Green:                    p' = sum_i  phi_i * v_i'  +  sum_j  psi_j * s_j * n_j'
//
// The second term is what stops it shearing. A cage built only from vertex
// positions has no way to know which way the surface is FACING, so twisting the
// cage slides the enclosed shape sideways. Carrying the cage's face normals as a
// second basis makes the map quasi-conformal: rotate or bend the cage and the
// shape rotates and bends with it instead of skewing.
//
// This header is deliberately free of Maya. Everything here takes points and
// triangles and hands back points, so the whole method is testable in a second
// under cl.exe with no Maya, no licence and no viewport - which is where all of
// the accuracy numbers in the docs come from.

#ifndef MCA_CAGE_WRAP_H
#define MCA_CAGE_WRAP_H

#include <cmath>
#include <cstddef>
#include <string>
#include <vector>

namespace mca {
namespace cage {

/// A point or a direction. Kept local to this namespace so that including this
/// header alongside another plug-in's maths cannot collide.
struct Vec3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;

    Vec3() {}
    Vec3(double xx, double yy, double zz) : x(xx), y(yy), z(zz) {}

    Vec3 operator+(const Vec3& other) const { return Vec3(x + other.x, y + other.y, z + other.z); }
    Vec3 operator-(const Vec3& other) const { return Vec3(x - other.x, y - other.y, z - other.z); }
    Vec3 operator*(double scale) const { return Vec3(x * scale, y * scale, z * scale); }
    Vec3& operator+=(const Vec3& other) { x += other.x; y += other.y; z += other.z; return *this; }

    double dot(const Vec3& other) const { return x * other.x + y * other.y + z * other.z; }
    Vec3 cross(const Vec3& other) const {
        return Vec3(y * other.z - z * other.y, z * other.x - x * other.z, x * other.y - y * other.x);
    }
    double lengthSquared() const { return x * x + y * y + z * z; }
    double length() const { return std::sqrt(lengthSquared()); }
    Vec3 unit() const {
        const double size = length();
        return size > 0.0 ? Vec3(x / size, y / size, z / size) : Vec3();
    }
};

/// One triangle of the cage, by cage vertex index.
struct Triangle {
    int a = 0;
    int b = 0;
    int c = 0;

    Triangle() {}
    Triangle(int aa, int bb, int cc) : a(aa), b(bb), c(cc) {}
};

/// The cage: points, and triangles wound so their normals point outward.
///
/// It has to be **triangulated** because the coordinate integral is defined over
/// triangles, and **closed** because the integral is over a boundary that encloses
/// something. A cage with a hole in it does not enclose anything, and the weights
/// come back meaning nothing rather than coming back wrong in an obvious way -
/// which is why both are checked before any work is done.
struct Cage {
    std::vector<Vec3> points;
    std::vector<Triangle> triangles;

    size_t vertexCount() const { return points.size(); }
    size_t triangleCount() const { return triangles.size(); }
};

/// How one mesh point is tied to the cage: every cage vertex's weight, then every cage
/// face's.
///
/// **Dense, and `float`, and both were arrived at by measurement.** The first version
/// stored index/weight pairs and offered a `weightFloor` to drop the small ones, on the
/// assumption that most weights would be negligible. They are not: Green coordinates are
/// GLOBAL - every cage element contributes something to every point - and at every floor
/// from 1e-6 to 1e-2 not one weight was ever dropped. So the index was pure overhead: 4
/// bytes per weight spent recording a position that is implied by the order.
///
/// Dropping it halves the memory, removes a knob that did nothing, and makes applying a
/// flat walk through contiguous floats instead of a chase through per-point vectors.
/// `float` costs about 1e-7 of the cage's size, which is five microns on a 200-unit
/// character.
///
/// A row is laid out as `cageVertexCount` vertex weights followed by `cageFaceCount` face
/// weights, so `row(point)` is the vertex part and `row(point) + cageVertexCount` the
/// face part.

/// What to bind with./// What to bind with.
struct BindOptions {
    /// 0 lets the machine decide (capped, see mca_parallel.h).
    int threads = 0;
};

/// Per cage triangle, the rest measurements the stretch factor is made from.
///
/// Kept in the bind rather than recomputed from the rest cage every frame, so that
/// applying needs the DEFORMED cage and nothing else. That matters for more than
/// speed: a deformer that has to be handed both cages every evaluation is a
/// deformer that goes quietly wrong the day somebody edits the rest one.
struct FaceRest {
    double area = 0.0;  ///< rest area
    double uu = 0.0;    ///< |u|^2, u being the first rest edge
    double vv = 0.0;    ///< |v|^2, v being the second
    double uv = 0.0;    ///< u . v
};

/// A finished bind, plus everything measured while making it.
struct Bind {
    /// One row of weights per mesh point: `cageVertexCount` vertex weights then
    /// `cageFaceCount` face weights. See the note above on why this is dense.
    std::vector<float> weights;

    /// Per mesh point: bound to its closest cage triangle rather than by coordinates,
    /// because it sits outside the cage or on it.
    std::vector<char> exterior;

    std::vector<FaceRest> restFaces;  ///< per cage triangle
    size_t cageVertexCount = 0;       ///< what it was bound to, so apply can refuse a mismatch
    size_t pointCount = 0;

    /// Weights per point: cage vertices plus cage faces.
    size_t stride() const { return cageVertexCount + restFaces.size(); }

    /// This point's weights. The first `cageVertexCount` are the cage's vertices.
    const float* row(size_t point) const { return weights.data() + point * stride(); }
    float* row(size_t point) { return weights.data() + point * stride(); }

    /// Throw the face weights away, leaving a deformation built from cage POSITIONS
    /// alone - which is what a lattice or a barycentric cage can do.
    ///
    /// Here because the tests need it: the claim that carrying the face normals stops the
    /// shape shearing is only worth making against the same bind without them, and a test
    /// that reached into the weights to do that by hand would have to be rewritten every
    /// time this structure changes.
    void dropFaceWeights();

    // --- what it measured about itself -------------------------------------- //

    /// Worst distance between a point's rest position and where this bind puts it with
    /// the cage at rest. **The self-check that matters.** If the bind is wrong - bad
    /// winding, a hole, a duplicated cage vertex - this is not small, and no amount of
    /// looking at the deformation will tell you as clearly.
    double worstRestError = 0.0;
    int worstRestVertex = -1;

    /// How far the coordinates strayed from summing to one before they were normalised.
    /// Grows for a point sitting almost on the cage surface, which is the one place this
    /// method is genuinely delicate.
    double worstPartitionError = 0.0;

    /// Points the winding number said were OUTSIDE the cage, or on it.
    int exteriorCount = 0;

    /// Points that were inside the cage, but whose coordinates could not reproduce their
    /// own rest position, so they were rebound to their closest triangle.
    ///
    /// Counted separately from `exteriorCount` because they mean different things and the
    /// fix is different. Points outside the cage are a modelling question - the cage
    /// misses part of the mesh. Points rebound in here are an accuracy question: the
    /// coordinates go singular at the cage surface, so a mesh whose points sit very close
    /// to the cage gets some, and a little more clearance takes them away. Adding them
    /// together and calling the total "outside the cage" reads as a cage that does not
    /// contain the mesh, which sent me looking in the wrong place for an afternoon.
    int healedCount = 0;

    /// Weights stored, which is `pointCount * stride()`. Multiply by 4 bytes for what the
    /// bind is holding.
    size_t termCount = 0;
};

/// What to apply with.
struct ApplyOptions {
    /// How much of each cage triangle's stretch is passed on to the thickness of
    /// what it encloses, 0 to 1.
    ///
    /// At 0 the shape is conformal: angles are preserved and a stretched cage
    /// leaves the enclosed shape the thickness it always was. At 1 the shape
    /// thickens and thins with the cage, which is what squash and stretch means
    /// and what makes a uniformly scaled cage scale the mesh. Neither is "right" -
    /// a bending gun barrel wants 0, a cartoon bouncing ball wants 1.
    double stretch = 0.0;

    int threads = 0;
};

// --- the maths ------------------------------------------------------------- //

/// Outward normal of one cage triangle. Unit length, or zero for a degenerate one.
Vec3 faceNormal(const Cage& cage, size_t triangle);

/// Area of one cage triangle.
double faceArea(const Cage& cage, size_t triangle);

/// Is this cage usable? Triangulated is implied by the structure; this is about
/// being closed, wound consistently, and free of degenerate triangles.
///
/// :param problem: filled with one sentence fit to show a person.
/// :return: true when the cage can be bound to.
bool checkCage(const Cage& cage, std::string* problem);

/// Six times the volume the cage encloses, signed by its winding.
///
/// Positive when the faces point outward, which is what everything here assumes.
/// Exposed because "your cage is inside out" is a thing a person needs told in those
/// words rather than as a deformation that does nothing useful.
double signedVolume(const Cage& cage);

/// How many times the cage wraps around this point: 1 inside, 0 outside.
///
/// The generalised winding number, by summing each triangle's signed solid angle.
/// Worth knowing that this is not a separate trick bolted on - for a closed cage
/// the sum of the Green vertex coordinates IS this number, which is why "the
/// weights add up to less than a half" is a sound test for being outside rather
/// than the heuristic it looks like.
double windingNumber(const Cage& cage, const Vec3& point);

/// The raw Green coordinates of ONE point: a weight per cage vertex and a weight
/// per cage face, exactly as the integral gives them.
///
/// Not normalised, not pruned, and meaningless for a point outside the cage - all
/// of which `bind` deals with. Public because being able to look at one point's
/// coordinates in isolation is how every mistake in this file was found, and a test
/// that can only see the finished deformation cannot tell a factor of two in the
/// weights from a factor of two somewhere else.
///
/// :param phi: resized to the cage's vertex count.
/// :param psi: resized to the cage's triangle count.
/// :return: the sum of `phi`, which for a closed cage is the winding number - 1
///     inside, 0 outside.
double coordinates(const Cage& restCage, const Vec3& point, std::vector<double>& phi,
                   std::vector<double>& psi);

/// Tie every mesh point to the cage. The expensive half: O(points x triangles).
///
/// :param restCage: the cage where it was modelled, matching the points.
/// :param points: the mesh, in the same space as the cage.
/// :return: false with `problem` set when the cage cannot be bound to.
bool bind(const Cage& restCage, const std::vector<Vec3>& points, const BindOptions& options,
          Bind& out, std::string* problem);

/// Move the points with the cage. The cheap half, and the one that runs per frame.
///
/// :param deformedCage: same topology as the rest cage, moved.
/// :return: false with `problem` set when the cage no longer matches the bind.
bool apply(const Bind& bind, const Cage& deformedCage, const ApplyOptions& options,
           std::vector<Vec3>& out, std::string* problem);

/// The per-triangle stretch factor Green coordinates need, one per cage face.
///
/// Exposed because it is worth being able to look at: a face whose factor is 3
/// is a face that has been stretched threefold, and at `stretch` = 1 everything
/// it encloses gets three times thicker.
void stretchFactors(const Bind& bind, const Cage& deformedCage, std::vector<double>& out);

}  // namespace cage
}  // namespace mca

#endif  // MCA_CAGE_WRAP_H
