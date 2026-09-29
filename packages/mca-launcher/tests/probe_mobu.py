"""
Why a package that installed will not import inside MotionBuilder.

Run by ``probe_mobu.bat`` with mobupy. It answers three questions, in order:

1. what interpreter this is, and which python DLLs sit beside it,
2. whether the package imports from the dependency folder as things stand,
3. whether it imports once the interpreter's own folders are added as DLL search
   directories - which is the fix, if that is the problem.

A stable-ABI extension (``*.pyd`` built ``abi3``) links against ``python3.dll`` rather than
``python310.dll``. If a DCC ships only the version-specific one, every abi3 extension fails
with "DLL load failed ... The specified module could not be found", while pure Python and
version-specific extensions import perfectly - which is exactly the shape of this failure.
"""

# python imports
import glob
import os
import sys


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


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else ''
    package = sys.argv[2] if len(sys.argv) > 2 else 'psutil'

    print('interpreter : {}'.format(sys.executable))
    print('version     : {}'.format(sys.version.replace('\n', ' ')))
    print('deps folder : {}'.format(target))
    print('')

    here = os.path.dirname(sys.executable)
    candidates = [here,
                  os.path.join(here, 'python'),
                  os.path.join(here, 'python', 'DLLs'),
                  os.path.dirname(here)]
    for folder in candidates:
        print('{:<70} {}'.format(folder, ', '.join(dlls(folder))))
    print('')

    if target and target not in sys.path:
        sys.path.insert(0, target)

    # -- as things stand ------------------------------------------------ #
    try:
        module = __import__(package)
        print('{} imported as-is: {}'.format(package, getattr(module, '__file__', '?')))
        return 0
    except Exception as error:
        print('{} did NOT import: {}: {}'.format(package, type(error).__name__, error))

    # -- with the interpreter's folders as DLL directories -------------- #
    if not hasattr(os, 'add_dll_directory'):
        print('this Python has no os.add_dll_directory, so there is nothing else to try')
        return 1

    added = []
    for folder in candidates:
        if os.path.isdir(folder):
            try:
                os.add_dll_directory(folder)
                added.append(folder)
            except Exception as error:
                print('could not add {}: {}'.format(folder, error))
    for name in list(sys.modules):
        if name == package or name.startswith(package + '.'):
            del sys.modules[name]

    try:
        module = __import__(package)
        print('')
        print('{} DID import once these were added as DLL directories:'.format(package))
        for folder in added:
            print('    {}'.format(folder))
        print('    -> {}'.format(getattr(module, '__file__', '?')))
        return 0
    except Exception as error:
        print('')
        print('{} still did not import: {}: {}'.format(package, type(error).__name__, error))
        print('so the extension wants a DLL that is not on this machine at all - most likely')
        print('python3.dll, which a stable-ABI build links against.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
