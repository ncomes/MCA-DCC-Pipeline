"""
The dependency bootstrap - the thing that has to be right for anything else to work.

What this fixes, stated plainly, because every point was a real failure:

**It runs on every launch, not once on first setup.** The old launcher checked in exactly
one place: first-run, after the "Save Paths?" confirm. Add a second project, switch
projects, or clean the folder, and Maya was handed a dependencies path that need not
exist.

**One folder per DCC version, filled by that DCC's own interpreter.** Measured on this
machine: Maya 2022 is Python 3.7.7, Maya 2024 is 3.10.8, Maya 2025 is 3.11.4, Maya 2026 is
3.11.9, MotionBuilder 2024 is 3.10.8. A wheel built for one of those does not load in
another, so a single shared folder named after a Python version - with ``python -m pip``
resolving to whatever is on PATH - is wrong by construction.

**The folder is wiped before it is filled.** ``pip install --target`` does not uninstall
what is already there. The old shared folder ended up holding PySide6 6.7.2, 6.10.0 *and*
6.10.1 dist-infos, two numpys and two of several other packages, with whichever was
written last silently winning.

**Qt is never installed into a DCC folder.** Every supported DCC ships its own: PySide2
5.15 in Maya 2022, Maya 2024 and MotionBuilder 2024; PySide6 6.5.3 in Maya 2025 and 2026.
A second, newer Qt on ``sys.path`` beside the DCC's own is how you get two QApplication
classes and an abort with no traceback.

**Being installed is proved by importing, not by a folder existing.** The old check looked
for a ``PySide6`` folder and a ``numpy`` folder. A half-finished install leaves both
behind, so it passed for good.

**A failure stops the launch.** Opening Maya without its dependencies produces a report of
"the tools are broken" instead of "the install failed", which costs a day to tell apart.
"""

# python imports
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import time

# mca imports
from mca.launcher.core import fileio, platform_paths


logger = logging.getLogger('mca-launcher')

#: Written into every dependency folder, and the reason a second launch is fast.
DEPENDENCY_STAMP = '.mca-deps.json'

#: Bumped when the stamp's meaning changes, which forces a reinstall rather than trusting
#: a stamp this version of the code did not write.
STAMP_VERSION = 1

#: A copy of exactly what was asked for, kept beside what was installed.
INSTALLED_REQUIREMENTS = 'requirements.installed.txt'

#: Never installed into a DCC's folder. See the module docstring.
EXCLUDED_FROM_DCCS = (
    'pyside6', 'pyside6-essentials', 'pyside6-addons',
    'pyside2', 'pyside2-essentials', 'pyside2-addons',
    'shiboken6', 'shiboken2',
)

#: Distribution name -> the name you import, for the ones that differ.
IMPORT_NAMES = {
    'pyyaml': 'yaml',
    'beautifulsoup4': 'bs4',
    'pillow': 'PIL',
    'opencv-python': 'cv2',
    'protobuf': 'google.protobuf',
    'python-dateutil': 'dateutil',
    'typing-extensions': 'typing_extensions',
    'google-genai': 'google.genai',
}

#: When a package's Windows wheel is a stable-ABI ("abi3") build, the newest version of it
#: that still ships a wheel built for one exact Python.
#:
#: An abi3 extension is one wheel for every Python 3.x, and it links against ``python3.dll``
#: rather than ``python310.dll``. MotionBuilder 2024 ships only ``python310.dll`` - measured:
#: ``bin/x64`` holds that and nothing else - so every abi3 extension there fails to load with
#: "DLL load failed ... The specified module could not be found", while pure Python and
#: version-specific extensions import perfectly. Maya has no such trouble with the same
#: package and the same Python version, which is why this is not a rule about Python 3.10.
#:
#: psutil's wheels went abi3 at 5.9.4; 5.9.3 is the last with a ``cp310-cp310-win_amd64``
#: wheel. It is only reached when the abi3 build has actually failed to import, so a machine
#: where the modern one works never sees it.
ABI3_FALLBACKS = {
    'psutil': 'psutil == 5.9.3',
}

#: What a Windows extension module says when the DLL it links against is not there.
ABI3_SYMPTOM = 'dll load failed'

#: The framework does not start without these. Everything else that fails to install for a
#: given interpreter is reported and skipped - which is how Maya 2022's Python 3.7 can keep
#: working after the AI packages, which need 3.8 or newer, refuse to install there.
CORE_IMPORTS = ('yaml', 'numpy', 'psutil', 'requests', 'pytz', 'bs4', 'anytree')

