# mcaPhysicsChain tests

| file | needs | covers |
|---|---|---|
| `test_solver.cpp` | cl.exe, **no Maya** | the integrator and damping maths, off-DCC |
| `test_node.py` | mayapy **or** an open Maya | 36 — the node driven as an actual chain: drag, springiness, gravity, stretch, limit angle, aim/up axes, solve and update modes |
| `test_layer.py` | an open Maya with a rig loaded | 16 — `physicschain_api` against a real FRAG rig: constraint offsets, weight 0 being exact, baking to zero error, and removal leaving the rig as it was found |

## Running them

```
run_python_tests.bat 2025
```

`test_layer.py` needs a rig in the scene, so it is meant to be run from inside
Maya rather than by the batch runner.

Results go to `%TEMP%` and a summary is printed.

## Two things these suites learned the hard way

**Set `advanced` when tuning with stiffness/damping/gravity.** Those three are
ignored unless it is on. The suite spent a while quietly testing default settings
while appearing to test specific ones, and five checks failed for reasons that
had nothing to do with the node.

**An assertion can pass on an artefact.** The original "lag grows strictly down
the chain" check was written to catch a chain sliding as a rigid body. It did —
but the gradient it measured came from the chain *squashing* by a third. Once
segment lengths were held, the same physically-correct chain saturated instead
and the check failed. Both behaviours are right; the assertion has to say which
mode it is talking about.
