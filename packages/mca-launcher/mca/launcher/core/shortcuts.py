"""
Desktop shortcuts: one click, one DCC, one project, no launcher window.

The window is the thing an artist opens when they have a decision to make - which project,
which version. Opening Maya on the project they have worked in every day for a year is not a
decision, and making them pass through a window to reach it is a tax. So the launcher can put
a shortcut on their desktop that starts exactly that.

What the shortcut must not do is skip the dependency check. It does not: it runs the launcher
with ``--launch``, which is the same ``api.launch`` the window calls, and that checks first
and refuses if the packages are not ready. What it skips is the window, not the guarantee.

A shortcut carries the project it was made for by name, because a shortcut whose behaviour
depends on a setting you cannot see from the desktop is a trap. "Maya 2025 - Wayward" opens
Maya 2025 for Wayward, today and in a year.

Writing the ``.lnk`` itself is done by PowerShell's ``WScript.Shell``, which is on every
Windows machine. pywin32 would be a dependency for one call, and a ``.url`` file cannot carry
arguments or an icon.
"""

# python imports
import logging
import os
import subprocess
import sys

# mca imports
from mca.launcher.core import platform_paths


logger = logging.getLogger('mca-launcher')

#: How long PowerShell gets to write one shortcut.
WRITE_TIMEOUT = 60

#: The runner script a source checkout's shortcut points at. It puts the package on the path
#: itself, because a .lnk cannot set an environment variable.
RUNNER_NAME = 'open_dcc.py'


def desktop_folder():
    """
    The user's Desktop, asked of Windows rather than assumed.

    ``~/Desktop`` is wrong on any machine where the Desktop has been redirected to OneDrive,
    which is the default on a lot of them.

    :return: The Desktop folder.
    :rtype: str
    """

    if platform_paths.IS_WINDOWS:
        try:
            import ctypes
            import ctypes.wintypes

            csidl_desktop_directory = 16        # the real folder, not the virtual desktop
            shgfp_type_current = 0

            buffer = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(
                None, csidl_desktop_directory, None, shgfp_type_current, buffer)
            if buffer.value:
                return os.path.normpath(buffer.value)
            logger.warning('Windows returned an empty Desktop path; falling back.')
        except Exception as error:
            logger.warning('Could not ask Windows for the Desktop folder: %s', error)

    return os.path.normpath(os.path.join(platform_paths.home_folder(), 'Desktop'))


def package_root():
    """
    :return: The folder that holds the ``mca`` package - what has to be on the path.
    :rtype: str
    """

    # core/shortcuts.py -> core -> launcher -> mca -> the folder holding mca
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, os.pardir, os.pardir, os.pardir))


def runner_script():
    """
    :return: The runner script's path, or '' when it is not there.
    :rtype: str
    """

    path = os.path.join(package_root(), 'mca', 'launcher', RUNNER_NAME)
    return os.path.normpath(path) if os.path.isfile(path) else ''


def windowless_python():
    """
    ``pythonw.exe`` beside this interpreter, so a shortcut does not open a console behind the
    DCC it started.

    :return: The interpreter to use.
    :rtype: str
    """

    executable = sys.executable or ''
    if not platform_paths.IS_WINDOWS or not executable:
        return executable

    folder, name = os.path.split(executable)
    if name.lower() == 'python.exe':
        windowless = os.path.join(folder, 'pythonw.exe')
        if os.path.isfile(windowless):
            return os.path.normpath(windowless)
    return executable


def runner():
    """
    What a shortcut should start, whichever way this launcher is installed.

    Three cases, in the order they are worth trying:

    1. a frozen build - the exe is the launcher,
    2. an installed ``mca-launcher-ui`` command beside this interpreter,
    3. a source checkout - ``pythonw.exe`` and the runner script.

    :return: (target, leading arguments). Target is '' when nothing can be found.
    :rtype: tuple(str, list(str))
    """

    if getattr(sys, 'frozen', False) and sys.executable:
        return os.path.normpath(sys.executable), []

    if platform_paths.IS_WINDOWS and sys.executable:
        scripts = os.path.join(os.path.dirname(sys.executable), 'Scripts')
        for name in ('mca-launcher-ui.exe', 'mca-launcher.exe'):
            candidate = os.path.join(scripts, name)
            if os.path.isfile(candidate):
                return os.path.normpath(candidate), []

    script = runner_script()
    if script:
        return windowless_python(), [script]
    return '', []


