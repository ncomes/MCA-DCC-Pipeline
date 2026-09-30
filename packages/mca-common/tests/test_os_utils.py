"""
The three modules that talk to the machine: processes, sounds, and ffmpeg.

    python tests/test_os_utils.py

None of them can be exercised for real on a build machine - there may be no psutil, there is
no winsound off Windows, and nobody wants a test suite that installs ffmpeg - so the parts
that reach outside are stood in for, and what is checked is the code around them: what is
answered when the thing is missing, and exactly what gets handed to it when it is there.
"""

# python imports
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.utils import process, sounds, video_utils  # noqa: E402


class FakeProcess(object):
    """Something with an ``info`` dict, which is all find_by_name looks at."""

    def __init__(self, name):
        self.info = {'name': name}


class Refuses(object):
    """A process that will not say what it is, the way Windows refuses about its own."""

    def __init__(self, error):
        self._error = error

    @property
    def info(self):
        raise self._error


class FakeWinsound(object):
    """Stands in for winsound, recording what it was asked to play."""

    MB_OK = 0
    MB_ICONHAND = 16
    MB_ICONQUESTION = 32
    MB_ICONEXCLAMATION = 48
    MB_ICONASTERISK = 64
    SND_FILENAME = 0x00020000
    SND_ASYNC = 0x0001
    SND_NODEFAULT = 0x0002

    def __init__(self):
        self.beeps = []
        self.files = []

    def MessageBeep(self, flag):                                     # noqa: N802
        self.beeps.append(flag)

    def PlaySound(self, path, flags):                                # noqa: N802
        self.files.append((path, flags))


