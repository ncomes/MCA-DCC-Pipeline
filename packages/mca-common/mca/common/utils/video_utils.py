"""
Turning a playblast into something that can be attached to a ticket: ffmpeg, found and run.

ffmpeg is not bundled - it is GPL, and a studio will already have a copy it is happy with.
:func:`ffmpeg_exe` looks in three places and says which one it used.
"""

# python imports
import os
import shutil
import subprocess

# MCA python imports
from mca.common import log
from mca.common.paths import paths
from mca.common.utils import platforms


logger = log.MCA_LOGGER

#: The environment variable that wins over everything else.
FFMPEG_VARIABLE = 'MCA_FFMPEG_EXE'

#: Keeps a console window from flashing up in front of Maya on every conversion.
_NO_WINDOW = 0x08000000 if platforms.IS_WINDOWS else 0


def ffmpeg_exe():
    """
    Find an ffmpeg to use, in order:

    1. ``MCA_FFMPEG_EXE``, when it points at a file that is there. This is the hook for a
       machine with ffmpeg somewhere of its own.
    2. ``<common tools>/3rdParty/FFmpeg/bin/ffmpeg.exe``, for a project that ships one.
    3. ``ffmpeg`` on ``PATH``.

    :return: The path, or ``''`` when there is none. Nothing raises: a caller may well want
        to offer the artist a different way out.
    :rtype: str
    """

    override = os.environ.get(FFMPEG_VARIABLE, '')
    if override and os.path.isfile(override):
        return os.path.normpath(override)

    common_tools = paths.get_common_tools_path()
    if common_tools:
        name = 'ffmpeg.exe' if platforms.IS_WINDOWS else 'ffmpeg'
        bundled = os.path.normpath(os.path.join(common_tools, '3rdParty', 'FFmpeg', 'bin', name))
        if os.path.isfile(bundled):
            return bundled

    on_path = shutil.which('ffmpeg')
    if on_path:
        return os.path.normpath(on_path)

    return ''


def ffmpeg_convert_to_mp4(source_path, output_path=''):
    """
    Convert a video to an h.264 mp4 beside it.

    :param str source_path: The video to read.
    :param str output_path: Where to write. The source's name with ``.mp4`` by default.
    :return: The file written.
    :rtype: str
    :raises OSError: When the source is not there, when there is no ffmpeg, or when ffmpeg
        fails - in which case what ffmpeg said is in the message and in the log.

    The version this replaces built one long string and ran it with ``shell=True``, so a
    path with a space in it - ``My Documents``, ``shot 01.mov``, most artists' desktops -
    arrived at ffmpeg as two arguments and the conversion failed, or wrote somewhere nobody
    expected. It also ignored ffmpeg's exit code, so the only report of a failure was
    ``FileNotFoundError`` about the output, which said nothing about why.
    """

    if not source_path or not os.path.isfile(source_path):
        raise OSError('There is no video at "{0}".'.format(source_path))

    source_path = os.path.normpath(source_path)
    processed_path = os.path.normpath(output_path or (os.path.splitext(source_path)[0] + '.mp4'))

    executable = ffmpeg_exe()
    if not executable:
        raise OSError(
            'ffmpeg was not found. Set {0} to it, put it on PATH, or ship it at '
            '<common tools>/3rdParty/FFmpeg/bin/.'.format(FFMPEG_VARIABLE))

    command = [
        executable,
        '-y',                       # overwrite, rather than waiting for an answer nobody will type
        '-i', source_path,
        '-c:v', 'libx264',
        '-crf', '19',
        '-preset', 'slow',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-ac', '2',
        processed_path,
    ]
    logger.debug('Converting: %s', ' '.join(command))

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        creationflags=_NO_WINDOW)

    if result.returncode:
        logger.error('ffmpeg said:\n%s', result.stdout)
        raise OSError('Converting "{0}" failed. The log has what ffmpeg said.'.format(source_path))

    if not os.path.isfile(processed_path):
        raise OSError('ffmpeg reported success but "{0}" is not there.'.format(processed_path))

    return processed_path