#: How long a single pip run may take before it is called hung. Installing numpy, scipy and
#: friends from source on a cold cache is genuinely slow; ten minutes is generous without
#: being forever.
INSTALL_TIMEOUT = 900

#: How long the import check may take. It starts an interpreter, so it is seconds.
VERIFY_TIMEOUT = 180


# ---------------------------------------------------------------------------- #
# Where things are
# ---------------------------------------------------------------------------- #
def target_folder(dcc, version):
    """
    Where this DCC version's dependencies live.

    :param str dcc: DCC name, for example 'maya'.
    :param str version: DCC version, for example '2025'.
    :return: The folder. It need not exist yet.
    :rtype: str
    """

    name = '{}-{}'.format(str(dcc).strip().lower(), str(version).strip())
    return os.path.normpath(os.path.join(platform_paths.dependencies_root(), name))


def stamp_path(target):
    """
    :param str target: A dependency folder.
    :return: The path of its stamp file.
    :rtype: str
    """

    return os.path.join(target, DEPENDENCY_STAMP)


def requirements_path(framework_path):
    """
    Find the requirements list, which mca-common owns.

    The launcher installs the list; it does not keep one. A second copy is how the
    installer and the framework drift apart, and the old tree shows exactly that: a folder
    named ``python311`` holding packages installed by whatever ``python`` was on PATH.

    Both the new layout and the old one are accepted, so this works before and after
    mca-common moves.

    :param str framework_path: The packages folder - the one holding mca-common.
    :return: The requirements file.
    :rtype: str
    :raises ValueError: When there is no requirements file to install.
    """

    if not framework_path:
        raise ValueError('No framework path is set, so there is no requirements list to '
                         'install. Set the project up in the launcher first.')

    common = os.path.join(framework_path, 'mca-common', 'mca', 'common')
    candidates = [
        os.path.join(common, 'startup', 'dependencies', 'requirements.txt'),
        os.path.join(common, 'startup', 'dependencies', 'python311', 'requirements.txt'),
        os.path.join(common, 'startup', 'dependencies', 'python310', 'requirements.txt'),
        os.path.join(framework_path, 'requirements.txt'),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.normpath(candidate)

    raise ValueError('No requirements.txt found under {}. Looked in: {}'
                     .format(common, ', '.join(os.path.dirname(one) for one in candidates)))


# ---------------------------------------------------------------------------- #
# Reading the list
# ---------------------------------------------------------------------------- #
def read_text(path):
    """
    Read a text file whole.

    :param str path: The file.
    :return: Its contents.
    :rtype: str
    :raises ValueError: When it cannot be read, because a missing requirements file is not
        something to paper over with an empty string.
    """

    try:
        with open(path, 'r', encoding='utf-8') as opened:
            return opened.read()
    except Exception as error:
        raise ValueError('Could not read {}: {}'.format(path, error))


def parse_requirements(text):
    """
    Turn the file's text into the requirement lines that matter.

    Comments, blank lines, ``-r`` includes and pip options are dropped. Nothing clever:
    the file is a flat list, and pretending otherwise would be inventing a format.

    :param str text: The file's contents.
    :return: One requirement per entry, in file order.
    :rtype: list(str)
    """

    lines = []
    for raw in (text or '').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith('-'):
            continue
        lines.append(line)
    return lines


def requirement_name(line):
    """
    :param str line: A requirement, for example 'anytree >= 2.8.0'.
    :return: Its distribution name, lower case.
    :rtype: str
    """

    name = re.split(r'[<>=!~\[;\s]', str(line).strip(), maxsplit=1)[0]
    return name.strip().lower()


def import_name(line):
    """
    :param str line: A requirement.
    :return: The name you would import to prove it is installed.
    :rtype: str
    """

    name = requirement_name(line)
    return IMPORT_NAMES.get(name, name.replace('-', '_'))


def dcc_requirements(lines):
    """
    The requirements that belong in a DCC's folder.

    :param list(str) lines: Every requirement in the file.
    :return: (kept, dropped) - dropped are the Qt packages the DCC already provides.
    :rtype: tuple(list(str), list(str))
    """

    kept = []
    dropped = []
    for line in lines:
        if requirement_name(line) in EXCLUDED_FROM_DCCS:
            dropped.append(line)
        else:
            kept.append(line)
    return kept, dropped


def fingerprint(lines):
    """
    A fingerprint of what was asked for.

    Whitespace and order are normalised away, so reformatting the file does not force a
    reinstall, while adding, removing or re-pinning a package does.

    :param list(str) lines: The requirements actually being installed.
    :return: A short hex digest.
    :rtype: str
    """

    normalised = sorted(' '.join(line.split()).lower() for line in lines)
    digest = hashlib.sha256('\n'.join(normalised).encode('utf-8')).hexdigest()
    return digest[:16]


# ---------------------------------------------------------------------------- #
# Is it already done
# ---------------------------------------------------------------------------- #
def status(dcc, version, framework_path):
    """
    Whether this DCC version's dependencies are installed and match the current list.

    Cheap on purpose - it reads one small JSON file and compares a hash. It is called on
    every launch, so it must not start an interpreter to answer.

    :param str dcc: DCC name.
    :param str version: DCC version.
    :param str framework_path: The packages folder.
    :return: What is known, including ``satisfied`` and a ``reason`` for a person.
    :rtype: dict
    """

    target = target_folder(dcc, version)
    answer = {
        'dcc': dcc,
        'version': str(version),
        'target': target,
        'satisfied': False,
        'reason': '',
        'stamp': None,
        'requirements': None,
        'fingerprint': None,
        'skipped': [],
    }

    requirements = requirements_path(framework_path)
    answer['requirements'] = requirements
    wanted, _ = dcc_requirements(parse_requirements(read_text(requirements)))
    answer['fingerprint'] = fingerprint(wanted)

    stamp = fileio.read_json(stamp_path(target))
    answer['stamp'] = stamp

    if not os.path.isdir(target):
        answer['reason'] = 'Nothing is installed for {} {} yet.'.format(dcc, version)
        return answer
    if not stamp:
        answer['reason'] = ('{} exists but carries no stamp, so what is in it is unknown.'
                            .format(target))
        return answer
    if stamp.get('stamp_version') != STAMP_VERSION:
        answer['reason'] = 'The stamp was written by an older launcher; reinstalling.'
        return answer
    if not stamp.get('verified'):
        answer['reason'] = 'The last install did not pass its import check.'
        return answer
    if stamp.get('fingerprint') != answer['fingerprint']:
        answer['reason'] = 'The requirements list changed since this folder was filled.'
        return answer

    answer['satisfied'] = True
    answer['skipped'] = stamp.get('skipped') or []
    answer['reason'] = ('{} {} has its dependencies, installed {} by {}.'
                        .format(dcc, version, stamp.get('installed_at', 'at some point'),
                                stamp.get('interpreter', 'an unknown interpreter')))
    return answer


# ---------------------------------------------------------------------------- #
# Doing it
# ---------------------------------------------------------------------------- #
def _run(command, progress=None, timeout=INSTALL_TIMEOUT, cwd=None):
    """
    Run a command, streaming its output to a callback as it arrives.

    Streaming rather than collecting, because a pip install is minutes long and a progress
    dialog that says nothing for three minutes is indistinguishable from a hang.

    :param list(str) command: The command.
    :param callable progress: Called with each line. May be None.
    :param float timeout: Seconds before the command is killed.
    :param str cwd: Working directory.
    :return: (return code, the whole output)
    :rtype: tuple(int, str)
    """

    logger.info('running: %s', ' '.join(command))
    lines = []
    started = time.time()

    creation_flags = 0
    if platform_paths.IS_WINDOWS:
        # No console window when the launcher itself is a windowed exe.
        creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               universal_newlines=True, errors='replace', cwd=cwd,
                               creationflags=creation_flags)
    try:
        for line in iter(process.stdout.readline, ''):
            line = line.rstrip()
            if line:
                lines.append(line)
                logger.debug('  %s', line)
                if progress:
                    progress(line)
            if time.time() - started > timeout:
                process.kill()
                lines.append('Killed after {:.0f} seconds.'.format(timeout))
                break
    finally:
        if process.stdout:
            process.stdout.close()
        code = process.wait()

    return code, '\n'.join(lines)


