"""Import the RBF Retargeter window headlessly and check its wiring.

No QApplication: one cannot be made under mayapy without a hard crash, so the
window is never drawn here. What this catches is the failure that actually
happens - a button connected to a method that was renamed or never written, an
import that only resolves inside a full Maya, a Toolbox target that does not
resolve. Those are silent until somebody opens the tool.
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


RESULT = _result_path('mcaRBFRetargeter_ui_import.json')

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

    from mca.mya.tools.rbfretargeter import rbfretargeter_ui
    check('the ui module imports', True)
    check('it exposes open_tool, which is what the Toolbox button calls',
          callable(rbfretargeter_ui.open_tool))
    check('RBFRetargeterUI is there', hasattr(rbfretargeter_ui, 'RBFRetargeterUI'))

    # Every method the buttons are wired to must exist, or the window builds and
    # then throws the first time somebody clicks.
    wired = ('_build_ui', '_note', '_say', '_handle', '_check_plugin',
             '_selected_meshes', '_vertex_count', '_rows', '_take_from', '_add_to',
             '_add_shapes', '_add_rows', '_remove_rows', '_swap',
             '_shapes_from_blendshape', '_take_vertices', '_reselect_vertices',
             '_clear_vertices', '_auto_pick', '_refresh_counts', '_update_cost',
             '_retarget')
    absent = [name for name in wired
              if not hasattr(rbfretargeter_ui.RBFRetargeterUI, name)]
    check('every method a button is connected to exists', not absent,
          'missing {}'.format(absent))

    # The window reads its limit from the api rather than carrying its own copy,
    # so the number in the spin box and the number the command enforces cannot
    # drift apart.
    from mca.mya.tools.rbfretargeter import rbfretargeter_api
    check('the window and the api agree on the solver point limit',
          'rbfretargeter_api.DEFAULT_MAX_SOLVER_POINTS' in
          open(_os.path.join(PACKAGES, 'mca-maya', 'mca', 'mya', 'tools',
                             'rbfretargeter', 'rbfretargeter_ui.py'),
               encoding='utf-8').read())
    check('the limit is a sane number',
          rbfretargeter_api.DEFAULT_MAX_SOLVER_POINTS > 0,
          str(rbfretargeter_api.DEFAULT_MAX_SOLVER_POINTS))

    # The rename is the whole fix for "I always get them wrong", so the old words
    # must be gone from the labels - not merely joined by new ones.
    ui_source = open(_os.path.join(PACKAGES, 'mca-maya', 'mca', 'mya', 'tools',
                                   'rbfretargeter', 'rbfretargeter_ui.py'),
                     encoding='utf-8').read()
    import re as _re
    labels = _re.findall(r"QLabel\('([^']+)'\)", ui_source)
    labels += _re.findall(r"QGroupBox\('([^']+)'\)", ui_source)
    out['labels'] = labels
    check('the window says "Deform from" and "Deform to"',
          'Deform from' in labels and 'Deform to' in labels, str(labels))
    check('and no label still says Source or Target',
          not any(word in label for label in labels for word in ('Source', 'Target')),
          str([l for l in labels if 'Source' in l or 'Target' in l]))

    # retarget_to_many is what the multi-target list calls.
    check('the api has the many-targets entry point',
          hasattr(rbfretargeter_api, 'retarget_to_many'))
    check('and the auto-pick the window offers',
          hasattr(rbfretargeter_api, 'suggest_solver_vertices'))

    # The over-limit message must point at the button that fixes it, not at work
    # the user has to invent. That was the whole complaint.
    # The button's exact wording, so the over-limit message and the button it
    # names cannot drift apart - which they did the moment the button was
    # renamed, and the only thing that noticed was this check.
    import re as _re2
    buttons = _re2.findall(r"QPushButton\('([^']+)'\)", ui_source)
    auto = [name for name in buttons if name.startswith('Auto-pick')]
    out['auto_button'] = auto
    check('there is exactly one auto-pick button', len(auto) == 1, str(buttons))
    # Adjacent string literals are joined first: a message long enough to wrap
    # has the button's name split across two source lines, and a per-line search
    # would never find it.
    joined = _re2.sub(r"'\s*\n\s*'", '', ui_source)
    mentions = _re2.findall(r'[Pp]ress (Auto-pick[^.]*)\.', joined)
    out['auto_mentions'] = mentions
    # startswith, not equals: a message may carry on past the button's name
    # ("...press Auto-pick Solver Vertices to choose a set off Female_Average1").
    # The point is that the name it gives is the name on the button.
    check('and every message telling you to press it uses the button\'s real name',
          bool(auto) and bool(mentions) and
          all(m.strip().startswith(auto[0]) for m in mentions),
          'button is {!r}, messages say {!r}'.format(auto, mentions))

    # The Toolbox button resolves its target through this, so run the same check.
    from mca.common.tools.toolbox import toolbox_runner, toolbox_model
    # A command is a plain dict, not a class - the toolbox stores it as YAML.
    command = {'kind': toolbox_model.COMMAND_CALLABLE,
               'target': 'mca.mya.tools.rbfretargeter.rbfretargeter_ui:open_tool'}
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
