// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.

#include "mca_mesh_tiler.h"
#include "mca_node_ids.h"

#include <maya/MFnNumericAttribute.h>
#include <maya/MFnTypedAttribute.h>
#include <maya/MFnEnumAttribute.h>
#include <maya/MFnMatrixAttribute.h>
#include <maya/MFnMesh.h>
#include <maya/MFnMeshData.h>
#include <maya/MArrayDataHandle.h>
#include <maya/MFloatVectorArray.h>
#include <maya/MItMeshPolygon.h>
#include <maya/MItMeshVertex.h>
#include <maya/MGlobal.h>
#include <maya/MPointArray.h>
#include <maya/MUintArray.h>
#include <maya/MDoubleArray.h>
#include <maya/MFloatArray.h>
#include <maya/MStringArray.h>
#include <maya/MMatrix.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <functional>
#include <string>
#include <utility>

const MString McaMeshTiler::kNodeName("mcaMeshTiler");
const MTypeId McaMeshTiler::kNodeId = mca::nodeId(mca::kMeshTilerNode);

MObject McaMeshTiler::aTileMesh;
MObject McaMeshTiler::aTargetMesh;
MObject McaMeshTiler::aOutMesh;
MObject McaMeshTiler::aTileUpAxis;
MObject McaMeshTiler::aHeight;
MObject McaMeshTiler::aHeightOffset;
MObject McaMeshTiler::aAreaScale;
MObject McaMeshTiler::aFaceRotation;
MObject McaMeshTiler::aWorldToOutput;
MObject McaMeshTiler::aBoundaryInterpolation;
MObject McaMeshTiler::aNormalMode;
MObject McaMeshTiler::aUseMeshCreases;
MObject McaMeshTiler::aCreaseSharpness;
MObject McaMeshTiler::aCornerSharpness;
MObject McaMeshTiler::aTilesU;
MObject McaMeshTiler::aTilesV;
MObject McaMeshTiler::aCopyUVs;
MObject McaMeshTiler::aRefineNonQuads;