def _pip_command(interpreter, extra):
    """
    :param str interpreter: The DCC's Python executable.
    :param list(str) extra: Arguments after ``-m pip``.
    :return: The whole command.
    :rtype: list(str)
    """

    return [interpreter, '-m', 'pip'] + list(extra)


def has_pip(interpreter):
    """
    :param str interpreter: A Python executable.
    :return: Whether ``-m pip`` works there.
    :rtype: bool
    """

    code, _ = _run(_pip_command(interpreter, ['--version']), timeout=VERIFY_TIMEOUT)
    return code == 0


def _clear_target(target):
    """
    Empty the dependency folder, so versions cannot stack up.

    Guarded, because this function deletes a tree: it refuses any path that is not inside
    the dependencies root. A wrong path here would delete somebody's work.

    :param str target: The folder to empty.
    :raises ValueError: When the path is not under the dependencies root.
    """

    root = os.path.normpath(platform_paths.dependencies_root())
    resolved = os.path.normpath(os.path.abspath(target))
    if os.path.normcase(resolved) == os.path.normcase(root) \
            or not os.path.normcase(resolved).startswith(os.path.normcase(root) + os.sep):
        raise ValueError('Refusing to empty {}, which is not a dependency folder under {}.'
                         .format(resolved, root))

    if os.path.isdir(resolved):
        shutil.rmtree(resolved)
    os.makedirs(resolved)