def body(suite):
    # ---------------------------------------------------------------- #
    # process: the no-psutil answer was False where a list was promised
    # ---------------------------------------------------------------- #
    # get_processes_by_name and kill_processes_by_name both answered False when psutil was
    # missing, while their docstrings promised a list - so the caller's `for p in ...` raised
    # TypeError on the machine the guard was written to protect.
    was_available = process.PSUTIL_AVAILABLE
    try:
        process.PSUTIL_AVAILABLE = False
        suite.check('with no psutil, looking for a process answers an empty list',
                    process.find_by_name('cm.exe') == [],
                    repr(process.find_by_name('cm.exe')))
        suite.check('and asking whether it is running answers False, not raising',
                    process.is_running('cm.exe') is False)
    finally:
        process.PSUTIL_AVAILABLE = was_available

    suite.check('and available() says which of the two it is',
                process.available() is process.PSUTIL_AVAILABLE)

    # A process list read on Windows raises AccessDenied about system processes as a matter
    # of course. check_if_process_is_running caught that; get_processes_by_name, the one
    # anything actually called, did not.
    class FakePsutil(object):
        NoSuchProcess = type('NoSuchProcess', (Exception,), {})
        AccessDenied = type('AccessDenied', (Exception,), {})
        ZombieProcess = type('ZombieProcess', (Exception,), {})

        def __init__(self, processes):
            self._processes = processes

        def process_iter(self, attributes=None):
            return list(self._processes)

    fake = FakePsutil([])
    fake._processes = [FakeProcess('cm.exe'),
                       Refuses(FakePsutil.AccessDenied('System')),
                       FakeProcess('maya.exe'),
                       FakeProcess('CM.EXE'),
                       FakeProcess(None)]

    real_psutil, real_transient, real_flag = process.psutil, process._TRANSIENT, process.PSUTIL_AVAILABLE
    try:
        process.psutil = fake
        process._TRANSIENT = (FakePsutil.NoSuchProcess, FakePsutil.AccessDenied, FakePsutil.ZombieProcess)
        process.PSUTIL_AVAILABLE = True

        found = process.find_by_name('cm.exe')
        suite.check('a process that refuses to be named is stepped over, not raised',
                    len(found) == 2, str(len(found)))
        suite.check('and the match ignores case',
                    all((p.info['name'] or '').lower() == 'cm.exe' for p in found))
        suite.check('an exact match does not answer a longer name',
                    process.find_by_name('cm') == [])
        suite.check('and asking for it anywhere in the name does',
                    len(process.find_by_name('cm', exact=False)) == 2)
        suite.check('a nameless process is not a match for the empty string',
                    process.find_by_name('') == [])
        suite.check('is_running is the same question, answered yes or no',
                    process.is_running('maya.exe') and not process.is_running('houdini.exe'))
    finally:
        process.psutil, process._TRANSIENT, process.PSUTIL_AVAILABLE = real_psutil, real_transient, real_flag

    # ---------------------------------------------------------------- #
    # process: a thread that dies silently
    # ---------------------------------------------------------------- #
    # cpu_threading started a non-daemon thread with nothing catching exceptions and returned
    # nothing, so a failure printed to a stream nobody reads and the caller could not wait.
    ran = []
    thread = process.run_on_thread(lambda: ran.append(1))
    suite.check('running something on a thread hands back the thread',
                hasattr(thread, 'join'), repr(thread))
    thread.join(5)
    suite.check('so the caller can wait for it, and it ran', ran == [1])
    suite.check('and it is a daemon, so it cannot hold the application open',
                thread.daemon)

    def explodes():
        raise ValueError('boom')

    failing = process.run_on_thread(explodes, name='on purpose')
    failing.join(5)
    suite.check('a background job that fails does not take the thread with it silently',
                not failing.is_alive())

    # ---------------------------------------------------------------- #
    # sounds: no files, and nothing raises where there is no winsound
    # ---------------------------------------------------------------- #
    was_winsound, real_module = sounds.WINSOUND_AVAILABLE, sounds.winsound
    try:
        sounds.WINSOUND_AVAILABLE = False
        suite.check('off Windows, a cue is silence rather than an error',
                    sounds.play_sound('warning') is False and
                    sounds.warning() is False and
                    sounds.tada() is False)
        suite.check('and so is a sound file',
                    sounds.play_file('tada.wav') is False)
    finally:
        sounds.WINSOUND_AVAILABLE, sounds.winsound = was_winsound, real_module

    stand_in = FakeWinsound()
    real_cues = sounds.SYSTEM_CUES
    try:
        sounds.winsound = stand_in
        sounds.WINSOUND_AVAILABLE = True
        sounds.SYSTEM_CUES = {
            'warning': stand_in.MB_ICONEXCLAMATION,
            'critical': stand_in.MB_ICONHAND,
            'error': stand_in.MB_ICONHAND,
            'question': stand_in.MB_ICONQUESTION,
            'ding': stand_in.MB_ICONASTERISK,
            'notify': stand_in.MB_ICONASTERISK,
            'ok': stand_in.MB_OK,
        }

        suite.check('a warning is the machine\'s own warning sound, no file involved',
                    sounds.warning() and stand_in.beeps == [stand_in.MB_ICONEXCLAMATION],
                    str(stand_in.beeps))
        stand_in.beeps = []
        suite.check('critical and ding are the machine\'s too',
                    sounds.critical() and sounds.ding() and
                    stand_in.beeps == [stand_in.MB_ICONHAND, stand_in.MB_ICONASTERISK],
                    str(stand_in.beeps))
        suite.check('the cue name is not case sensitive',
                    sounds.play_sound('WARNING'))

        # A project file, which is the only thing that has to come off disk.
        wav = os.path.join(suite.temp, 'tada.wav')
        with open(wav, 'wb') as opened:
            opened.write(b'RIFF')
        stand_in.files = []
        suite.check('a project sound is played as a file name, not looked up as an alias',
                    sounds.play_file(wav) and
                    stand_in.files[0][0] == wav and
                    stand_in.files[0][1] & stand_in.SND_FILENAME,
                    str(stand_in.files))
        suite.check('and asked not to substitute a default when it cannot be read',
                    stand_in.files[0][1] & stand_in.SND_NODEFAULT)

        suite.check('a file that is not there is silence, not a raise',
                    sounds.play_file(os.path.join(suite.temp, 'missing.wav')) is False)

        os.environ.pop('MCA_COMMON_PATH', None)
        suite.check('and with no sounds folder set, a bare file name is not guessed at',
                    sounds.play_file('tada.wav') is False)

        stand_in.beeps = []
        suite.check('tada falls back to a plain beep, so something is always heard',
                    sounds.tada() and stand_in.beeps == [stand_in.MB_OK],
                    str(stand_in.beeps))
    finally:
        sounds.winsound, sounds.WINSOUND_AVAILABLE, sounds.SYSTEM_CUES = (real_module, was_winsound,
                                                                         real_cues)

    # ---------------------------------------------------------------- #
    # video: finding ffmpeg
    # ---------------------------------------------------------------- #
    pretend = os.path.join(suite.temp, 'ffmpeg.exe')
    with open(pretend, 'w', encoding='utf-8') as opened:
        opened.write('not really ffmpeg')

    was_variable = os.environ.get(video_utils.FFMPEG_VARIABLE)
    try:
        os.environ[video_utils.FFMPEG_VARIABLE] = pretend
        suite.check('MCA_FFMPEG_EXE wins when it points at a file that is there',
                    video_utils.ffmpeg_exe() == os.path.normpath(pretend),
                    video_utils.ffmpeg_exe())
        os.environ[video_utils.FFMPEG_VARIABLE] = os.path.join(suite.temp, 'nope.exe')
        suite.check('and is ignored when it does not, rather than failing on it',
                    video_utils.ffmpeg_exe() != os.path.join(suite.temp, 'nope.exe'))
        os.environ.pop(video_utils.FFMPEG_VARIABLE)
        suite.check('with nothing set and no ffmpeg about, the answer is empty, not a raise',
                    isinstance(video_utils.ffmpeg_exe(), str))
    finally:
        if was_variable is None:
            os.environ.pop(video_utils.FFMPEG_VARIABLE, None)
        else:
            os.environ[video_utils.FFMPEG_VARIABLE] = was_variable

    suite.check('a source that is not there is refused before ffmpeg is looked for',
                'no video' in suite.raises('converting nothing raises',
                                           video_utils.ffmpeg_convert_to_mp4,
                                           os.path.join(suite.temp, 'missing.mov')).lower())

    source = os.path.join(suite.temp, 'shot 01 playblast.mov')
    with open(source, 'w', encoding='utf-8') as opened:
        opened.write('pretend video')

    real_exe = video_utils.ffmpeg_exe
    try:
        video_utils.ffmpeg_exe = lambda: ''
        message = suite.raises('with no ffmpeg anywhere, converting says so',
                               video_utils.ffmpeg_convert_to_mp4, source)
        suite.check('and the message says how to point at one',
                    video_utils.FFMPEG_VARIABLE in message, message)
    finally:
        video_utils.ffmpeg_exe = real_exe

    # ---------------------------------------------------------------- #
    # video: the space in the path that broke every conversion
    # ---------------------------------------------------------------- #
    # The version this replaces formatted one string and ran it with shell=True, so
    # 'shot 01 playblast.mov' arrived as three arguments.
    recorded = {}

    class Result(object):
        returncode = 0
        stdout = ''

    def fake_run(command, **kwargs):
        recorded['command'] = command
        recorded['kwargs'] = kwargs
        with open(command[-1], 'w', encoding='utf-8') as opened:
            opened.write('converted')
        return Result()

    real_run, real_finder = subprocess.run, video_utils.ffmpeg_exe
    try:
        subprocess.run = fake_run
        video_utils.ffmpeg_exe = lambda: pretend
        written = video_utils.ffmpeg_convert_to_mp4(source)

        suite.check('the output lands beside the source, named for it',
                    written == os.path.splitext(source)[0] + '.mp4', written)
        suite.check('ffmpeg is handed a list of arguments, so a space stays inside one',
                    isinstance(recorded['command'], list) and source in recorded['command'],
                    repr(recorded['command'])[:200])
        suite.check('and no shell is involved',
                    not recorded['kwargs'].get('shell'))
        suite.check('it is told to overwrite, rather than waiting for an answer nobody types',
                    '-y' in recorded['command'])
        suite.check('and ffmpeg is asked not to flash a console window up',
                    'creationflags' in recorded['kwargs'])

        # The old version ignored the exit code and then complained about the output file.
        class Failed(object):
            returncode = 1
            stdout = 'Invalid data found when processing input'

        def failing_run(command, **kwargs):
            return Failed()

        subprocess.run = failing_run
        message = suite.raises('a conversion that fails raises',
                               video_utils.ffmpeg_convert_to_mp4, source)
        suite.check('and points at the log rather than blaming the missing output',
                    'log' in message.lower(), message)

        def silent_run(command, **kwargs):
            return Result()

        subprocess.run = silent_run
        out = os.path.join(suite.temp, 'not written.mp4')
        suite.raises('ffmpeg claiming success with no file is still a failure',
                     video_utils.ffmpeg_convert_to_mp4, source, out)

        suite.check('a named output is used as given',
                    isinstance(out, str))
    finally:
        subprocess.run, video_utils.ffmpeg_exe = real_run, real_finder

    # ---------------------------------------------------------------- #
    # video: the real thing, on a machine that has ffmpeg
    # ---------------------------------------------------------------- #
    if video_utils.ffmpeg_exe():
        real_source = os.path.join(suite.temp, 'a real playblast 01.mov')
        made = subprocess.run(
            [video_utils.ffmpeg_exe(), '-y', '-f', 'lavfi', '-i', 'testsrc=duration=1:size=64x64:rate=10',
             '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-shortest', real_source],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        if made.returncode == 0:
            written = video_utils.ffmpeg_convert_to_mp4(real_source)
            suite.check('and a real conversion, through a path with spaces in it, works',
                        os.path.isfile(written) and os.path.getsize(written) > 0, written)
            suite.check('running it again overwrites rather than hanging on a question',
                        video_utils.ffmpeg_convert_to_mp4(real_source) == written)
        else:
            suite.check('and a real conversion, through a path with spaces in it, works',
                        True, 'skipped: ffmpeg could not make a test video')
    else:
        suite.check('and a real conversion, through a path with spaces in it, works',
                    True, 'skipped: no ffmpeg on this machine')

    suite.note('psutil on this machine', process.PSUTIL_AVAILABLE)
    suite.note('winsound on this machine', sounds.WINSOUND_AVAILABLE)
    suite.note('ffmpeg on this machine', video_utils.ffmpeg_exe() or 'none')


if __name__ == '__main__':
    sys.exit(harness.run('os_utils', body))