namespace {

enum NormalMode { kFaceNormal = 0, kSurfaceNormal = 1, kDerivativeNormal = 2 };

/// Face vertex counts and ids as flat arrays.
void readTopology(MObject mesh, std::vector<int>& counts, std::vector<int>& ids) {
    counts.clear();
    ids.clear();
    MItMeshPolygon iterator(mesh);
    for (; !iterator.isDone(); iterator.next()) {
        MIntArray faceVertices;
        iterator.getVertices(faceVertices);
        counts.push_back(static_cast<int>(faceVertices.length()));
        for (unsigned int index = 0u; index < faceVertices.length(); ++index) {
            ids.push_back(faceVertices[index]);
        }
    }
}

void readPoints(MObject mesh, MSpace::Space space, std::vector<mca::Vec3>& out) {
    MPointArray points;
    MFnMesh(mesh).getPoints(points, space);
    out.resize(points.length());
    for (unsigned int index = 0u; index < points.length(); ++index) {
        out[index] = mca::Vec3(points[index].x, points[index].y, points[index].z);
    }
}

void readVertexNormals(MObject mesh, std::vector<mca::Vec3>& out) {
    MFloatVectorArray normals;
    MFnMesh(mesh).getVertexNormals(false, normals, MSpace::kWorld);
    out.resize(normals.length());
    for (unsigned int index = 0u; index < normals.length(); ++index) {
        out[index] = mca::Vec3(normals[index].x, normals[index].y, normals[index].z);
    }
}

void readFaceNormals(MObject mesh, std::vector<mca::Vec3>& out) {
    MFnMesh function(mesh);
    const int faceCount = function.numPolygons();
    out.resize(static_cast<std::size_t>(faceCount));
    for (int face = 0; face < faceCount; ++face) {
        MVector normal;
        function.getPolygonNormal(face, normal, MSpace::kWorld);
        out[static_cast<std::size_t>(face)] = mca::Vec3(normal.x, normal.y, normal.z);
    }
}

/// Mean area of the faces touching each vertex, which is what area scaling
/// interpolates across the surface.
void readVertexAreas(MObject mesh, std::vector<double>& out) {
    MFnMesh function(mesh);
    const int vertexCount = function.numVertices();
    out.assign(static_cast<std::size_t>(vertexCount), 0.0);

    std::vector<double> faceAreas;
    MItMeshPolygon faceIterator(mesh);
    for (; !faceIterator.isDone(); faceIterator.next()) {
        double area = 0.0;
        faceIterator.getArea(area, MSpace::kWorld);
        faceAreas.push_back(area);
    }

    MItMeshVertex vertexIterator(mesh);
    for (; !vertexIterator.isDone(); vertexIterator.next()) {
        MIntArray faces;
        vertexIterator.getConnectedFaces(faces);
        double total = 0.0;
        for (unsigned int index = 0u; index < faces.length(); ++index) {
            const int face = faces[index];
            if (face >= 0 && face < static_cast<int>(faceAreas.size())) {
                total += faceAreas[static_cast<std::size_t>(face)];
            }
        }
        // A vertex with no faces is not tiled against anything, so its area is
        // meaningless rather than zero - but zero keeps the arithmetic finite.
        const int index = vertexIterator.index();
        if (faces.length() > 0u && index >= 0 && index < vertexCount) {
            out[static_cast<std::size_t>(index)] = total / static_cast<double>(faces.length());
        }
    }
}

/// The crease and corner values the rigger actually authored on the mesh.
///
/// The tool this replaces ignored these entirely and applied one value to every
/// edge and vertex, which is why its `crease` attribute never behaved like a
/// crease.
void readMeshCreases(MObject mesh, mca::SharpnessOptions& sharpness) {
    MFnMesh function(mesh);

    MUintArray creaseEdges;
    MDoubleArray creaseValues;
    if (function.getCreaseEdges(creaseEdges, creaseValues) == MS::kSuccess) {
        for (unsigned int index = 0u; index < creaseEdges.length(); ++index) {
            int2 vertices = {0, 0};
            if (function.getEdgeVertices(static_cast<int>(creaseEdges[index]), vertices) !=
                MS::kSuccess) {
                continue;
            }
            sharpness.creaseVertexPairs.push_back(vertices[0]);
            sharpness.creaseVertexPairs.push_back(vertices[1]);
            sharpness.creaseWeights.push_back(static_cast<float>(creaseValues[index]));
        }
    }

    MUintArray cornerVertices;
    MDoubleArray cornerValues;
    if (function.getCreaseVertices(cornerVertices, cornerValues) == MS::kSuccess) {
        for (unsigned int index = 0u; index < cornerVertices.length(); ++index) {
            sharpness.cornerVertexIds.push_back(static_cast<int>(cornerVertices[index]));
            sharpness.cornerWeights.push_back(static_cast<float>(cornerValues[index]));
        }
    }
}

/// Prefix a message with the node name. MString will not concatenate numbers,
/// so anything with a count in it is built as std::string first.
MString note(const std::string& text) {
    return MString("mcaMeshTiler: ") + text.c_str();
}

/// Fold a value into a running hash, so a cache key can cover settings as well
/// as topology.
void mixHash(std::size_t& hash, std::size_t value) {
    hash ^= value + 0x9e3779b97f4a7c15ull + (hash << 6) + (hash >> 2);
}

void mixHash(std::size_t& hash, double value) {
    // Bit pattern rather than the number, so -0.0 and 0.0 are the same key and
    // NaN is at least stable.
    std::size_t bits = 0u;
    static_assert(sizeof(bits) >= sizeof(value), "double must fit in size_t for hashing");
    std::memcpy(&bits, &value, sizeof(value));
    mixHash(hash, bits);
}

/// Mix a whole float array into a key.
void mixHash(std::size_t& hash, const std::vector<float>& values) {
    mixHash(hash, values.size());
    for (float value : values) {
        mixHash(hash, static_cast<double>(value));
    }
}
void mixHash(std::size_t& hash, const std::vector<int>& values) {
    mixHash(hash, values.size());
    for (int value : values) {
        mixHash(hash, static_cast<std::size_t>(static_cast<unsigned int>(value)));
    }
}

}  // namespace

void* McaMeshTiler::creator() { return new McaMeshTiler(); }

