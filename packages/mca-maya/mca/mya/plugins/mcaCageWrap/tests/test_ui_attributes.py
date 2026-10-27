"""Check the Attribute Editor template against the node it claims to drive.

The template is MEL built in a C++ string, which means a typo in an attribute name is
not a compile error, not a runtime error, and not visible unless somebody opens the
Attribute Editor and notices a missing row. So the names are lifted straight out of the
source and checked against a real node - and the reverse too: an attribute the node has
and the template neither shows nor suppresses is one an artist will never find.
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


import json, re, traceback

import maya.standalone as _standalone  # noqa: E402
_standalone.initialize(name='python')
import maya.cmds as _cmds  # noqa: E402
_VERSION = _cmds.about(version=True).split()[0]
MLL = _plugin_binary(_VERSION)
RESULT = _result_path('mcaCageWrap_ui_attributes.json')

out = {'checks': [], 'failures': []}


def check(label, condition, detail=''):
    out['checks'].append(label)
    if not condition:
        out['failures'].append('{}  |  {}'.format(label, detail))
    print('{}  {}'.format('ok  ' if condition else 'FAIL', label))


try:
    import maya.cmds as cmds
    _add_framework_paths(_VERSION)
    cmds.loadPlugin(MLL)

    source = _os.path.join(PLUGIN_ROOT, 'source', 'mca_cage_wrap_node.cpp')
    with open(source, 'r', encoding='utf-8') as handle:
        text = handle.read()

    shown = re.findall(r'addControl \\"(\w+)\\"', text)
    suppressed = re.findall(r'suppress \\"(\w+)\\"', text)
    out['shown'] = shown
    out['suppressed'] = suppressed
    check('the template names some attributes', len(shown) >= 5, str(shown))

    mesh = cmds.polySphere(constructionHistory=False)[0]
    node = cmds.deformer(mesh, type='mcaCageWrap')[0]

    absent = [name for name in shown + suppressed
              if not cmds.attributeQuery(name, node=node, exists=True)]
    check('every attribute the template mentions exists on the node', not absent,
          'missing {}'.format(absent))

    # And the other way round. Anything the node adds and the template neither shows nor
    # suppresses is invisible to an artist - which for an output like pointsRebound means
    # the number it measured is only reachable from a script.
    ours = [name for name in (cmds.listAttr(node, userDefined=True) or [])]
    out['user_defined'] = ours
    unmentioned = [name for name in ours if name not in shown and name not in suppressed]
    check('every attribute the node adds is either shown or deliberately suppressed',
          not unmentioned, 'neither: {}'.format(unmentioned))

    # The window reads these by name through the API, so a rename would strand it.
    from mca.mya.tools.cagewrap import cagewrap_api
    reported = cagewrap_api.report(node)
    check('the API can report on a fresh node', reported['ok'], reported['message'])
    if reported['ok']:
        for key in ('worst_rest_error', 'points_outside', 'points_rebound', 'weights_kept',
                    'megabytes', 'stretch', 'envelope'):
            check('the report carries {}'.format(key), key in reported['result'],
                  str(sorted(reported['result'])))

    # Paintable weights have to be registered, or the paint tool simply does not list the
    # deformer and nobody can tell why.
    paintable = cmds.pluginInfo(_os.path.basename(MLL), query=True, dependNode=True) or []
    check('the node type is registered', 'mcaCageWrap' in paintable, str(paintable))
    check('its weights are paintable',
          bool(cmds.attributeQuery('weightList', node=node, exists=True)))

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
