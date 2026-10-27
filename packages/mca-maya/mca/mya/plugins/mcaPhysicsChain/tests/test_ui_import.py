"""Import the Physics Chain UI under mayapy without building any widgets.

Constructing a QApplication under mayapy hard-crashes: Maya's standalone init
loads Qt WebEngine, which wants an OpenGL context the offscreen platform cannot
give it. So this stops short of widgets and checks everything that does not need
one - which is most of what goes wrong on a first run.
"""

# --- where things are, worked out from this file ----------------------------- #
#
# Everything below is derived rather than hardcoded. These suites used to carry
# absolute paths into a scratch folder, which meant they only ran on one machine
# from one place.
import os as _os
import sys as _sys
import tempfile as _tempfile

#: <package root>/mca-maya/mca/mya/plugins/<plugin>
PLUGIN_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
PLUGIN_NAME = _os.path.basename(PLUGIN_ROOT)
#: The `packages` folder six levels up: tests -> plugin -> plugins -> mya -> mca
#: -> mca-maya -> packages.
PACKAGES = _os.path.abspath(_os.path.join(PLUGIN_ROOT, *([_os.pardir] * 5)))


def _plugin_binary(version):
    """:return: This plugin's .mll for a Maya version."""
    return _os.path.join(PLUGIN_ROOT, 'plug-in', str(version), 'Release',
                         '{}_maya{}.mll'.format(PLUGIN_NAME, version))


def _result_path(name):
    """Results go to the temp folder, not into the repo next to the suite."""
    return _os.path.join(_tempfile.gettempdir(), name)


def _add_framework_paths(version):
    """Put the framework and its bundled dependencies on sys.path.

    The bundles are APPENDED, never inserted: the python311 bundle carries its
    own PySide6 that does not import under mayapy, and `mca.common.pyqt.pygui`
    swallows the ImportError and hands back a stub - so putting it in front turns
    every Qt call into an AttributeError several frames from the cause.
    """
    for package in ('mca-common', 'mca-maya'):
        path = _os.path.join(PACKAGES, package)
        if path not in _sys.path:
            _sys.path.insert(0, path)
    for bundle in (_os.path.join(PACKAGES, 'mca-maya', 'mca', 'mya', 'startup',
                                 'dependencies', str(version)),
                   _os.path.join(PACKAGES, 'mca-common', 'mca', 'common', 'startup',
                                 'dependencies',
                                 'python{}{}'.format(*_sys.version_info[:2])),
                   _os.path.join(PACKAGES, 'dependancies')):
        if _os.path.isdir(bundle) and bundle not in _sys.path:
            _sys.path.append(bundle)
import json, os, sys, traceback


RESULT = _result_path('mcaPhysicsChain_ui_import.json')

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
    # Appended, never inserted - see uitest.py.
    for bundle in (os.path.join(PACKAGES, 'mca-maya', 'mca', 'mya', 'startup',
                                'dependencies', version),
                   os.path.join(PACKAGES, 'mca-common', 'mca', 'common', 'startup',
                                'dependencies', 'python{}{}'.format(*sys.version_info[:2])),
                   os.path.join(PACKAGES, 'dependancies')):
        if os.path.isdir(bundle):
            sys.path.append(bundle)

    from mca.mya.tools.physicschain import physicschain_ui
    check('the ui module imports', True)
    check('it exposes open_tool, which is what the Toolbox button calls',
          callable(physicschain_ui.open_tool))
    check('PhysicsChainUI is there', hasattr(physicschain_ui, 'PhysicsChainUI'))

    # Every method the buttons are wired to must exist, or the window builds and
    # then throws the first time somebody clicks.
    wired = ('_add', '_refresh', '_chain_chosen', '_select_flag', '_set_weight',
             '_apply_preset', '_bake', '_remove', '_current', '_handle', '_say',
             '_check_plugin')
    absent = [name for name in wired if not hasattr(physicschain_ui.PhysicsChainUI, name)]
    check('every method a button is connected to exists', not absent,
          'missing {}'.format(absent))

    # Presets are what the window's two dropdowns are filled from, so an empty
    # or renamed table would leave them blank with no error anywhere.
    from mca.mya.tools.physicschain import physicschain_api
    check('the preset table has entries', len(physicschain_api.PRESETS) >= 4,
          str(sorted(physicschain_api.PRESETS)))
    check('the default preset is one of them',
          physicschain_api.DEFAULT_PRESET in physicschain_api.PRESETS,
          physicschain_api.DEFAULT_PRESET)
    out['presets'] = sorted(physicschain_api.PRESETS)

    # The Toolbox button resolves its target through this, so run the same check.
    from mca.common.tools.toolbox import toolbox_runner, toolbox_model
    # A command is a plain dict, not a class - the toolbox stores it as YAML.
    command = {'kind': toolbox_model.COMMAND_CALLABLE,
               'target': 'mca.mya.tools.physicschain.physicschain_ui:open_tool'}
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

# Say it out loud as well as writing the file. A suite whose result you have to
# go and find is a suite nobody checks.
print('{}/{} passed'.format(out['passed'], out['total']))
for _failure in out['failures']:
    print('  FAILED  {}'.format(_failure))
if out.get('error'):
    print(out['error'])
print('  details: {}'.format(RESULT))