def verify(interpreter, target, imports):
    """
    Prove the packages are importable by that DCC's own interpreter.

    This is the check the old launcher did not have. A folder named ``numpy`` proves
    somebody started an install; importing numpy proves it finished, matches this
    interpreter's ABI, and is not a half-written tree.

    :param str interpreter: The DCC's Python executable.
    :param str target: The dependency folder to put on the path.
    :param list(str) imports: Module names to import.
    :return: ``{'ok': bool, 'imported': [...], 'missing': {name: reason}}``
    :rtype: dict
    """

    wanted = sorted(set(imports))
    if not wanted:
        return {'ok': True, 'imported': [], 'missing': {}}

    # Printed one line per module, parsed back here. Running them in one interpreter keeps
    # this to a single start-up, which matters: mayapy takes a second or two to boot.
    code = (
        'import importlib, sys\n'
        'for name in {names!r}:\n'
        '    try:\n'
        '        importlib.import_module(name)\n'
        '    except Exception as error:\n'
        '        print("MISSING", name, type(error).__name__, error)\n'
        '    else:\n'
        '        print("OK", name)\n'
    ).format(names=wanted)

    environment = os.environ.copy()
    environment['PYTHONPATH'] = target
    # The DCC's own site-packages still win, which is deliberate: if Maya ships numpy, that
    # is the numpy the framework will use, and this check should agree with reality.
    process = subprocess.run([interpreter, '-c', code], capture_output=True, text=True,
                             timeout=VERIFY_TIMEOUT, env=environment, errors='replace')

    imported = []
    missing = {}
    for line in (process.stdout or '').splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0] == 'OK':
            imported.append(parts[1])
        elif len(parts) >= 2 and parts[0] == 'MISSING':
            missing[parts[1]] = parts[2] if len(parts) > 2 else 'could not be imported'

    if not imported and not missing:
        missing['(the check itself)'] = (
            'The import check produced no output. Exit code {}. {}'
            .format(process.returncode, (process.stderr or '').strip()[-400:]))

    return {'ok': not missing, 'imported': imported, 'missing': missing}


def remove_distribution(target, name):
    """
    Take one package out of a dependency folder, so a different version can replace it.

    ``pip install --target`` never uninstalls: it writes over what is there and leaves the
    rest, so a downgrade would otherwise keep the old dist-info and any file the new version
    does not have.

    :param str target: The dependency folder.
    :param str name: The distribution name.
    """

    for entry in sorted(os.listdir(target)) if os.path.isdir(target) else []:
        lowered = entry.lower()
        if lowered == name or lowered.startswith(name + '-') or lowered.startswith(name + '.'):
            path = os.path.join(target, entry)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except OSError as error:
                logger.warning('Could not remove %s: %s', path, error)


