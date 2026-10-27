"""Check the RBF window's settings table against the node it claims to drive.

Every widget in the Mesh Tiler's top half is mapped to a node attribute by name.
A typo there fails at runtime, silently in the worst case - so the names are
lifted straight out of the source and checked against a real node. This runs
under any Maya the plug-in is built for, and deliberately does NOT import the UI
module, so it does not need pymel.
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
import json, os, re, sys, traceback


UI = _os.path.join(PACKAGES, 'mca-maya', 'mca', 'mya', 'tools', 'rbfsolver',
                   'rbfsolver_ui.py')
RESULT = _result_path('mcaRBFSolver_ui_attributes.json')

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
    mll = _plugin_binary(version)
    cmds.loadPlugin(mll)
    out['version'] = version

    source = open(UI, encoding='utf-8').read()
    block = re.search(r'def _settings\(self\):.*?return \((.*?)\)\n', source, re.S)
    check('the settings table is where it is expected to be', bool(block))
    pairs = re.findall(r'\(self\.(\w+),\s*\'(\w+)\'\)', block.group(1)) if block else []
    out['pairs'] = pairs
    # A threshold, not a count: the point is to catch the table being emptied or
    # the regex failing to match, not to pin how many settings this window has.
    # The first version asserted >= 10, copied from a window with eleven.
    check('it has entries', len(pairs) >= 4, '{} found'.format(len(pairs)))

    # Every widget named in the table must actually be built by _build_ui.
    missing_widgets = [name for name, _ in pairs
                       if 'self.{} ='.format(name) not in source]
    check('every widget in the table is one the window builds', not missing_widgets,
          'missing {}'.format(missing_widgets))

    node = cmds.createNode('mcaRBFSolver')
    missing_attrs, unsettable = [], []
    for widget, attribute in pairs:
        plug = '{}.{}'.format(node, attribute)
        if not cmds.objExists(plug):
            missing_attrs.append(attribute)
            continue
        # Round trip it, the way _push and _pull do.
        try:
            before = cmds.getAttr(plug)
            cmds.setAttr(plug, before)
        except Exception as exc:
            unsettable.append('{}: {}'.format(attribute, exc))
    check('every attribute in the table exists on the node', not missing_attrs,
          'missing {}'.format(missing_attrs))
    check('and every one can be read and written', not unsettable, str(unsettable))

    # The grid in particular has to survive the round trip the window does.
    cmds.setAttr(node + '.scale', 2.5)
    check('a setting reads back what was written',
          abs(cmds.getAttr(node + '.scale') - 2.5) < 1e-9)

    # Anything the window drives must affect the output, or changing it does
    # nothing visible and the tool looks broken.
    affected = set(cmds.listConnections(node + '.outMesh', source=True) or [])
    inputs = cmds.listAttr(node, settable=True) or []
    not_driving = [a for _, a in pairs if a not in inputs]
    check('every attribute in the table is a settable input', not not_driving,
          str(not_driving))

    out['ok'] = not out['failures']
except Exception:
    out['error'] = traceback.format_exc()[-2500:]
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
