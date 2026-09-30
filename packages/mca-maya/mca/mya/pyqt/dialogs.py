"""
Asking the user something, and telling them something, from inside Maya.

Two kinds of message. The Qt ones - error, info, question - are ``mca-common``'s, so a tool looks
the same in Maya as it does in MotionBuilder or in a standalone window. The in-view message is
Maya's own: a line of text that fades out of the corner of the viewport, which is the right way to
say "that worked" without a dialog somebody has to dismiss.

What was wrong before:

- **``MAYA_MAIN_WINDOW`` was worked out when the module was imported.** A module-level
  ``get_maya_window()`` call, so the value was whatever Maya's main window was the first time
  anything imported this - ``None`` in a batch Maya, and ``None`` in an interactive one too if the
  import happened during start-up, before the window existed. It was then the default parent for
  every dialog. The parent is worked out when a dialog is opened now.
- **A file dialog's style came from an option variable that is often unset.**
  ``pm.optionVar(query='FileDialogStyle')`` answers ``0`` for a variable nobody has written, and
  ``fileDialog2(dialogStyle=0)`` is not a style Maya has - so on a fresh Maya profile the file
  dialogs were being asked for something that does not exist.
- The module docstring said "Helper functions for Blend nodes and shapes".
"""

# python imports

# software specific imports
import maya.cmds as cmds

# mca imports
from mca.common import log
from mca.common.pyqt import messages
from mca.mya.pyqt.utils import ma_main_window


logger = log.MCA_LOGGER

#: What ``fileDialog2`` takes for its style: 1 is the operating system's own dialog, 2 is Maya's.
OS_NATIVE_DIALOG = 1
MAYA_NATIVE_DIALOG = 2

#: The option variable holding which one the user prefers.
DIALOG_STYLE_OPTION_VARIABLE = 'FileDialogStyle'

#: What to show when the caller does not say.
DEFAULT_FILE_FILTERS = ('Maya Files (*.ma *.mb);;Maya ASCII (*.ma);;'
                        'Maya Binary (*.mb);;All Files (*.*)')

#: How long a character of an in-view message stays up for, in milliseconds, and the longest any
#: message stays up however much of it there is.
FADE_TIME_PER_CHARACTER = 110
MAXIMUM_FADE_TIME = 10000

#: The colours an in-view message is written in.
VIEW_MESSAGE_COLOURS = {
    'good': '#21C4F5',
    'error': '#f52121',
}


def maya_main_window():
    """
    Maya's main window, to parent a dialog to.

    Asked for when a dialog is opened, not when this module is imported - the version this replaces
    read it once at import time and handed the same answer out forever, which in a batch Maya, or
    during start-up, is ``None``.

    :return: The window, or None.
    :rtype: qtwidgets.QWidget or None
    """

    return ma_main_window.get_maya_window()


def display_view_message(text='No text given', mode='good', header='', fade_time=None):
    """
    Write a line in the corner of the viewport and let it fade.

    :param str text: What to say.
    :param str mode: ``'good'`` or ``'error'``, which decides the colour.
    :param str header: Written before the message, in the same colour.
    :param float fade_time: How long it stays up, in milliseconds. Worked out from the length of
        the message otherwise, so a long one is up long enough to read.
    :return: Whether it was shown - a batch Maya has no viewport to write in.
    :rtype: bool
    """

    if cmds.about(batch=True):
        logger.debug('No viewport to write "%s" in.', text)
        return False

    if fade_time is None:
        fade_time = min(len(text) * FADE_TIME_PER_CHARACTER, MAXIMUM_FADE_TIME)

    colour = VIEW_MESSAGE_COLOURS.get(mode, VIEW_MESSAGE_COLOURS['good'])
    cmds.inViewMessage(
        assistMessage='<span style="color:{};">{}:</span> {}'.format(colour, header, text),
        position='topRight', fade=True, fadeStayTime=fade_time)
    return True