MStatus McaMeshTiler::initialize() {
    MFnTypedAttribute typedAttr;
    MFnNumericAttribute numericAttr;
    MFnEnumAttribute enumAttr;
    MFnMatrixAttribute matrixAttr;
    MStatus status;

    // --- meshes ------------------------------------------------------------ //

    aTileMesh = typedAttr.create("tileMesh", "tm", MFnData::kMesh, MObject::kNullObj, &status);
    typedAttr.setStorable(false);
    addAttribute(aTileMesh);

    aTargetMesh =
        typedAttr.create("targetMesh", "gm", MFnData::kMesh, MObject::kNullObj, &status);
    typedAttr.setStorable(false);
    addAttribute(aTargetMesh);

    aOutMesh = typedAttr.create("outMesh", "om", MFnData::kMesh, MObject::kNullObj, &status);
    typedAttr.setWritable(false);
    typedAttr.setStorable(false);
    addAttribute(aOutMesh);

    // --- placement ---------------------------------------------------------- //

    // The tool this replaces hard-coded Y and documented it nowhere, so a tile
    // authored any other way came out wrong with no clue as to why.
    aTileUpAxis = enumAttr.create("tileUpAxis", "tua", 1, &status);
    enumAttr.addField("X", 0);
    enumAttr.addField("Y", 1);
    enumAttr.addField("Z", 2);
    enumAttr.setKeyable(true);
    addAttribute(aTileUpAxis);

    aHeight = numericAttr.create("height", "hgt", MFnNumericData::kDouble, 1.0, &status);
    numericAttr.setKeyable(true);
    numericAttr.setSoftMin(0.0);
    numericAttr.setSoftMax(5.0);
    addAttribute(aHeight);

    aHeightOffset =
        numericAttr.create("heightOffset", "hof", MFnNumericData::kDouble, 0.0, &status);
    numericAttr.setKeyable(true);
    numericAttr.setSoftMin(-5.0);
    numericAttr.setSoftMax(5.0);
    addAttribute(aHeightOffset);

    aAreaScale = numericAttr.create("areaScale", "asc", MFnNumericData::kDouble, 0.0, &status);
    numericAttr.setKeyable(true);
    numericAttr.setMin(0.0);
    numericAttr.setMax(1.0);
    addAttribute(aAreaScale);

    aFaceRotation = numericAttr.create("faceRotation", "fro", MFnNumericData::kShort, 0, &status);
    numericAttr.setArray(true);
    numericAttr.setKeyable(true);
    addAttribute(aFaceRotation);

    aWorldToOutput = matrixAttr.create("worldToOutput", "wto", MFnMatrixAttribute::kDouble,
                                       &status);
    addAttribute(aWorldToOutput);

    // --- surface -------------------------------------------------------------- //

    aBoundaryInterpolation = enumAttr.create("boundaryInterpolation", "bin", 1, &status);
    enumAttr.addField("Edge", 0);
    enumAttr.addField("Edge and Corner", 1);
    enumAttr.setKeyable(true);
    addAttribute(aBoundaryInterpolation);

    aNormalMode = enumAttr.create("normalMode", "nmo", kSurfaceNormal, &status);
    enumAttr.addField("Face", kFaceNormal);
    enumAttr.addField("Surface", kSurfaceNormal);
    enumAttr.addField("Derivative", kDerivativeNormal);
    enumAttr.setKeyable(true);
    addAttribute(aNormalMode);

    aUseMeshCreases =
        numericAttr.create("useMeshCreases", "umc", MFnNumericData::kBoolean, true, &status);
    numericAttr.setKeyable(true);
    addAttribute(aUseMeshCreases);

    aCreaseSharpness =
        numericAttr.create("creaseSharpness", "csh", MFnNumericData::kFloat, 0.0f, &status);
    numericAttr.setKeyable(true);
    numericAttr.setMin(0.0);
    numericAttr.setMax(10.0);
    addAttribute(aCreaseSharpness);

    aCornerSharpness =
        numericAttr.create("cornerSharpness", "cosh", MFnNumericData::kFloat, 0.0f, &status);
    numericAttr.setKeyable(true);
    numericAttr.setMin(0.0);
    numericAttr.setMax(10.0);
    addAttribute(aCornerSharpness);

    // --- tiles ----------------------------------------------------------------- //

    // Fill a face with a grid of tiles instead of stretching one over it. The
    // counts are fixed rather than derived from face area on purpose: sizing
    // tiles in world units would make the tile count depend on the target's
    // geometry, so a deforming rig would change the output mesh's topology
    // mid-animation and break caching, Alembic export and shader assignment.
    aTilesU = numericAttr.create("tilesU", "tu", MFnNumericData::kInt, 1, &status);
    numericAttr.setKeyable(true);
    numericAttr.setMin(1);
    numericAttr.setSoftMax(8);
    addAttribute(aTilesU);

    aTilesV = numericAttr.create("tilesV", "tv", MFnNumericData::kInt, 1, &status);
    numericAttr.setKeyable(true);
    numericAttr.setMin(1);
    numericAttr.setSoftMax(8);
    addAttribute(aTilesV);

    aCopyUVs = numericAttr.create("copyUVs", "cuv", MFnNumericData::kBoolean, true, &status);
    numericAttr.setKeyable(true);
    addAttribute(aCopyUVs);

    aRefineNonQuads =
        numericAttr.create("refineNonQuads", "rnq", MFnNumericData::kBoolean, true, &status);
    numericAttr.setKeyable(true);
    addAttribute(aRefineNonQuads);

    // --- wiring ------------------------------------------------------------------ //
    //
    // No hidden helper attribute. The tool this replaces carried a `clonedChanged`
    // boolean purely as a manual dirty flag, with attributeAffects wired into it
    // and isClean/setClean in compute - working around the DG rather than using
    // it. Caching here is keyed on a hash of what was actually read.
    const MObject inputs[] = {aTileMesh,
                              aTargetMesh,
                              aTileUpAxis,
                              aHeight,
                              aHeightOffset,
                              aAreaScale,
                              aFaceRotation,
                              aWorldToOutput,
                              aBoundaryInterpolation,
                              aNormalMode,
                              aUseMeshCreases,
                              aCreaseSharpness,
                              aCornerSharpness,
                              aTilesU,
                              aTilesV,
                              aCopyUVs,
                              aRefineNonQuads};
    for (const MObject& input : inputs) {
        status = attributeAffects(input, aOutMesh);
        if (!status) {
            return status;
        }
    }

    return MS::kSuccess;
}

