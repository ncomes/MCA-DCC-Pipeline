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
import sys


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
    code = main()
    write_report()
    sys.exit(code)