def recover_stable_abi(interpreter, target, wanted, missing, say):
    """
    Try an older build of anything that installed but could not load its extension.

    Called only with what the import check actually rejected. A package whose reason does not
    look like a DLL that will not load is left alone: this is a fix for one specific,
    measured failure, not a general "try an older version and hope".

    :param str interpreter: The DCC's Python executable.
    :param str target: The dependency folder.
    :param list(str) wanted: The requirement lines that were installed.
    :param dict missing: ``{import name: reason}`` from :func:`verify`.
    :param callable say: Where to report.
    :return: ``{import name: the requirement that was installed instead}`` for what was
        recovered.
    :rtype: dict
    """

    by_import = {import_name(line): requirement_name(line) for line in wanted}
    attempts = {}
    for name, reason in sorted(missing.items()):
        if ABI3_SYMPTOM not in str(reason).lower():
            continue
        distribution = by_import.get(name, name)
        pin = ABI3_FALLBACKS.get(distribution)
        if pin:
            attempts[name] = pin

    if not attempts:
        return {}

    recovered = {}
    for name, pin in sorted(attempts.items()):
        say('{} installed, but its extension will not load in this interpreter: it has no '
            'python3.dll, which a stable-ABI wheel links against. Trying {}, the last build '
            'with a wheel for this exact Python.'.format(name, pin))
        remove_distribution(target, requirement_name(pin))
        code, _ = _run(_pip_command(interpreter, ['install', '--no-cache-dir',
                                                  '--no-warn-script-location',
                                                  '--target', target, pin]), progress=None)
        if code != 0:
            say('  {} would not install either.'.format(pin))
            continue
        proof = verify(interpreter, target, [name])
        if proof['ok']:
            say('  {} imports now.'.format(name))
            recovered[name] = pin
        else:
            say('  {} still does not import: {}'
                .format(name, proof['missing'].get(name, 'no reason given')))
    return recovered


def install(dcc, version, framework_path, interpreter, progress=None):
    """
    Install this DCC version's dependencies, from scratch.

    Whole-file first, and on failure one requirement at a time - so a package that has no
    wheel for this interpreter costs its own line in the report instead of taking the other
    fourteen down with it. Maya 2022 is the case that needs it: Python 3.7, where the AI
    packages cannot install and the rest can.

    :param str dcc: DCC name.
    :param str version: DCC version.
    :param str framework_path: The packages folder.
    :param str interpreter: The DCC's Python executable.
    :param callable progress: Called with progress lines. May be None.
    :return: What happened, including ``ok``, ``skipped`` and ``message``.
    :rtype: dict
    """

    def say(text):
        logger.info(text)
        if progress:
            progress(text)

    if not interpreter or not os.path.isfile(interpreter):
        raise ValueError('Cannot install dependencies for {} {}: its Python interpreter was '
                         'not found ({}). Is that version installed?'
                         .format(dcc, version, interpreter or 'no path'))

    requirements = requirements_path(framework_path)
    everything = parse_requirements(read_text(requirements))
    wanted, dropped = dcc_requirements(everything)
    if not wanted:
        raise ValueError('{} lists no requirements to install.'.format(requirements))

    target = target_folder(dcc, version)
    say('Installing {} package(s) for {} {} into {}'
        .format(len(wanted), dcc, version, target))
    if dropped:
        say('Skipping {} - {} provides its own Qt.'
            .format(', '.join(requirement_name(one) for one in dropped), dcc))

    if not has_pip(interpreter):
        say('pip is not available in that interpreter; bootstrapping it.')
        code, output = _run([interpreter, '-m', 'ensurepip', '--upgrade'], progress=progress,
                            timeout=VERIFY_TIMEOUT)
        if code != 0 or not has_pip(interpreter):
            raise ValueError('{} {} has no working pip, and ensurepip did not fix it. '
                             'Install pip for {} and try again.\n{}'
                             .format(dcc, version, interpreter, output[-600:]))

    _clear_target(target)

    listing = os.path.join(target, INSTALLED_REQUIREMENTS)
    with open(listing, 'w', encoding='utf-8', newline='\n') as opened:
        opened.write('# Written by the MCA launcher from {}\n'.format(requirements))
        opened.write('# Qt is excluded: {} ships its own.\n'.format(dcc))
        opened.write('\n'.join(wanted) + '\n')

    base = ['install', '--upgrade', '--no-cache-dir', '--no-warn-script-location',
            '--target', target]
    code, output = _run(_pip_command(interpreter, base + ['-r', listing]), progress=progress)

    skipped = []
    if code != 0:
        say('The whole list did not install. Trying one package at a time to find out '
            'which ones this Python cannot take.')
        for line in wanted:
            one_code, one_output = _run(_pip_command(interpreter, base + [line]),
                                        progress=progress)
            if one_code != 0:
                reason = _pip_reason(one_output)
                skipped.append({'requirement': line, 'reason': reason})
                say('  skipped {} - {}'.format(line, reason))

    imports = sorted({import_name(one) for one in wanted}
                     - {import_name(one['requirement']) for one in skipped})
    checked = verify(interpreter, target, imports)

    # Something installed and then would not load. For the one cause that has actually been
    # measured - a stable-ABI extension in an interpreter with no python3.dll - there is a
    # build that works, and using it beats refusing to start the DCC at all.
    pinned = recover_stable_abi(interpreter, target, wanted, checked['missing'], say)
    for name in pinned:
        checked['missing'].pop(name, None)
        if name not in checked['imported']:
            checked['imported'].append(name)
    checked['imported'].sort()
    checked['ok'] = not checked['missing']

    fatal = sorted(name for name in checked['missing'] if name in CORE_IMPORTS)
    ok = not fatal

    stamp = {
        'stamp_version': STAMP_VERSION,
        'dcc': dcc,
        'version': str(version),
        'interpreter': interpreter,
        'python': _interpreter_version(interpreter),
        'requirements_file': requirements,
        'fingerprint': fingerprint(wanted),
        'installed_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'verified': bool(ok),
        'imported': checked['imported'],
        'missing': checked['missing'],
        'skipped': skipped,
        'pinned': pinned,
        'qt_excluded': [requirement_name(one) for one in dropped],
        'launcher': _launcher_version(),
    }
    fileio.write_json(stamp, stamp_path(target))

    if ok:
        message = ('{} {} is ready: {} package(s) installed into {}.'
                   .format(dcc, version, len(checked['imported']), target))
        if skipped:
            message += (' {} package(s) had no version for Python {} and were skipped: {}.'
                        .format(len(skipped), stamp['python'],
                                ', '.join(one['requirement'] for one in skipped)))
        if pinned:
            message += (' {} had to fall back to an older build this interpreter can load: '
                        '{}.'.format(', '.join(sorted(pinned)),
                                     ', '.join(sorted(pinned.values()))))
    else:
        message = ('{} {} is not ready. These are needed and could not be imported: {}. '
                   'The log has pip\'s output; the folder is {}.'
                   .format(dcc, version, ', '.join(fatal), target))

    return {'ok': ok, 'target': target, 'skipped': skipped, 'missing': checked['missing'],
            'imported': checked['imported'], 'stamp': stamp, 'message': message}


