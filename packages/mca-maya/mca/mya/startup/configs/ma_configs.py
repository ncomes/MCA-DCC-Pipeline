"""
Module that sets up the environment variables for MCA
"""

# mca python imports
import os
import sys

# software specific imports
import pymel.core as pm
import maya.cmds as cmds
# mca python imports
from mca.common import log
from mca.common.textio import yamlio
from mca.mya.utils import maya_utils


logger = log.MCA_LOGGER


def add_maya_system_paths(path_list):
    if not isinstance(path_list, (list, tuple)):
        path_list = [path_list]

    for path in path_list:
        if os.path.isdir(path) and os.path.normpath(path) not in sys.path:
            sys.path.append(path)


def add_maya_module(mod_file):
    """
    Loads a Maya module from a .mod file at runtime.

    Similar to add_maya_system_paths but for Maya modules. Adds the module
    directory to MAYA_MODULE_PATH, tells Maya to load it, and adds Python
    paths from the .mod file to sys.path.

    :param str mod_file: Full path to the .mod file
    :return: True if module was loaded successfully, False otherwise
    :rtype: bool
    """

    if not os.path.isfile(mod_file):
        logger.warning(f'Module file not found: {mod_file}')
        return False

    module_dir = os.path.dirname(mod_file)
    module_name = os.path.basename(mod_file).split('.')[0]

    # Add module directory to MAYA_MODULE_PATH
    current_path = os.environ.get('MAYA_MODULE_PATH', '')
    if module_dir not in current_path:
        os.environ['MAYA_MODULE_PATH'] = module_dir + os.pathsep + current_path

    # Tell Maya to scan and load the module
    try:
        cmds.loadModule(scan=True, allModules=True)
    except Exception as e:
        logger.error(f'Failed to load module {module_name}: {e}')
        return False

    # Parse the .mod file and add Python paths to sys.path
    # Maya's loadModule sets env vars but doesn't update sys.path in running interpreter
    _add_module_python_paths(mod_file, module_dir)

    # Verify module loaded
    loaded = cmds.moduleInfo(listModules=True) or []
    if module_name in loaded:
        logger.debug(f'Loaded Maya module: {module_name}')
        return True

    logger.warning(f'Module {module_name} not found after loadModule')
    return False


