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

RESULT = os.path.join(tempfile.gettempdir(), 'mcaCageWrap_ui.json')
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

    from mca.mya.tools.cagewrap import cagewrap_ui
    check('the ui module imports', True)
    check('it exposes open_tool, which is what the Toolbox button calls',
          callable(cagewrap_ui.open_tool))
    check('CageWrapUI is there', hasattr(cagewrap_ui, 'CageWrapUI'))

    # Every method a button is wired to must exist, or the window builds and then throws
    # the first time somebody clicks.
    wired = ('_pick_mesh', '_pick_cage', '_build_cage', '_wrap', '_bake', '_report',
             '_remove', '_resolve_mesh', '_frames', '_handle', '_say', '_check_plugin',
             '_is_mesh', '_meshes_in')
    absent = [name for name in wired if not hasattr(cagewrap_ui.CageWrapUI, name)]
    check('every method a button is connected to exists', not absent,
          'missing {}'.format(absent))

    from mca.mya.tools.cagewrap import cagewrap_api
    # The window fills a spin box from this, so a rename would leave it at zero with no
    # error anywhere.
    check('the face-count default the window reads still exists',
          isinstance(getattr(cagewrap_api, 'DEFAULT_CAGE_FACES', None), int))
    check('and the offset default', isinstance(getattr(cagewrap_api, 'DEFAULT_OFFSET', None),
                                               float))

    # Everything the window calls on the API, by name.
    called = ('cage_from_mesh', 'wrap', 'report', 'remove', 'find_wraps', 'bake_to_skin',
              'border_edges', 'plugin_is_available')
    missing = [name for name in called if not callable(getattr(cagewrap_api, name, None))]
    check('every API function the window calls exists', not missing,
          'missing {}'.format(missing))

    # Each public call answers in the same shape whether it worked or not, so the window
    # can show one sentence either way.
    import maya.cmds as cmds
    cmds.file(new=True, force=True)
    refused = cagewrap_api.wrap('no_such_mesh')
    check('a bad call still answers with the ok/result/message contract',
          isinstance(refused, dict) and set(refused) == {'ok', 'result', 'message'}
          and refused['ok'] is False and refused['message'],
          str(refused))

    check('the plug-in is where the loader expects it',
          cagewrap_api.plugin_is_available()[0], cagewrap_api.plugin_is_available()[1])

    # The Toolbox button resolves its target through this, so run the same check.
    from mca.common.tools.toolbox import toolbox_runner, toolbox_model
    command = {'kind': toolbox_model.COMMAND_CALLABLE,
               'target': 'mca.mya.tools.cagewrap.cagewrap_ui:open_tool'}
    problems = toolbox_runner.check_command(command)
    out['command_problems'] = problems
    check('the Toolbox command resolves', not problems, str(problems))

    out['ok'] = not out['failures']

except Exception:
    out['error'] = traceback.format_exc()[-3000:]
    out['ok'] = False

out['passed'] = len(out['checks']) - len(out['failures'])
out['total'] = len(out['checks'])
with open(RESULT, 'w') as handle:
    json.dump(out, handle, indent=1, default=str)

print('{}/{} passed'.format(out['passed'], out['total']))
for _failure in out['failures']:
    print('  FAILED  {}'.format(_failure))
if out.get('error'):
    print(out['error'])
print('  details: {}'.format(RESULT))
