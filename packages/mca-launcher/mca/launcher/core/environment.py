"""
Building the environment a DCC is started with.

A pure function over plain data: preferences in, a dictionary out. Nothing here starts a
process, so what the DCC will be handed can be checked by a test rather than by opening Maya
and reading a log.

Three things it gets right that the old launcher did not:

- **Nothing is set to None.** ``script_path['MCA_ART_PATH'] = os.getenv('MCA_ART_PATH')``
  raised a TypeError when the variable was not set, and setting a variable to an empty
  string is its own trap - the framework then believes there *is* an art path and joins
  onto it.
- **PYTHONPATH is added to, not replaced.** It used to be assigned outright, throwing away
  anything the machine already had on it.
- **The dependency folder comes from the dependency system**, not from a path assembled out
  of the framework folder and a guess about which Python the DCC uses.
"""

# python imports
import logging
import os

# mca imports
from mca.launcher.core import dependencies


logger = logging.getLogger('mca-launcher')

#: Inherited Qt variables that break a DCC's own Qt. Both Maya and MotionBuilder pick these
#: up from whatever launched them, and a PySide6 application - which this launcher is -
#: leaves them pointing at its own plug-ins.
QT_VARIABLES_TO_DROP = ('QT_PLUGIN_PATH', 'QML2_IMPORT_PATH', 'QML_IMPORT_PATH',
                        'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_API', '__COMPAT_LAYER')

#: How each DCC wants its bootstrap folder handed over. Maya reads PYTHONPATH and runs
#: userSetup.py; MotionBuilder the same; Unreal has its own variable and runs init_unreal.py.
PATH_VARIABLE = {'maya': 'PYTHONPATH', 'mobu': 'PYTHONPATH', 'unreal': 'UE_PYTHONPATH'}


def startup_folder(framework_path, dcc_name):
    """
    Where the DCC's bootstrap scripts live inside mca-common.

    :param str framework_path: The packages folder.
    :param str dcc_name: The DCC name.
    :return: The folder, whether or not it exists.
    :rtype: str
    """

    folder = {'maya': 'maya', 'mobu': 'mobu', 'unreal': 'unreal'}.get(dcc_name, dcc_name)
    return os.path.normpath(os.path.join(framework_path, 'mca-common', 'mca', 'common',
                                         'startup', 'dccs', folder, 'Scripts'))


def common_path(framework_path):
    """
    :param str framework_path: The packages folder.
    :return: The mca-common package folder the framework calls MCA_COMMON_PATH.
    :rtype: str
    """

    return os.path.normpath(os.path.join(framework_path, 'mca-common', 'mca', 'common'))


def build(project_prefs, dcc_name, key, base=None):
    """
    The environment for one launch.

    :param prefs.ProjectPrefs project_prefs: The project's paths.
    :param str dcc_name: The DCC name.
    :param str key: The DCC version, or for Unreal the project path.
    :param dict base: What to start from. Defaults to this process's environment.
    :return: The environment to start the DCC with.
    :rtype: dict
    :raises ValueError: When the project has no framework path, since without it there is
        nothing to put on the path and a DCC would start looking healthy and be empty.
    """

    framework_path = project_prefs.framework_path
    if not framework_path:
        raise ValueError('This project has no framework path set, so there would be nothing '
                         'for {} to load. Set it in the launcher\'s project setup.'
                         .format(dcc_name))

    environment = dict(os.environ if base is None else base)

    for name in QT_VARIABLES_TO_DROP:
        environment.pop(name, None)

    # The project's own values, none of them empty.
    environment.update(project_prefs.environment_values())
    environment['MCA_FRAMEWORK_PATH'] = framework_path
    environment['MCA_PACKAGES_PATH'] = framework_path
    environment['MCA_COMMON_PATH'] = common_path(framework_path)

    # The dependency folder for this exact DCC version, which is also the folder the
    # launcher just made sure was filled.
    deps = dependencies.target_folder(dcc_name, key)
    environment['MCA_COMMON_DEPEND'] = deps
    environment['MCA_{}_DEPEND'.format(_depend_name(dcc_name))] = deps

    # The bootstrap folder, added to whatever the machine already had.
    variable = PATH_VARIABLE.get(dcc_name, 'PYTHONPATH')
    environment[variable] = _prepend(environment.get(variable, ''),
                                     startup_folder(framework_path, dcc_name))

    if dcc_name == 'unreal' and str(key).lower().endswith('.uproject'):
        environment['UE_PROJECT_PATH'] = os.path.normpath(key)

    return environment


def describe(environment):
    """
    The MCA part of an environment, for a log line or a report.

    :param dict environment: An environment.
    :return: Only the variables this launcher sets, sorted.
    :rtype: dict
    """

    return {key: value for key, value in sorted(environment.items())
            if key.startswith('MCA_') or key in ('PYTHONPATH', 'UE_PYTHONPATH',
                                                 'UE_PROJECT_PATH')}


def _depend_name(dcc_name):
    """
    :param str dcc_name: The DCC name.
    :return: The middle of the MCA_<X>_DEPEND variable the framework's startup reads.
    :rtype: str
    """

    return {'maya': 'MAYA', 'mobu': 'MOBU', 'unreal': 'UNREAL'}.get(dcc_name,
                                                                    dcc_name.upper())


def _prepend(existing, folder):
    """
    Put a folder at the front of a path list, without duplicating it.

    :param str existing: The current value, possibly empty.
    :param str folder: The folder to add.
    :return: The new value.
    :rtype: str
    """

    parts = [part for part in str(existing or '').split(os.pathsep) if part.strip()]
    normalised = [os.path.normcase(os.path.normpath(part)) for part in parts]
    if os.path.normcase(os.path.normpath(folder)) in normalised:
        return os.pathsep.join(parts)
    return os.pathsep.join([folder] + parts)