MStatus McaMeshTiler::compute(const MPlug& plug, MDataBlock& data) {
    // Saying kSuccess for a plug we did not compute tells Maya we did work we
    // did not do. The tool this replaces did exactly that.
    if (plug != aOutMesh) {
        return MS::kUnknownParameter;
    }

    MStatus status;
    MDataHandle outHandle = data.outputValue(aOutMesh, &status);
    if (!status) {
        return status;
    }

    // HasNoEffect means pass the input through, not "leave whatever was here
    // last time", which is what the original did.
    const int nodeState = data.inputValue(state).asInt();
    if (nodeState == 1) {
        outHandle.setMObject(data.inputValue(aTargetMesh).asMesh());
        data.setClean(plug);
        return MS::kSuccess;
    }

    const MObject tileMesh = data.inputValue(aTileMesh).asMesh();
    const MObject targetMesh = data.inputValue(aTargetMesh).asMesh();
    if (tileMesh.isNull() || targetMesh.isNull()) {
        MGlobal::displayWarning(note("needs both a tileMesh and a targetMesh."));
        data.setClean(plug);
        return MS::kSuccess;
    }

    status = rebuildTile(data);
    if (!status) {
        data.setClean(plug);
        return MS::kSuccess;
    }

    status = rebuildSubdiv(data, targetMesh);
    if (!status || !subdiv_.valid()) {
        data.setClean(plug);
        return MS::kSuccess;
    }

    // --- evaluate ---------------------------------------------------------- //

    std::vector<mca::Vec3> controlPoints;
    readPoints(targetMesh, MSpace::kWorld, controlPoints);

    std::vector<mca::Vec3> positions;
    if (!subdiv_.evaluatePoints(controlPoints, positions)) {
        MGlobal::displayWarning(note("the target mesh changed under the cache."));
        data.setClean(plug);
        return MS::kSuccess;
    }

    const short normalMode = data.inputValue(aNormalMode).asShort();
    std::vector<mca::Vec3> normals;

    if (normalMode == kDerivativeNormal) {
        subdiv_.evaluateNormals(controlPoints, normals);
    } else if (normalMode == kFaceNormal) {
        std::vector<mca::Vec3> faceNormals;
        readFaceNormals(targetMesh, faceNormals);
        const std::vector<int>& sourceFaces = subdiv_.tileSourceFaces();
        normals.resize(positions.size());
        for (int tile = 0; tile < subdiv_.tileCount(); ++tile) {
            const int face = sourceFaces[static_cast<std::size_t>(tile)];
            const mca::Vec3 normal =
                (face >= 0 && face < static_cast<int>(faceNormals.size()))
                    ? faceNormals[static_cast<std::size_t>(face)]
                    : mca::Vec3(0.0, 1.0, 0.0);
            for (int vertex = 0; vertex < subdiv_.verticesPerTile(); ++vertex) {
                normals[static_cast<std::size_t>(tile) * subdiv_.verticesPerTile() + vertex] =
                    normal;
            }
        }
    } else {
        std::vector<mca::Vec3> vertexNormals;
        readVertexNormals(targetMesh, vertexNormals);
        subdiv_.evaluateVectors(vertexNormals, normals);
    }

    if (normals.size() != positions.size()) {
        normals.assign(positions.size(), mca::Vec3(0.0, 1.0, 0.0));
    }

    // Renormalise, whatever the mode produced.
    //
    // Interpolating unit vertex normals through the limit surface does NOT give
    // a unit vector: the stencil weights sum to one, so the result is an average
    // of directions and it shortens wherever the surface curves. On a cube's
    // limit surface the corner normals point far enough apart that a height
    // offset of 0.5 moved the tiles only 0.144 - so `height` silently meant
    // different things in flat and curved regions. The tool this replaces had
    // the same behaviour and no test that would have noticed.
    //
    // Area scaling is applied to the height rather than to the normal's length,
    // so normalising here does not fight it.
    for (mca::Vec3& normal : normals) {
        const double length =
            std::sqrt(normal.x * normal.x + normal.y * normal.y + normal.z * normal.z);
        if (length > 1e-12) {
            normal.x /= length;
            normal.y /= length;
            normal.z /= length;
        }
    }

    // Area scaling: interpolate the mean adjacent face area across the surface,
    // then scale each tile's height by how that compares to its footprint.
    const double areaBlend = data.inputValue(aAreaScale).asDouble();
    std::vector<double> areaFactors;
    if (areaBlend > 1e-9) {
        std::vector<double> vertexAreas;
        readVertexAreas(targetMesh, vertexAreas);
        std::vector<double> sampledAreas;
        if (subdiv_.evaluateScalars(vertexAreas, sampledAreas)) {
            areaFactors.resize(sampledAreas.size());
            for (std::size_t index = 0u; index < sampledAreas.size(); ++index) {
                areaFactors[index] =
                    mca::areaScaleFactor(sampledAreas[index], tile_.baseArea, areaBlend);
            }
        }
    }

    const double height = data.inputValue(aHeight).asDouble();
    const double heightOffset = data.inputValue(aHeightOffset).asDouble();
    const MMatrix worldToOutput = data.inputValue(aWorldToOutput).asMatrix();
    const bool applyMatrix = !worldToOutput.isEquivalent(MMatrix::identity);

    MPointArray outPoints;
    outPoints.setLength(static_cast<unsigned int>(positions.size()));

    const int perTile = subdiv_.verticesPerTile();
    for (std::size_t index = 0u; index < positions.size(); ++index) {
        const std::size_t tileVertex = index % static_cast<std::size_t>(perTile);
        const double raw = tile_.height[tileVertex];
        const double factor = areaFactors.empty() ? 1.0 : areaFactors[index];
        const double lift = raw * height * factor + heightOffset;

        MPoint point(positions[index].x + normals[index].x * lift,
                     positions[index].y + normals[index].y * lift,
                     positions[index].z + normals[index].z * lift);
        if (applyMatrix) {
            point *= worldToOutput;
        }
        outPoints.set(point, static_cast<unsigned int>(index));
    }

    if (outMeshData_.isNull() || outVertexCount_ != outPoints.length()) {
        MGlobal::displayWarning(note("output topology is out of step with the tiles."));
        data.setClean(plug);
        return MS::kSuccess;
    }

    MFnMesh(outMeshData_).setPoints(outPoints);
    outHandle.setMObject(outMeshData_);
    data.setClean(plug);
    return MS::kSuccess;
}

