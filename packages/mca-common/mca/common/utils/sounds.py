"""
The small noises a tool makes: a warning, an error, "your export finished".

**No sound files are bundled.** The version this replaces played eight ``.wav`` files out of
a depot folder, six of them Windows' own system sounds copied in - ``Windows Error.wav``,
``Windows Critical Stop.wav``, ``Windows Ding.wav`` and so on - which is the same licence
problem as the icons and, for those six, unnecessary: Windows will play the user's own sound
scheme if you ask it to, and will stay quiet if they have turned sounds off. That is what the
named cues below do, and they need nothing on disk.

A project that wants its own sound puts a file in the shared sounds folder and passes its name
to :func:`play_sound`. A missing file is silence, not an error: a tool must never fail because
it could not make a noise.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common.paths import paths


logger = log.MCA_LOGGER

try:
    import winsound

    WINSOUND_AVAILABLE = True
except ImportError:
    winsound = None
    WINSOUND_AVAILABLE = False

#: The cues Windows already has a sound for, mapped to the MessageBeep flag that plays it.
#: These respect the machine's sound scheme, including having been muted.
SYSTEM_CUES = {}
if WINSOUND_AVAILABLE:
    SYSTEM_CUES = {
        'warning': winsound.MB_ICONEXCLAMATION,
        'critical': winsound.MB_ICONHAND,
        'error': winsound.MB_ICONHAND,
        'question': winsound.MB_ICONQUESTION,
        'ding': winsound.MB_ICONASTERISK,
        'notify': winsound.MB_ICONASTERISK,
        'ok': winsound.MB_OK,
    }


def play_sound(sound):
    """
    Play a cue by name, or a sound file out of the shared sounds folder.

    :param str sound: One of the names in :data:`SYSTEM_CUES` - ``'warning'``,
        ``'critical'``, ``'ding'``, ``'notify'`` - or the name of a file in the project's
        sounds folder, or a full path to one.
    :return: True when something was played.
    :rtype: bool

    The version this replaces handed the string straight to ``PlaySound`` without
    ``SND_FILENAME``, so Windows looked the name up as a *registry sound alias* first and
    only then as a file, and with the sounds folder unset it was passed a bare file name -
    so what an artist heard depended on the machine.
    """

    if not WINSOUND_AVAILABLE or not sound:
        return False

    key = str(sound).lower()
    if key in SYSTEM_CUES:
        winsound.MessageBeep(SYSTEM_CUES[key])
        return True

    return play_file(sound)


def play_file(file_name):
    """
    Play a ``.wav`` from the project's sounds folder.

    :param str file_name: A file name, or a full path.
    :return: True when the file was there and was played.
    :rtype: bool
    """

    if not WINSOUND_AVAILABLE or not file_name:
        return False

    path = file_name
    if not os.path.isabs(path):
        folder = paths.get_common_sounds()
        if not folder:
            logger.debug('No sounds folder is set, so "%s" was not played.', file_name)
            return False
        path = os.path.join(folder, file_name)

    if not os.path.isfile(path):
        logger.debug('No sound file at "%s".', path)
        return False

    try:
        # SND_FILENAME says this is a file and not an alias; SND_NODEFAULT keeps Windows
        # from substituting its default ding when it cannot read the file.
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except RuntimeError as error:
        logger.debug('Could not play "%s" (%s).', path, error)
        return False

    return True


def warning():
    """
    The machine's warning sound. For a warning, and for a dialog carrying one.
    """

    return play_sound('warning')


def critical():
    """
    The machine's critical-stop sound. For something an artist has to deal with now.
    """

    return play_sound('critical')


def ding():
    """
    A short note, for drawing attention to something small.
    """

    return play_sound('ding')


def notify():
    """
    The same note under the name tools tend to reach for.
    """

    return play_sound('notify')


def tada(file_name='tada.wav'):
    """
    The one cue Windows has no sound for: a long job finished, happily.

    :param str file_name: The file to play, if the project ships one.
    :return: True when it played; when the project ships no such file the machine's plain
        beep stands in, so something is always heard.
    :rtype: bool
    """

    if play_file(file_name):
        return True

    return play_sound('ok')
