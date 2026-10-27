// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// The registered Maya node id block, and who has which id.
//
// Registered with the Autodesk Developer Network to Mechanical Art Studios:
//
//     0x00142C00 - 0x00142C3F   (64 ids)
//
// Every node type Maya loads carries an id, and it is written into every scene
// file that uses that node. Two plug-ins sharing an id is not a warning, it is
// one of them failing to load in a scene that contains the other - so these are
// allocated from one table rather than picked per file.
//
// This header is shared by every plug-in in this tree and should be the only
// place in the codebase where a raw node id appears. It lives in
// plugins/common/include so that no plug-in has to include another plug-in's
// headers to find it.

#ifndef MCA_NODE_IDS_H
#define MCA_NODE_IDS_H

#include <maya/MTypeId.h>

namespace mca {

/// First id of the registered block.
constexpr unsigned int kNodeIdBlockStart = 0x00142C00u;

/// Last id of the registered block, inclusive.
constexpr unsigned int kNodeIdBlockEnd = 0x00142C3Fu;

constexpr unsigned int kNodeIdBlockSize = kNodeIdBlockEnd - kNodeIdBlockStart + 1u;

/// Who has which id.
///
/// Rules, and they matter more than they look:
///
/// * **Append only.** Once a node has shipped, its index is written into user
///   scenes forever. Renumbering it orphans those nodes on load.
/// * **Never reuse a retired index.** If a node is removed, leave its entry
///   here marked retired. An old scene still refers to it, and handing that id
///   to a different node type is worse than leaving it dead.
/// * **One entry per registered type.** Manipulator nodes are node types and
///   need their own. Commands and contexts register by name and do not.
enum NodeIdIndex : unsigned int {
    /// The physics chain solver.
    kPhysicsChainNode = 0u,        // 0x00142C00
    /// Its interactive cone-limit manipulator.
    kPhysicsChainLimitManip = 1u,  // 0x00142C01

    /// Tiles a mesh across the limit surface of another. Replaces the
    /// third-party cloneToQuad, which sat at 0x0077CBBC - outside any block
    /// allocated to us.
    kMeshTilerNode = 2u,           // 0x00142C02

    /// Interpolates an N-dimensional key to an M-dimensional value through a
    /// radial basis function. Replaces the third-party rbfSolver, which sat at
    /// 0x0B8D357 - outside any block allocated to us - and was Python 2, so it
    /// has not loaded in any Maya since 2022.
    kRBFSolverNode = 3u,           // 0x00142C03

    /// Deforms a mesh by a cage wrapped around it, through Green coordinates.
    /// Replaces the third-party greenDeformer, which sat at 0xCED2528 - outside any
    /// block allocated to us - and built for 2025 only.
    kCageWrapNode = 4u,            // 0x00142C04

    /// Not yet allocated. Take the next free index and add it above this line.
    kNextFreeNodeId = 5u
};

/// The Maya id for an allocated index.
inline MTypeId nodeId(unsigned int index) {
    return MTypeId(kNodeIdBlockStart + index);
}

static_assert(kNodeIdBlockSize == 64u, "The registered block is 64 ids.");
static_assert(kNextFreeNodeId <= kNodeIdBlockSize,
              "Out of registered node ids - request another block from ADN rather than "
              "borrowing an id from outside the block.");

}  // namespace mca

#endif  // MCA_NODE_IDS_H