MStatus McaMeshTiler::rebuildTile(MDataBlock& data) {
    const MObject tileMesh = data.inputValue(aTileMesh).asMesh();
    const short upAxisValue = data.inputValue(aTileUpAxis).asShort();

    std::vector<int> counts;
    std::vector<int> ids;
    readTopology(tileMesh, counts, ids);

    std::vector<mca::Vec3> points;
    readPoints(tileMesh, MSpace::kObject, points);

    // Read the tile's UV sets up front so they are part of the key. Editing a
    // tile's UVs without touching a vertex is an ordinary thing to do, and if
    // the key ignored them the output would keep serving the old layout.
    std::vector<TileUVSet> uvSets;
    {
        MFnMesh function(tileMesh);
        MStringArray setNames;
        function.getUVSetNames(setNames);
        for (unsigned int set = 0u; set < setNames.length(); ++set) {
            const MString& setName = setNames[set];
            MFloatArray u;
            MFloatArray v;
            if (function.getUVs(u, v, &setName) != MS::kSuccess || u.length() == 0u) {
                continue;
            }
            MIntArray uvCounts;
            MIntArray uvIds;
            if (function.getAssignedUVs(uvCounts, uvIds, &setName) != MS::kSuccess) {
                continue;
            }
            TileUVSet entry;
            entry.name = setName.asChar();
            entry.u.assign(&u[0], &u[0] + u.length());
            entry.v.assign(&v[0], &v[0] + v.length());
            entry.counts.resize(uvCounts.length());
            for (unsigned int index = 0u; index < uvCounts.length(); ++index) {
                entry.counts[index] = uvCounts[index];
            }
            entry.ids.resize(uvIds.length());
            for (unsigned int index = 0u; index < uvIds.length(); ++index) {
                entry.ids[index] = uvIds[index];
            }
            uvSets.push_back(std::move(entry));
        }
    }

    std::size_t key = mca::hashTopology(counts, ids);
    mixHash(key, static_cast<std::size_t>(upAxisValue));
    for (const mca::Vec3& point : points) {
        mixHash(key, point.x);
        mixHash(key, point.y);
        mixHash(key, point.z);
    }
    mixHash(key, uvSets.size());
    for (const TileUVSet& set : uvSets) {
        mixHash(key, std::hash<std::string>()(set.name));
        mixHash(key, set.u);
        mixHash(key, set.v);
        mixHash(key, set.counts);
        mixHash(key, set.ids);
    }

    if (key == tileKey_ && !tile_.height.empty()) {
        return MS::kSuccess;
    }

    if (points.empty() || counts.empty()) {
        MGlobal::displayWarning(note("the tileMesh has no geometry."));
        return MS::kFailure;
    }

    const mca::UpAxis upAxis = static_cast<mca::UpAxis>(std::min<short>(2, std::max<short>(0, upAxisValue)));
    tile_ = mca::parameteriseTile(points, upAxis);
    tileCounts_ = counts;
    tileVertexIds_ = ids;
    tileVertexCount_ = static_cast<int>(points.size());
    tileUVs_ = std::move(uvSets);
    tileKey_ = key;
    // The output topology depends on the tile, so force it to be rebuilt.
    topologyKey_ = 0u;
    return MS::kSuccess;
}

