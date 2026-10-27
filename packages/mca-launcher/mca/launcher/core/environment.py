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


def mcp_package_folder():
    """
    Where mca-mcp is, when it is a sibling package rather than a pip install.

    The launcher and the MCP server ship together and are versioned together, so the
    launcher can simply look beside itself:
    ``packages/mca-launcher`` and ``packages/mca-mcp`` share a parent.

    Handing this to the DCC is what lets its start-up open the command ports - which is how
    an assistant reaches Maya at all. Before, those ports were opened by a code editor's
    plug-in, so closing the editor took the assistant's hands off.

    :return: The folder to put on the DCC's PYTHONPATH, or '' when mca-mcp is not a sibling
        (a pip install needs nothing here).
    :rtype: str
    """

    # environment.py -> core -> launcher -> mca -> mca-launcher -> packages
    packages = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))))
    candidate = os.path.join(packages, 'mca-mcp')
    if os.path.isdir(os.path.join(candidate, 'mca', 'mcp')):
        return os.path.normpath(candidate)
    return ''


#: Overrides that move where preferences, dependencies and logs live. The launcher honours
#: them and so does mca-common, so a DCC has to be told about them too.
ROOT_VARIABLES = ('MCA_PREFS_ROOT', 'MCA_DEPS_ROOT', 'MCA_LOGS_ROOT', 'MCA_LOGGING_LEVEL')


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

    # Where preferences and logs live, handed over deliberately. The framework inside the DCC
    # reads these same three names, so without them a DCC started from a first-run sandbox
    # would write its logs and read its project preferences from the real folders - the one
    # thing the sandbox exists to prevent. They did reach the DCC before this, but only
    # because the whole environment is inherited, which is an accident rather than a
    # promise: anything that later built a clean environment would have dropped them.
    for name in ROOT_VARIABLES:
        value = os.getenv(name)
        if value:
            environment[name] = value

    # The dependency folder for this exact DCC version, which is also the folder the
    # launcher just made sure was filled.
    deps = dependencies.target_folder(dcc_name, key)
    environment['MCA_COMMON_DEPEND'] = deps
    environment['MCA_{}_DEPEND'.format(_depend_name(dcc_name))] = deps

    # The DCC's python path is BUILT, not inherited.
    #
    # It used to keep whatever the launching shell happened to carry, which sounds
    # generous and is not: a test harness that set PYTHONPATH to its own package roots
    # passed them into Maya, so Maya's interpreter had a second copy of the `mca`
    # namespace in front of the real one before the framework had said a word. What a DCC
    # imports should depend on the project it was started for and nothing else.
    variable = PATH_VARIABLE.get(dcc_name, 'PYTHONPATH')
    inherited = environment.pop(variable, '')
    if inherited:
        logger.info('Not passing the inherited %s on to %s: %s', variable, dcc_name,
                    inherited)
    environment[variable] = startup_folder(framework_path, dcc_name)

    # And the MCP package, so the DCC's start-up can open its command ports. Passed as a
    # variable as well as on the path: the start-up script reads MCA_MCP_PATH by name, which
    # keeps it working even where PYTHONPATH is rewritten by something else on the way in.
    mcp_folder = mcp_package_folder()
    if mcp_folder:
        environment['MCA_MCP_PATH'] = mcp_folder
        environment[variable] = _prepend(environment[variable], mcp_folder)
        # Opening a command port is off unless asked for. The launcher asks, for the DCCs it
        # starts; a DCC started any other way is left alone, which keeps "start it another
        # way" as an escape from anything this does during start-up.
        environment['MCA_MAYA_COMMAND_PORTS'] = '1'

    # Keep Python's per-user site-packages out of the DCC.
    #
    # `pip install --user something` lands in AppData/Roaming/Python/PythonXY, which
    # Python adds to sys.path automatically and ahead of the DCC's own packages. A
    # user-site PyMEL shadowing the managed one is exactly how a Maya that was fine
    # yesterday stops importing the framework today, with nothing saying why. The
    # dependency folder this launcher fills is the one that should win.
    environment['PYTHONNOUSERSITE'] = '1'

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
                                                 'UE_PROJECT_PATH', 'PYTHONNOUSERSITE')}


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