def _add_module_python_paths(mod_file, mod_file_dir):
    """
    Parses a .mod file and adds PYTHONPATH entries to sys.path.

    Maya's loadModule sets environment variables but doesn't update sys.path
    in the running Python interpreter. This function manually adds the paths.

    .mod file format example:
        + ModuleName 1.0 ModuleRoot
        PYTHONPATH+:= python
        scripts+:= scripts

    :param str mod_file: Path to the .mod file
    :param str mod_file_dir: Directory containing the .mod file
    """
    module_root = None
    python_paths = []

    try:
        with open(mod_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # First non-comment line starting with '+' defines module root
                # Format: "+ ModuleName Version ModuleRoot"
                if line.startswith('+') and module_root is None:
                    parts = line.split()
                    if len(parts) >= 4:
                        # Last part is the relative path to module root
                        module_root = os.path.join(mod_file_dir, parts[-1])
                    continue

                # Look for PYTHONPATH directives
                if 'PYTHONPATH' in line:
                    for sep in ['+:=', '+=']:
                        if sep in line:
                            rel_path = line.split(sep)[-1].strip()
                            if module_root:
                                full_path = os.path.normpath(os.path.join(module_root, rel_path))
                            else:
                                full_path = os.path.normpath(os.path.join(mod_file_dir, rel_path))
                            python_paths.append(full_path)
                            break

    except Exception as e:
        logger.debug(f'Error parsing .mod file for Python paths: {e}')
        return

    # Add paths to sys.path
    for py_path in python_paths:
        if os.path.isdir(py_path) and py_path not in sys.path:
            sys.path.append(py_path)
            logger.debug(f'Added module Python path: {py_path}')


class MayaDefaultStartOptions:
    def __init__(self, data=None):
        self._data = data
        if not data:
            self.set_default_options()

    @property
    def data(self):
        return self._data

    @property
    def use_defaults(self):
        """
        If True, defaults will be set in Maya.

        :return: If True, defaults will be set in Maya.
        :rtype: boolean
        """

        return self._data.get('use_defaults', True)

    @use_defaults.setter
    def use_defaults(self, value):
        """
        If True, defaults will be set in Maya.

        :param bool value: If True, defaults will be set in Maya.
        """

        self._data.update({'use_defaults': value})

    @property
    def working_unit_linear(self):
        """
        Unit settings to be applied in maya.

        :return: Returns the Unit settings to be applied in maya.
        :rtype: str
        """

        return self._data.get('workingUnitLinear', 'cm')

    @working_unit_linear.setter
    def working_unit_linear(self, value):
        """
        Sets the unit settings to be applied in maya.

        :param str value: unit measure.
        """

        self._data.update({'workingUnitLinear': value})

    @property
    def working_unit_linear_default(self):
        """
        Default Unit settings to be applied in maya.

        :return: Returns the Default Unit settings to be applied in maya.
        :rtype: str
        """

        return self._data.get('workingUnitLinearDefault', 'cm')

    @working_unit_linear_default.setter
    def working_unit_linear_default(self, value):
        """
        Sets the Default unit settings to be applied in maya.

        :param str value: Default unit measure.
        """

        self._data.update({'workingUnitLinearDefault': value})

    @property
    def working_unit_time(self):
        """
        Returns the unit time for Maya's timeline that will be set.

        :return: Returns the unit time for Maya's timeline that will be set.
        :rtype: str
        """

        return self._data.get('workingUnitTime', 'ntsc')

    @working_unit_time.setter
    def working_unit_time(self, value):
        """
        Sets unit time for Maya's timeline.

        :param str value: Unit time.
        """

        self._data.update({'workingUnitTime': value})

    @property
    def working_unit_time_default(self):
        """
        Returns the default unit time for Maya's timeline that will be set.

        :return: Returns the default unit time for Maya's timeline that will be set.
        :rtype: str
        """

        return self._data.get('workingUnitTimeDefault', 'ntsc')

    @working_unit_time_default.setter
    def working_unit_time_default(self, value):
        """
        Sets default unit time for Maya's timeline.

        :param str value: Unit default time.
        """

        self._data.update({'workingUnitTimeDefault': value})

    @property
    def playback_max(self):
        """
        Returns the playback max for Maya's timeline that will be set.

        :return: Returns the playback max for Maya's timeline that will be set.
        :rtype: int
        """

        return self._data.get('playbackMax', 120)

    @playback_max.setter
    def playback_max(self, value):
        """
        Sets the playback max for Maya's timeline.

        :param int value: the playback max for Maya's timeline.
        """

        self._data.update({'playbackMax': value})

    @property
    def playback_max_default(self):
        """
        Returns the default playback max for Maya's timeline that will be set.

        :return: Returns the default playback max for Maya's timeline that will be set.
        :rtype: int
        """

        return self._data.get('playbackMaxDefault', 120)

    @playback_max_default.setter
    def playback_max_default(self, value):
        """
        Sets the default playback max for Maya's timeline.

        :param int value: the default playback max for Maya's timeline.
        """

        self._data.update({'playbackMaxDefault': value})

    @property
    def playback_max_range(self):
        """
        Returns the playback max range for Maya's timeline that will be set.

        :return: Returns the playback max range for Maya's timeline that will be set.
        :rtype: int
        """

        return self._data.get('playbackMaxRange', 120)

    @playback_max_range.setter
    def playback_max_range(self, value):
        """
        Sets the playback max range for Maya's timeline.

        :param int value: the range playback max for Maya's timeline.
        """

        self._data.update({'playbackMaxRange': value})

    @property
    def playback_max_range_default(self):
        """
        Returns the default playback max range for Maya's timeline that will be set.

        :return: Returns the default playback max range for Maya's timeline that will be set.
        :rtype: int
        """

        return self._data.get('playbackMaxRangeDefault', 120)

    @playback_max_range_default.setter
    def playback_max_range_default(self, value):
        """
        Sets the default playback max range for Maya's timeline.

        :param int value: the default range playback max for Maya's timeline.
        """

        self._data.update({'playbackMaxRangeDefault': value})

    @property
    def playback_min(self):
        """
        Returns the playback min for Maya's timeline that will be set.

        :return: Returns the playback min for Maya's timeline that will be set.
        :rtype: int
        """

        return self._data.get('playbackMin', 0)

    @playback_min.setter
    def playback_min(self, value):
        """
        Sets the playback min for Maya's timeline.

        :param int value: the playback min for Maya's timeline.
        """

        self._data.update({'playbackMin': value})

    @property
    def playback_min_default(self):
        """
        Returns the default playback min for Maya's timeline that will be set.

        :return: Returns the default playback min for Maya's timeline that will be set.
        :rtype: int
        """

        return self._data.get('playbackMinDefault', 0)

    @playback_min_default.setter
    def playback_min_default(self, value):
        """
        Sets the default playback min for Maya's timeline.

        :param int value: the default playback min for Maya's timeline.
        """

        self._data.update({'playbackMinDefault': value})

    @property
    def playback_min_range(self):
        """
        Returns the playback min range for Maya's timeline that will be set.

        :return: Returns the playback min range for Maya's timeline that will be set.
        :rtype: int
        """

        return self._data.get('playbackMinRange', 0)

    @playback_min_range.setter
    def playback_min_range(self, value):
        """
        Sets the playback min range for Maya's timeline.

        :param int value: the range playback min for Maya's timeline.
        """

        self._data.update({'playbackMinRange': value})

    @property
    def playback_min_range_default(self):
        """
        Returns the default playback min range for Maya's timeline that will be set.

        :return: Returns the default playback min range for Maya's timeline that will be set.
        :rtype: int
        """

        return self._data.get('playbackMinRangeDefault', 0)

    @playback_min_range_default.setter
    def playback_min_range_default(self, value):
        """
        Sets the default playback min range for Maya's timeline.

        :param int value: the default range playback min for Maya's timeline.
        """

        self._data.update({'playbackMinRangeDefault': value})

    @property
    def grid_divisions(self):
        """
        Returns the number of grid divisions that will be set.

        :return: Returns the number of grid divisions that will be set.
        :rtype: int
        """

        return self._data.get('gridDivisions', 10)

    @grid_divisions.setter
    def grid_divisions(self, value):
        """
        Sets the number of grid divisions.

        :param int value: the number of grid divisions.
        """

        self._data.update({'gridDivisions': value})

    @property
    def grid_size(self):
        """
        Returns the grid size that will be set.

        :return: Returns the grid size that will be set.
        :rtype: int
        """

        return self._data.get('gridSize', 200)

    @grid_size.setter
    def grid_size(self, value):
        """
        Sets the grid size.

        :param int value: the grid size.
        """

        self._data.update({'gridSize': value})

    @property
    def grid_spacing(self):
        """
        Returns the grid spacing that will be set.

        :return: Returns the grid spacing that will be set.
        :rtype: int
        """

        return self._data.get('gridSpacing', 100)

    @grid_spacing.setter
    def grid_spacing(self, value):
        """
        Sets the grid spacing.

        :param int value: the grid spacing.
        """

        self._data.update({'gridSpacing': value})

    def set_default_options(self):
        """
        Default Maya options.
        """

        self._data = {}
        self._data.update({"use_defaults": True})
        # setting the units
        self._data.update({"workingUnitLinear": "cm"})
        self._data.update({"workingUnitLinearDefault": "cm"})
        self._data.update({"workingUnitTime": "ntsc"})
        self._data.update({"workingUnitTimeDefault": "ntsc"})

        # setting the timeline durations and defaults
        self._data.update({"playbackMax": 120})
        self._data.update({"playbackMaxDefault": 120})
        self._data.update({"playbackMaxRange": 120})
        self._data.update({"playbackMaxRangeDefault": 120})
        self._data.update({"playbackMin": 0})
        self._data.update({"playbackMinDefault": 0})
        self._data.update({"playbackMinRange": 0})
        self._data.update({"playbackMinRangeDefault": 0})

        # setting the grid settings
        self._data.update({"gridDivisions": 10})
        self._data.update({"gridSize": 200})
        self._data.update({"gridSpacing": 100})

    def apply_maya_defaults(self):
        """
        Applies the settings to Maya.
        """
        if not self._data.get('use_defaults'):
            return

        for k, v in self._data.items():
            if k == 'use_defaults':
                continue
            elif isinstance(v, str):
                pm.optionVar(sv=(k, v))
            elif isinstance(v, (float, int)):
                pm.optionVar(fv=(k, v))
            else:
                logger.warning(f'Cannot set type for {k}: {type(v)} not declared in class.')
                continue

    @classmethod
    def load(cls, save_data=True):
        """
        Returns an instance of MayaDefaultStartOptions with either saved data or default data.

        :param save_data:
        :return: Returns an instance of MayaDefaultStartOptions with either saved data or default data.
        :rtype: MayaDefaultStartOptions
        """

        default_prefs = maya_utils.get_default_preferences_file()
        if not os.path.exists(default_prefs):
            logger.warning("No preferences file was found.  Returning default settings.")
            default_cls = cls()
            if save_data:
                yamlio.write_to_yaml_file(default_cls.data, default_prefs)
            return default_cls
        prefs = yamlio.read_yaml_file(default_prefs)
        return cls(prefs)

    def save(self):
        """
        Saves the default settings to a yaml file in the preferences folder.
        """

        default_prefs = maya_utils.get_default_preferences_file()
        yamlio.write_to_yaml_file(self._data, default_prefs)