def ensure(dcc, version, framework_path, interpreter, progress=None, force=False):
    """
    Make sure this DCC version has its dependencies, installing them if it does not.

    This is the one function every launch path goes through. It is cheap when there is
    nothing to do: a stamp read and a hash compare, no interpreter started.

    :param str dcc: DCC name.
    :param str version: DCC version.
    :param str framework_path: The packages folder.
    :param str interpreter: The DCC's Python executable.
    :param callable progress: Called with progress lines. May be None.
    :param bool force: Reinstall even when the stamp says it is fine.
    :return: What happened, including ``ok``, ``installed`` and ``message``.
    :rtype: dict
    """

    current = status(dcc, version, framework_path)
    if current['satisfied'] and not force:
        return {'ok': True, 'installed': False, 'target': current['target'],
                'skipped': current['skipped'], 'message': current['reason']}

    if progress:
        progress(current['reason'] if not force else 'Reinstalling on request.')

    outcome = install(dcc, version, framework_path, interpreter, progress=progress)
    outcome['installed'] = True
    return outcome


# ---------------------------------------------------------------------------- #
# Small helpers
# ---------------------------------------------------------------------------- #
def _pip_reason(output):
    """
    Pull the one useful line out of pip's output.

    :param str output: Everything pip said.
    :return: A short reason.
    :rtype: str
    """

    for line in reversed((output or '').splitlines()):
        line = line.strip()
        if line.startswith('ERROR:'):
            return line[6:].strip()[:220]
    tail = (output or '').strip().splitlines()
    return tail[-1][:220] if tail else 'pip failed with no output'


def _interpreter_version(interpreter):
    """
    :param str interpreter: A Python executable.
    :return: Its version, for example '3.11.4', or '' when it cannot be asked.
    :rtype: str
    """

    try:
        process = subprocess.run([interpreter, '-c',
                                  'import sys; print(".".join(map(str, sys.version_info[:3])))'],
                                 capture_output=True, text=True, timeout=VERIFY_TIMEOUT)
        return (process.stdout or '').strip()
    except Exception as error:
        logger.warning('Could not ask %s for its version: %s', interpreter, error)
        return ''


def _launcher_version():
    """
    :return: This launcher's version, for the stamp.
    :rtype: str
    """

    try:
        from mca import launcher
        return getattr(launcher, '__version__', '')
    except Exception:
        return ''
