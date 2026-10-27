// MCA-DCC Pipeline
// Copyright (c) 2026 Nathan Comes. MIT licensed.
//
// One parallel-for, shared by every plug-in in this tree, on plain CRT threads.
//
// **Deliberately not OpenMP.** `#pragma omp parallel for` on MSVC pulls
// VCOMP140.DLL into whatever process loads the plug-in, and Maya runs its own
// thread pool on TBB. The devkit call that used to reconcile the two,
// `MThreadUtils::syncNumOpenMPThreads()`, is a no-op in every Maya this tree builds
// for, and the compiler says so to your face on every build:
//
//     warning C4996: 'MThreadUtils::syncNumOpenMPThreads': Does nothing.
//     Present for backward-compatibility purposes only.
//
// That warning sat in the build log, in four copies, while the call was being
// credited with fixing an access violation in mcaPoseSkinner. It was not. Threads
// started here are the CRT's own and there is no second parallel runtime in the
// process to disagree with Maya's.
//
// Header-only and inline, because it is three dozen lines and every plug-in that
// wants it already has `../common/include` on its include path.

#ifndef MCA_PARALLEL_H
#define MCA_PARALLEL_H

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <exception>
#include <functional>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace mca {

/// The automatic thread count, when a caller asks for 0.
///
/// There is an open race in mcaPoseSkinner's weight solve. It is not an
/// out-of-range index - a bounds-checked build runs clean - and it is not the
/// OpenMP runtime, which is gone. It faults during an allocation on a worker
/// thread, and it needs a lot of threads. Measured off-DCC at full face scale
/// (5,400 vertices, 173 poses, 81 joints, six runs each, 28-core machine):
///
///     threads   runs crashed   fastest solve
///        1          0/6           14.9 s
///        8          0/6            2.1 s
///       16          0/6            1.4 s
///       24        2 of 8 seen        -
///       28          1/6              -
///
/// The cap costs 0.7 seconds on a whole face and excludes every thread count at
/// which a fault has ever been observed. **It is risk reduction, not a cure** - six
/// clean runs do not prove a race absent. See `claude/pose-skinner-crash-open.md`;
/// whoever finds the cause should take this out.
const unsigned int kSafeThreads = 8;

/// Run `body(index)` for every index in [0, count).
///
/// `threads` of 1 runs everything on the calling thread and starts nothing, which
/// is what makes a one-thread-against-all determinism check mean something. 0 asks
/// the hardware and then applies `kSafeThreads`. Any other number is used exactly
/// as given, cap or no cap, so a reproduction harness can still ask for 24 - a tool
/// that quietly ignores what it was told is worse than one with a documented limit.
///
/// Work is handed out one index at a time, so an uneven per-index cost does not
/// leave threads idle waiting for the slowest chunk.
///
/// **An exception thrown out of an OpenMP region is undefined behaviour**, which is
/// why loop bodies here used to catch into a shared `std::string` - itself a race.
/// This catches per thread into its own slot and reports the failure with the
/// LOWEST index, so the message does not depend on which thread lost.
///
/// :param problem: set to the first failure's text, left alone when there is none.
///     Never written from more than one thread.
inline void parallelFor(int count, int threads, const std::function<void(int)>& body,
                        std::string* problem) {
    if (count <= 0 || !body) {
        return;
    }

    unsigned int wanted = 0;
    if (threads > 0) {
        wanted = static_cast<unsigned int>(threads);
    } else {
        wanted = std::thread::hardware_concurrency();
        if (wanted == 0) {
            wanted = 1;
        }
        wanted = std::min(wanted, kSafeThreads);
    }
    wanted = std::min<unsigned int>(wanted, static_cast<unsigned int>(count));

    if (wanted <= 1) {
        for (int index = 0; index < count; ++index) {
            try {
                body(index);
            } catch (const std::exception& trouble) {
                if (problem && problem->empty()) {
                    *problem = trouble.what();
                }
                return;
            } catch (...) {
                if (problem && problem->empty()) {
                    *problem = "an unknown error";
                }
                return;
            }
        }
        return;
    }

    std::atomic<int> next(0);
    std::vector<std::pair<int, std::string> > failures(
        static_cast<std::size_t>(wanted), std::pair<int, std::string>(-1, std::string()));

    // Each worker touches only its own slot, so nothing here is shared but `next`.
    struct Worker {
        static void run(std::atomic<int>* next, int count,
                        const std::function<void(int)>* body,
                        std::pair<int, std::string>* mine) {
            for (;;) {
                const int index = next->fetch_add(1);
                if (index >= count) {
                    return;
                }
                try {
                    (*body)(index);
                } catch (const std::exception& trouble) {
                    if (mine->first < 0) {
                        mine->first = index;
                        mine->second = trouble.what();
                    }
                } catch (...) {
                    if (mine->first < 0) {
                        mine->first = index;
                        mine->second = "an unknown error";
                    }
                }
            }
        }
    };

    std::vector<std::thread> pool;
    pool.reserve(static_cast<std::size_t>(wanted - 1));
    for (unsigned int slot = 1; slot < wanted; ++slot) {
        pool.push_back(std::thread(Worker::run, &next, count, &body,
                                   &failures[static_cast<std::size_t>(slot)]));
    }
    // The calling thread takes a share rather than sitting and waiting.
    Worker::run(&next, count, &body, &failures[0]);
    for (std::size_t index = 0; index < pool.size(); ++index) {
        pool[index].join();
    }

    if (!problem || !problem->empty()) {
        return;
    }
    int lowest = -1;
    const std::string* text = 0;
    for (std::size_t slot = 0; slot < failures.size(); ++slot) {
        if (failures[slot].first < 0) {
            continue;
        }
        if (lowest < 0 || failures[slot].first < lowest) {
            lowest = failures[slot].first;
            text = &failures[slot].second;
        }
    }
    if (text) {
        *problem = *text;
    }
}

}  // namespace mca

#endif  // MCA_PARALLEL_H