MStatus McaMeshTiler::rebuildSubdiv(MDataBlock& data, MObject targetMesh) {
    std::vector<int> counts;
    std::vector<int> ids;
    readTopology(targetMesh, counts, ids);

    // Face rotation turns the tile on a face by relabelling that face's corners.
    // It changes the parameterisation, not the surface.
    MArrayDataHandle rotationHandle = data.inputArrayValue(aFaceRotation);
    if (rotationHandle.elementCount() > 0u) {
        std::size_t offset = 0u;
        std::vector<int> rotations(counts.size(), 0);
        for (unsigned int element = 0u; element < rotationHandle.elementCount(); ++element) {
            if (rotationHandle.jumpToArrayElement(element) != MS::kSuccess) {
                continue;
            }
            const int face = static_cast<int>(rotationHandle.elementIndex());
            if (face >= 0 && face < static_cast<int>(counts.size())) {
                rotations[static_cast<std::size_t>(face)] =
                    rotationHandle.inputValue().asShort();
            }
        }
        for (std::size_t face = 0u; face < counts.size(); ++face) {
            const std::size_t size = static_cast<std::size_t>(counts[face]);
            if (rotations[face] != 0) {
                std::vector<int> faceIds(ids.begin() + offset, ids.begin() + offset + size);
                mca::rotateFaceVertices(faceIds, rotations[face]);
                std::copy(faceIds.begin(), faceIds.end(), ids.begin() + offset);
            }
            offset += size;
        }
    }

    const bool refineNonQuads = data.inputValue(aRefineNonQuads).asBool();
    if (!refineNonQuads && !mca::isAllQuads(counts)) {
        MGlobal::displayWarning(note(
            "the target has " + std::to_string(mca::nonQuadCount(counts)) +
            " faces that are not quads, and refineNonQuads is off. Turn it on, or "
            "quadrangulate the target."));
        return MS::kFailure;
    }

    mca::SharpnessOptions sharpness;
    sharpness.boundary =
        data.inputValue(aBoundaryInterpolation).asShort() == 0 ? mca::BoundaryMode::EdgeOnly
                                                               : mca::BoundaryMode::EdgeAndCorner;
    sharpness.uniformCrease = data.inputValue(aCreaseSharpness).asFloat();
    sharpness.uniformCorner = data.inputValue(aCornerSharpness).asFloat();
    if (data.inputValue(aUseMeshCreases).asBool()) {
        readMeshCreases(targetMesh, sharpness);
    }
    // A uniform crease applies to every edge, which needs the edge list.
    if (sharpness.uniformCrease > 1e-6f && sharpness.creaseWeights.empty()) {
        MFnMesh function(targetMesh);
        const int edgeCount = function.numEdges();
        for (int edge = 0; edge < edgeCount; ++edge) {
            int2 vertices = {0, 0};
            if (function.getEdgeVertices(edge, vertices) == MS::kSuccess) {
                sharpness.creaseVertexPairs.push_back(vertices[0]);
                sharpness.creaseVertexPairs.push_back(vertices[1]);
                sharpness.creaseWeights.push_back(sharpness.uniformCrease);
            }
        }
    }

    // Everything that changes the stencil table goes in the key - not just
    // topology. Counting vertices, edges and faces, which is what the original
    // compared, misses an edge flip entirely.
    std::size_t key = mca::hashTopology(counts, ids);
    mixHash(key, static_cast<std::size_t>(sharpness.boundary));
    mixHash(key, static_cast<double>(sharpness.uniformCrease));
    mixHash(key, static_cast<double>(sharpness.uniformCorner));
    mixHash(key, sharpness.creaseWeights.size());
    for (float weight : sharpness.creaseWeights) {
        mixHash(key, static_cast<double>(weight));
    }
    mixHash(key, sharpness.cornerWeights.size());
    for (float weight : sharpness.cornerWeights) {
        mixHash(key, static_cast<double>(weight));
    }
    mixHash(key, tileKey_);
    // The output topology carries the UV sets, so toggling copyUVs has to
    // rebuild it - otherwise turning it on did nothing until you also nudged
    // the target.
    const bool copyUVs = data.inputValue(aCopyUVs).asBool();
    mixHash(key, static_cast<std::size_t>(copyUVs ? 1u : 0u));
    // The grid changes how many tiles there are, so it changes the stencil
    // table and the output topology both.
    const int tilesU = std::max(1, data.inputValue(aTilesU).asInt());
    const int tilesV = std::max(1, data.inputValue(aTilesV).asInt());
    mixHash(key, static_cast<std::size_t>(tilesU));
    mixHash(key, static_cast<std::size_t>(tilesV));

    if (key == topologyKey_ && subdiv_.valid()) {
        return MS::kSuccess;
    }

    // OpenSubdiv takes its parametric coordinates as float. The narrowing is
    // deliberate and spelled out, rather than left to an implicit conversion
    // inside the vector constructor that the compiler rightly grumbles about.
    std::vector<float> tileS;
    std::vector<float> tileT;
    tileS.reserve(tile_.u.size());
    tileT.reserve(tile_.v.size());
    for (double value : tile_.u) {
        tileS.push_back(static_cast<float>(value));
    }
    for (double value : tile_.v) {
        tileT.push_back(static_cast<float>(value));
    }

    std::string error;
    const int vertexCount = MFnMesh(targetMesh).numVertices();
    if (!subdiv_.build(vertexCount, counts, ids, sharpness, tileS, tileT, tilesU, tilesV,
                       error)) {
        MGlobal::displayWarning(note(error));
        topologyKey_ = 0u;
        return MS::kFailure;
    }

    const int nonQuads = mca::nonQuadCount(counts);
    if (nonQuads > 0 || subdiv_.tilesPerFace() > 1) {
        MGlobal::displayInfo(note(std::to_string(counts.size()) + " faces (" +
                                  std::to_string(nonQuads) + " not quads) produced " +
                                  std::to_string(subdiv_.tileCount()) + " tiles."));
    }

    topologyKey_ = key;
    return rebuildOutputTopology(copyUVs);
}