def shortcut_name(label, key, project):
    """
    What the shortcut is called, as a person would write it.

    :param str label: The DCC's label, for example 'Maya'.
    :param str key: The version, or an Unreal project path.
    :param str project: The project name.
    :return: A file name with no extension and nothing Windows will refuse.
    :rtype: str
    """

    if str(key).lower().endswith('.uproject'):
        # Split on both separators by hand: this is a Windows path, and the tests run
        # anywhere, where os.path would keep the whole thing as one name.
        leaf = str(key).replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]
        key = os.path.splitext(leaf)[0]
    parts = [part for part in (label, str(key)) if part]
    name = '{} - {}'.format(' '.join(parts), project) if project else ' '.join(parts)
    for character in '\\/:*?"<>|':
        name = name.replace(character, '-')
    return name.strip() or 'MCA Launcher'


def _quote(text):
    """
    :param str text: One argument.
    :return: It, quoted for a command line if it needs to be.
    :rtype: str
    """

    text = str(text)
    return '"{}"'.format(text) if ' ' in text and not text.startswith('"') else text


def _powershell_literal(text):
    """
    :param str text: Anything going into a single-quoted PowerShell string.
    :return: It, with its quotes escaped.
    :rtype: str
    """

    return str(text).replace("'", "''")


def write(path, target, arguments=(), working_directory='', icon='', description=''):
    """
    Write a Windows shortcut.

    :param str path: The .lnk to write.
    :param str target: What it starts.
    :param list(str) arguments: Its arguments.
    :param str working_directory: Where it starts.
    :param str icon: A file to take the icon from. Its own exe, usually.
    :param str description: The tooltip.
    :return: The path written.
    :rtype: str
    :raises ValueError: When the shortcut could not be written, with what PowerShell said.
    """

    if not platform_paths.IS_WINDOWS:
        raise ValueError('Desktop shortcuts are a Windows thing, and this is not Windows.')
    if not target:
        raise ValueError('There is nothing for the shortcut to start.')

    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)

    lines = ["$link = (New-Object -ComObject WScript.Shell).CreateShortcut('{}')"
             .format(_powershell_literal(path)),
             "$link.TargetPath = '{}'".format(_powershell_literal(target))]
    if arguments:
        lines.append("$link.Arguments = '{}'".format(
            _powershell_literal(' '.join(_quote(one) for one in arguments))))
    if working_directory:
        lines.append("$link.WorkingDirectory = '{}'"
                     .format(_powershell_literal(working_directory)))
    if icon and os.path.isfile(icon):
        lines.append("$link.IconLocation = '{},0'".format(_powershell_literal(icon)))
    if description:
        # A tooltip has a hard limit, and a longer one silently writes nothing at all.
        lines.append("$link.Description = '{}'"
                     .format(_powershell_literal(str(description)[:250])))
    lines.append('$link.Save()')

    command = ['powershell', '-NoProfile', '-NonInteractive', '-Command', '; '.join(lines)]
    logger.info('writing shortcut: %s -> %s %s', path, target, ' '.join(arguments))
    try:
        process = subprocess.run(command, capture_output=True, text=True,
                                 timeout=WRITE_TIMEOUT, errors='replace')
    except Exception as error:
        raise ValueError('Could not run PowerShell to write the shortcut: {}'.format(error))

    if process.returncode != 0 or not os.path.isfile(path):
        raise ValueError('The shortcut was not written. PowerShell said: {}'
                         .format((process.stderr or process.stdout or '').strip()[-400:]
                                 or 'nothing at all'))
    return os.path.normpath(path)