def error_prompt(title, text, detail_text=None, style=None, sound=None,
                 icon=r'color\error.png', parent=None):
    """
    Tell the user something went wrong.

    :param str title: The window's title.
    :param str text: What happened.
    :param str detail_text: The long version, behind a "show details" button.
    :param style: A stylesheet, or None for the pipeline's.
    :param sound: A sound to play, or None.
    :param str icon: The icon beside the message.
    :param parent: The window to sit on. Maya's main window otherwise.
    :return: Which button was pressed.
    """

    return messages.error_message(title=title, text=text, detail_text=detail_text, style=style,
                                  sound=sound, icon=icon, parent=parent or maya_main_window())


def info_prompt(title, text, detail_text=None, style=None, sound=None,
                icon=r'color\info.png', parent=None):
    """
    Tell the user something.

    :param str title: The window's title.
    :param str text: What to say.
    :param str detail_text: The long version, behind a "show details" button.
    :param style: A stylesheet, or None for the pipeline's.
    :param sound: A sound to play, or None.
    :param str icon: The icon beside the message.
    :param parent: The window to sit on. Maya's main window otherwise.
    :return: Which button was pressed.
    """

    return messages.info_message(title=title, text=text, detail_text=detail_text, style=style,
                                 sound=sound, icon=icon, parent=parent or maya_main_window())


def question_prompt(title, text, detail_text=None, style=None, sound=None,
                    icon=r'color\question.png', parent=None):
    """
    Ask the user something.

    :param str title: The window's title.
    :param str text: The question.
    :param str detail_text: The long version, behind a "show details" button.
    :param style: A stylesheet, or None for the pipeline's.
    :param sound: A sound to play, or None.
    :param str icon: The icon beside the message.
    :param parent: The window to sit on. Maya's main window otherwise.
    :return: Which button was pressed.
    """

    return messages.question_message(title=title, text=text, detail_text=detail_text, style=style,
                                     sound=sound, icon=icon, parent=parent or maya_main_window())


def file_dialog_style(dialog_style=None):
    """
    Which file dialog to show: the operating system's, or Maya's.

    :param int dialog_style: What the caller asked for, or None to use the user's preference.
    :return: 1 or 2. Never 0, which is what an unwritten option variable answers and is not a style
        ``fileDialog2`` has.
    :rtype: int
    """

    if dialog_style in (OS_NATIVE_DIALOG, MAYA_NATIVE_DIALOG):
        return dialog_style

    preferred = cmds.optionVar(query=DIALOG_STYLE_OPTION_VARIABLE)
    if preferred in (OS_NATIVE_DIALOG, MAYA_NATIVE_DIALOG):
        return preferred
    return OS_NATIVE_DIALOG


def open_file_dialog(title, filters=None, start_dir=None, dialog_style=None):
    """
    Ask the user to pick a file that is already there.

    :param str title: The dialog's title.
    :param str filters: What to show, in Maya's filter format.
    :param str start_dir: The folder to open in.
    :param int dialog_style: 1 for the operating system's dialog, 2 for Maya's. The user's
        preference otherwise.
    :return: The file they picked, or '' when they cancelled.
    :rtype: str
    """

    picked = cmds.fileDialog2(fileFilter=filters or DEFAULT_FILE_FILTERS,
                              dialogStyle=file_dialog_style(dialog_style),
                              fileMode=1, dir=start_dir, caption=title)
    return picked[0] if picked else ''


def save_file_dialog(title, filters=None, start_dir=None, dialog_style=None):
    """
    Ask the user where to save a file.

    :param str title: The dialog's title.
    :param str filters: What to show, in Maya's filter format.
    :param str start_dir: The folder to open in.
    :param int dialog_style: 1 for the operating system's dialog, 2 for Maya's. The user's
        preference otherwise.
    :return: The file they chose, or '' when they cancelled.
    :rtype: str
    """

    picked = cmds.fileDialog2(fileFilter=filters or DEFAULT_FILE_FILTERS,
                              dialogStyle=file_dialog_style(dialog_style),
                              fileMode=0, dir=start_dir, caption=title,
                              okCaption='Save')
    return picked[0] if picked else ''