MStatus McaMeshTiler::rebuildOutputTopology(bool copyUVs) {
    const int tiles = subdiv_.tileCount();
    const int perTileVertices = tileVertexCount_;
    const int perTileFaces = static_cast<int>(tileCounts_.size());

    const unsigned int vertexTotal =
        static_cast<unsigned int>(tiles) * static_cast<unsigned int>(perTileVertices);

    MPointArray points;
    points.setLength(vertexTotal);
    for (unsigned int index = 0u; index < vertexTotal; ++index) {
        points.set(MPoint(0.0, 0.0, 0.0), index);
    }

    MIntArray polygonCounts;
    polygonCounts.setLength(static_cast<unsigned int>(tiles * perTileFaces));
    for (int tile = 0; tile < tiles; ++tile) {
        for (int face = 0; face < perTileFaces; ++face) {
            polygonCounts.set(tileCounts_[static_cast<std::size_t>(face)],
                              static_cast<unsigned int>(tile * perTileFaces + face));
        }
    }

    const int idsPerTile = static_cast<int>(tileVertexIds_.size());
    MIntArray polygonConnects;
    polygonConnects.setLength(static_cast<unsigned int>(tiles * idsPerTile));
    for (int tile = 0; tile < tiles; ++tile) {
        for (int index = 0; index < idsPerTile; ++index) {
            polygonConnects.set(tile * perTileVertices +
                                    tileVertexIds_[static_cast<std::size_t>(index)],
                                static_cast<unsigned int>(tile * idsPerTile + index));
        }
    }

    MStatus status;
    MFnMeshData dataCreator;
    outMeshData_ = dataCreator.create(&status);
    if (!status) {
        return status;
    }

    MFnMesh builder;
    builder.create(static_cast<int>(vertexTotal), tiles * perTileFaces, points, polygonCounts,
                   polygonConnects, outMeshData_, &status);
    if (!status) {
        outMeshData_ = MObject::kNullObj;
        return status;
    }

    outVertexCount_ = vertexTotal;
    if (copyUVs && !tileUVs_.empty()) {
        MStatus uvStatus = copyTileUVs(outMeshData_, tiles);
        if (!uvStatus) {
            // Worth saying out loud rather than shipping unmapped tiles, but
            // not worth failing the whole evaluation over - the geometry is
            // fine and the user can turn copyUVs off.
            MGlobal::displayWarning(note("could not copy the tile's UV sets onto the output."));
        }
    }
    return MS::kSuccess;
}

