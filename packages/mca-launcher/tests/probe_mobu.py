"""
Why a package that installed will not import inside MotionBuilder.

Run by ``probe_mobu.bat`` with mobupy. It answers three questions, in order:

1. what interpreter this is, and which python DLLs sit beside it,
2. whether the package imports from the dependency folder as things stand,
3. whether it imports once the interpreter's own folders are added as DLL search
   directories - which is the fix, if that is the problem.

Everything it prints is also written to ``%LOCALAPPDATA%/MCA/probe_mobu.txt``, because a
console window that has been closed takes its answer with it.

A stable-ABI extension (``*.pyd`` built ``abi3``) links against ``python3.dll`` rather than
``python310.dll``. If a DCC ships only the version-specific one, every abi3 extension fails
with "DLL load failed ... The specified module could not be found", while pure Python and
version-specific extensions import perfectly - which is exactly the shape of this failure.
"""

# python imports
import glob
import os
import subprocess
import sys

#: Set on the child, so the re-run below happens once and not forever.
CHILD_VARIABLE = 'MCA_PROBE_UNDER_MOBUPY'


#: Where the report is written as well as printed.
def report_path():
    """
    :return: The file the report is written to.
    :rtype: str
    """

    local = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(local, 'MCA', 'probe_mobu.txt')


LINES = []


def say(text=''):
    """
    Print a line, and keep it for the report file.

    :param str text: The line.
    """

    print(text)
    LINES.append(str(text))


def dlls(folder):
    """
    :param str folder: Where to look.
    :return: The python DLLs there.
    :rtype: list(str)
    """

    if not os.path.isdir(folder):
        return ['<no such folder>']
    return sorted(os.path.basename(path) for path in
                  glob.glob(os.path.join(folder, 'python*.dll'))) or ['<none>']


def find_mobupy():
    """
    MotionBuilder's own interpreter, from the registry first and the usual place after.

    :return: The path, or ''.
    :rtype: str
    """

    relative = os.path.join('bin', 'x64', 'mobupy.exe')
    try:
        import winreg
    except ImportError:
        winreg = None

    if winreg:
        for version in ('2026', '2025', '2024', '2023', '2022'):
            key = r'SOFTWARE\Autodesk\MotionBuilder\{}'.format(version)
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, key) as opened:
                        folder, _ = winreg.QueryValueEx(opened, 'InstallPath')
                except OSError:
                    continue
                candidate = os.path.join(str(folder), relative)
                if os.path.isfile(candidate):
                    return os.path.normpath(candidate)

    for version in ('2026', '2025', '2024', '2023', '2022'):
        candidate = os.path.join(r'C:\Program Files\Autodesk',
                                 'MotionBuilder {}'.format(version), relative)
        if os.path.isfile(candidate):
            return os.path.normpath(candidate)
    return ''


def rerun_under_mobupy():
    """
    Start this same file again with mobupy, and pass its output straight through.

    The whole question is about MotionBuilder's interpreter, so being opened with any other
    Python answers nothing - and a probe that quietly answers the wrong question is worse
    than one that will not run. Double-clicking this file now gets the right answer anyway.

    :return: The exit code, or None when there is no MotionBuilder to run it with.
    :rtype: int or None
    """

    mobupy = find_mobupy()
    if not mobupy:
        return None

    environment = dict(os.environ)
    environment[CHILD_VARIABLE] = '1'
    command = [mobupy, os.path.abspath(__file__)] + sys.argv[1:]
    print('re-running under {}'.format(mobupy))
    print('')
    return subprocess.call(command, env=environment)


def newest_dependency_folder(name='mobu-2024'):
    """
    The dependency folder to look in when nobody said.

    The newest first-run sandbox if there is one, because that is what has just failed,
    and otherwise the real folder.

    :param str name: The ``<dcc>-<version>`` folder wanted.
    :return: The folder, or ''.
    :rtype: str
    """

    local = os.environ.get('LOCALAPPDATA', '')
    if not local:
        return ''
    sandboxes = os.path.join(local, 'MCA', 'first-run')
    if os.path.isdir(sandboxes):
        stamps = sorted(os.listdir(sandboxes), reverse=True)
        for stamp in stamps:
            folder = os.path.join(sandboxes, stamp, 'deps', name)
            if os.path.isdir(folder):
                return folder
    folder = os.path.join(local, 'MCA', 'deps', name)
    return folder if os.path.isdir(folder) else ''


