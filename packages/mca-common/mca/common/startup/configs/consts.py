"""
The names the framework and the launcher both use.

One table, in one place, because these strings are a contract: the launcher writes them into
the environment and into a project's preferences file, and the framework reads them back
inside the DCC. A typo on either side is a variable that is silently empty, which is the
hardest kind of wrong to find.

The names and the file names are unchanged from the version this replaces, so existing
preference files keep working.
"""

# python imports
import os


# ---------------------------------------------------------------------------- #
# The project, as the launcher hands it over
# ---------------------------------------------------------------------------- #
MCA_PROJECT_NAME = 'MCA_PROJECT_NAME'
MCA_PROJECT_ROOT = 'MCA_PROJECT_ROOT'
MCA_FRAMEWORK_PATH = 'MCA_FRAMEWORK_PATH'
MCA_PACKAGES_PATH = 'MCA_PACKAGES_PATH'
MCA_COMMON_PATH = 'MCA_COMMON_PATH'
MCA_COMMON_ROOT = 'MCA_COMMON_ROOT'
MCA_COMMON_CONFIG = 'MCA_COMMON_CONFIG'
MCA_COMMON_TOOLS = 'MCA_COMMON_TOOLS'

#: A folder of DCC installers, when the studio keeps one. The launcher writes it into a
#: project's preferences, so the framework should know the name even though nothing here
#: installs anything.
MCA_INSTALLERS_PATH = 'MCA_INSTALLERS_PATH'

#: Where the Python packages for this DCC version were installed. The launcher fills the
#: folder and names it here; nothing inside a DCC installs anything.
MCA_COMMON_DEPEND = 'MCA_COMMON_DEPEND'

# ---------------------------------------------------------------------------- #
# The art
# ---------------------------------------------------------------------------- #
MCA_ART_PATH = 'MCA_ART_PATH'
MCA_CHARACTERS_PATH = 'MCA_CHARACTERS_PATH'
MCA_PROPS_PATH = 'MCA_PROPS_PATH'
MCA_WEAPONS_PATH = 'MCA_WEAPONS_PATH'
MCA_GEAR_PATH = 'MCA_GEAR_PATH'
MCA_VEHICLE_PATH = 'MCA_VEHICLE_PATH'
MCA_ENVIRONMENT_PATH = 'MCA_ENVIRONMENT_PATH'

#: Every art folder, which is what a loop over "the project's art" should use rather than a
#: list written out again at each call site.
ART_PATHS = (MCA_ART_PATH, MCA_CHARACTERS_PATH, MCA_PROPS_PATH, MCA_WEAPONS_PATH,
             MCA_GEAR_PATH, MCA_VEHICLE_PATH, MCA_ENVIRONMENT_PATH)

# ---------------------------------------------------------------------------- #
# What ships with mca-common
# ---------------------------------------------------------------------------- #
MCA_RESOURCES_PATH = 'MCA_RESOURCES_PATH'
MCA_ICONS_PATH = 'MCA_ICONS_PATH'
MCA_IMAGES_PATH = 'MCA_IMAGES_PATH'
MCA_STYLES_PATH = 'MCA_STYLES_PATH'
MCA_FONTS_PATH = 'MCA_FONTS_PATH'
MCA_MOVIES_PATH = 'MCA_MOVIES_PATH'

#: Resource folder name to the variable that holds it, so the six lines that built these
#: one at a time are one loop.
RESOURCE_FOLDERS = (
    ('icons', MCA_ICONS_PATH),
    ('images', MCA_IMAGES_PATH),
    ('styles', MCA_STYLES_PATH),
    ('fonts', MCA_FONTS_PATH),
    ('movies', MCA_MOVIES_PATH),
)

# ---------------------------------------------------------------------------- #
# Overrides, which is how anything is testable
# ---------------------------------------------------------------------------- #
#: Set by the launcher and by the suites. With these, a test run - or a first-run sandbox -
#: reads and writes nowhere near a real machine's preferences.
MCA_PREFS_ROOT = 'MCA_PREFS_ROOT'
MCA_LOGS_ROOT = 'MCA_LOGS_ROOT'
MCA_LOGGING_LEVEL = 'MCA_LOGGING_LEVEL'

# ---------------------------------------------------------------------------- #
# Folders and files
# ---------------------------------------------------------------------------- #
#: Under Documents, unless MCA_PREFS_ROOT says otherwise.
MCA_LOCAL_PREFS = 'mca_preferences'

#: One per project, inside its own folder. The launcher writes this file; the framework
#: reads it.
MCA_LOCAL_PREFS_FILE = 'mca_project.prefs'

#: Beside the project folders, holding which project was open last. The launcher writes it
#: when the artist changes project; anything that has to work out "the current project"
#: without being told - the editor, a standalone script - reads it.
MCA_LAUNCHER_PREFS_FILE = 'mca_launcher.pref'

#: The key inside that file.
CURRENT_PROJECT_KEY = 'project_name'

#: mca-common, relative to the packages folder.
MCA_DEFAULT_COMMON_PATH = os.path.join('mca-common', 'mca', 'common')

#: The package manifest that ships beside mca/common.
MCA_PACKAGE_FILE = 'mca_package.yaml'
MCA_PACKAGE_BOOTS = 'mca_python_package.config'
MCA_PROJECT_CONFIG_NAME = 'mca_python.config'

# ---------------------------------------------------------------------------- #
# DCCs
# ---------------------------------------------------------------------------- #
MAYA = 'maya'
MOBU = 'mobu'
UNREAL = 'unreal'
STANDALONE = 'standalone'