/// Stamp the tile's UV sets once per tile.
///
/// Each tile is a verbatim copy of the tile mesh, so its UVs are too: the
/// values repeat unchanged and only the indices shift, by one tile's worth of
/// UVs each time. Every tile therefore lands on the same patch of texture,
/// which is the point - one scale texture, ten thousand scales.
MStatus McaMeshTiler::copyTileUVs(MObject outMesh, int tiles) {
    if (tiles <= 0) {
        return MS::kSuccess;
    }

    MStatus status;
    MFnMesh function(outMesh, &status);
    if (!status) {
        return status;
    }

    for (std::size_t set = 0u; set < tileUVs_.size(); ++set) {
        const TileUVSet& tileSet = tileUVs_[set];
        const unsigned int perTile = static_cast<unsigned int>(tileSet.u.size());
        if (perTile == 0u) {
            continue;
        }

        MString setName(tileSet.name.c_str());
        // The output is a mesh DATA object, not a shape in the DAG, and the two
        // take different calls: createUVSet goes through a DG modifier and does
        // nothing here, so a tile's second UV set was silently dropped while the
        // first - which rode in on the default set MFnMesh::create already made
        // - looked like proof the whole thing worked. createUVSetDataMesh is the
        // one for mesh data.
        MStringArray existing;
        function.getUVSetNames(existing);
        bool present = false;
        for (unsigned int index = 0u; index < existing.length(); ++index) {
            if (existing[index] == setName) {
                present = true;
                break;
            }
        }
        if (!present) {
            if (set == 0u && existing.length() == 1u) {
                // Rename the default set rather than leaving an empty "map1"
                // sitting in front of the real one.
                function.renameUVSet(existing[0], setName);
            } else {
                MString requested = setName;
                status = function.createUVSetDataMesh(requested);
                if (!status) {
                    return status;
                }
                // createUVSetDataMesh renames on a clash, so use what it gave us.
                setName = requested;
            }
        }

        MFloatArray u;
        MFloatArray v;
        u.setLength(perTile * static_cast<unsigned int>(tiles));
        v.setLength(perTile * static_cast<unsigned int>(tiles));
        for (int tile = 0; tile < tiles; ++tile) {
            const unsigned int base = static_cast<unsigned int>(tile) * perTile;
            for (unsigned int index = 0u; index < perTile; ++index) {
                u.set(tileSet.u[index], base + index);
                v.set(tileSet.v[index], base + index);
            }
        }
        status = function.setUVs(u, v, &setName);
        if (!status) {
            return status;
        }

        const unsigned int countsPerTile = static_cast<unsigned int>(tileSet.counts.size());
        const unsigned int idsPerTile = static_cast<unsigned int>(tileSet.ids.size());
        MIntArray uvCounts;
        MIntArray uvIds;
        uvCounts.setLength(countsPerTile * static_cast<unsigned int>(tiles));
        uvIds.setLength(idsPerTile * static_cast<unsigned int>(tiles));
        for (int tile = 0; tile < tiles; ++tile) {
            const unsigned int countBase = static_cast<unsigned int>(tile) * countsPerTile;
            for (unsigned int index = 0u; index < countsPerTile; ++index) {
                uvCounts.set(tileSet.counts[index], countBase + index);
            }
            const unsigned int idBase = static_cast<unsigned int>(tile) * idsPerTile;
            const int shift = tile * static_cast<int>(perTile);
            for (unsigned int index = 0u; index < idsPerTile; ++index) {
                uvIds.set(tileSet.ids[index] + shift, idBase + index);
            }
        }
        status = function.assignUVs(uvCounts, uvIds, &setName);
        if (!status) {
            return status;
        }
    }

    return MS::kSuccess;
}