def main():
    # Opened with the wrong Python - by a file association, or by double-clicking this file
    # rather than the batch file beside it. Hand the job to the interpreter the question is
    # actually about.
    if 'mobupy' not in os.path.basename(sys.executable).lower():
        if not os.environ.get(CHILD_VARIABLE):
            code = rerun_under_mobupy()
            if code is not None:
                # The child wrote the report; this process has nothing to add.
                raise SystemExit(code)
            say('No MotionBuilder was found on this machine, so this is {} instead - which '
                'answers nothing about MotionBuilder.'.format(sys.executable))

    target = sys.argv[1] if len(sys.argv) > 1 else ''
    package = sys.argv[2] if len(sys.argv) > 2 else 'psutil'
    if not target:
        target = newest_dependency_folder()
        say('(no folder given, using the newest one found)')

    say('interpreter : {}'.format(sys.executable))
    say('version     : {}'.format(sys.version.replace('\n', ' ')))
    say('deps folder : {}'.format(target))
    say('')

    here = os.path.dirname(sys.executable)
    candidates = [here,
                  os.path.join(here, 'python'),
                  os.path.join(here, 'python', 'DLLs'),
                  os.path.dirname(here)]
    for folder in candidates:
        say('{:<70} {}'.format(folder, ', '.join(dlls(folder))))
    say('')

    # What was actually installed: an extension named *.abi3.pyd or a dist-info tagged
    # abi3 is the stable-ABI build, and that is the one that wants python3.dll.
    if target and os.path.isdir(target):
        folder = os.path.join(target, package)
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith(('.pyd', '.dll')):
                    say('{} ships: {}'.format(package, name))
        for name in sorted(os.listdir(target)):
            if name.lower().startswith(package) and name.lower().endswith('.dist-info'):
                say('{} installed as: {}'.format(package, name))
        say('')

    if target and target not in sys.path:
        sys.path.insert(0, target)

    # -- as things stand ------------------------------------------------ #
    try:
        module = __import__(package)
        say('{} imported as-is: {}'.format(package, getattr(module, '__file__', '?')))
        return 0
    except Exception as error:
        say('{} did NOT import: {}: {}'.format(package, type(error).__name__, error))

    # -- with the interpreter's folders as DLL directories -------------- #
    if not hasattr(os, 'add_dll_directory'):
        say('this Python has no os.add_dll_directory, so there is nothing else to try')
        return 1

    added = []
    for folder in candidates:
        if os.path.isdir(folder):
            try:
                os.add_dll_directory(folder)
                added.append(folder)
            except Exception as error:
                say('could not add {}: {}'.format(folder, error))
    for name in list(sys.modules):
        if name == package or name.startswith(package + '.'):
            del sys.modules[name]

    try:
        module = __import__(package)
        say('')
        say('{} DID import once these were added as DLL directories:'.format(package))
        for folder in added:
            say('    {}'.format(folder))
        say('    -> {}'.format(getattr(module, '__file__', '?')))
        return 0
    except Exception as error:
        say('')
        say('{} still did not import: {}: {}'.format(package, type(error).__name__, error))
        say('so the extension wants a DLL that is not on this machine at all - most likely')
        say('python3.dll, which a stable-ABI build links against.')
        return 1


def write_report():
    """Write everything that was said to a file, so a closed window loses nothing."""

    path = report_path()
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, 'w') as opened:
            opened.write('\n'.join(LINES) + '\n')
        print('')
        print('written to {}'.format(path))
    except Exception as error:
        print('could not write {}: {}'.format(path, error))


if __name__ == '__main__':
    try:
        code = main()
    except SystemExit as stop:
        # The child did the work and wrote the report.
        sys.exit(stop.code)
    write_report()
    sys.exit(code)
