"""Import the Pose Skinner UI under mayapy without building any widgets.

Constructing a QApplication under mayapy hard-crashes: Maya's standalone init
loads Qt WebEngine, which wants an OpenGL context the offscreen platform cannot
give it. So this stops short of widgets and checks everything that does not need
one - which is most of what goes wrong on a first run: a button wired to a method
that does not exist, a default the window reads from the API that has been
renamed, a Toolbox target that does not resolve.

**The window has never been drawn under test.** Its layout is verified by a person
looking at it. Worth saying rather than implying.
"""

import json
import os
import sys
import tempfile
import traceback

#: <package root>/mca-maya/mca/mya/plugins/<plugin>
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_NAME = os.path.basename(PLUGIN_ROOT)
#: The `packages` folder five levels up.
PACKAGES = os.path.abspath(os.path.join(PLUGIN_ROOT, *([os.pardir] * 5)))

RESULT = os.path.join(tempfile.gettempdir(), 'mcaPoseSkinner_ui.json')
out = {'checks': [], 'failures': []}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))


try:
    import maya.standalone
    maya.standalone.initialize(name='python')
    import maya.cmds as cmds

    version = cmds.about(version=True).split()[0]
    for package in ('mca-common', 'mca-maya'):
        sys.path.insert(0, os.path.join(PACKAGES, package))
    # Appended, never inserted: the python311 bundle carries a PySide6 that does not
    # import under mayapy, and pygui swallows the ImportError and hands back a stub.
    for bundle in (os.path.join(PACKAGES, 'mca-maya', 'mca', 'mya', 'startup',
                                'dependencies', version),
                   os.path.join(PACKAGES, 'mca-common', 'mca', 'common', 'startup',
                                'dependencies', 'python{}{}'.format(*sys.version_info[:2])),
                   os.path.join(PACKAGES, 'dependancies')):
        if os.path.isdir(bundle):
            sys.path.append(bundle)

    from mca.mya.tools.poseskinner import poseskinner_ui
    check('the ui module imports', True)
    check('it exposes open_tool, which is what the Toolbox button calls',
          callable(poseskinner_ui.open_tool))
    check('PoseSkinnerUI is there', hasattr(poseskinner_ui, 'PoseSkinnerUI'))

    # Every method a button is wired to must exist, or the window builds and then
    # throws the first time somebody clicks.
    wired = ('_pick_mesh', '_pick_joints', '_lay_out', '_solve', '_auto_joints',
             '_report', '_correctives', '_clear_colours', '_show_numbers', '_frames',
             '_holdout_frames', '_duplicate_choice', '_handle', '_say', '_check_plugin')
    absent = [name for name in wired if not hasattr(poseskinner_ui.PoseSkinnerUI, name)]
    check('every method a button is connected to exists', not absent,
          'missing {}'.format(absent))

    # The window fills a spin box from this, so a rename would leave it at zero with
    # no error anywhere.
    from mca.mya.tools.poseskinner import poseskinner_api
    check('the API still has the default the window reads',
          isinstance(poseskinner_api.DEFAULT_MAX_INFLUENCES, int) and
          poseskinner_api.DEFAULT_MAX_INFLUENCES >= 1,
          str(poseskinner_api.DEFAULT_MAX_INFLUENCES))
    check('and the locality default the tooltip quotes',
          poseskinner_api.DEFAULT_LOCALITY_MULTIPLE >= 1,
          str(poseskinner_api.DEFAULT_LOCALITY_MULTIPLE))

    # Every function the window and the MCP tools call, by name. A rename in the API
    # is otherwise found by an artist.
    functions = ('solve', 'skin_from_poses', 'auto_joints', 'poses_from_blendshape',
                 'influence_report', 'show_error', 'clear_error_colours',
                 'add_correctives', 'remove_solved_skin', 'plugin_is_available',
                 'existing_skin', 'clean_copy', 'other_deformers')
    missing = [name for name in functions if not callable(getattr(poseskinner_api, name, None))]
    check('every API function the UI and the MCP tools name exists', not missing,
          'missing {}'.format(missing))

    # The plug-in has to be built for the Maya running this, or nothing works and the
    # reason is a missing file rather than a bug.
    binary = os.path.join(PLUGIN_ROOT, 'plug-in', str(version), 'Release',
                          '{}_maya{}.mll'.format(PLUGIN_NAME, version))
    out['binary'] = binary
    check('the plug-in is built for this Maya', os.path.isfile(binary), binary)

    check('and it loads', poseskinner_api.plugin_is_available()[0],
          poseskinner_api.plugin_is_available()[1])

    # The Toolbox button resolves its target through this, so run the same check.
    from mca.common.tools.toolbox import toolbox_runner, toolbox_model
    command = {'kind': toolbox_model.COMMAND_CALLABLE,
               'target': 'mca.mya.tools.poseskinner.poseskinner_ui:open_tool'}
    problems = toolbox_runner.check_command(command)
    out['command_problems'] = problems
    check('the Toolbox button target resolves', not problems, str(problems))

    out['ok'] = not out['failures']
except Exception:
    out['error'] = traceback.format_exc()[-3000:]
    out['ok'] = False

out['passed'] = len(out['checks']) - len(out['failures'])
out['total'] = len(out['checks'])
with open(RESULT, 'w') as handle:
    json.dump(out, handle, indent=1)

print('{}/{} passed'.format(out['passed'], out['total']))
for _failure in out['failures']:
    print('  FAILED  {}'.format(_failure))
if out.get('error'):
    print(out['error'])
print('  details: {}'.format(RESULT))
