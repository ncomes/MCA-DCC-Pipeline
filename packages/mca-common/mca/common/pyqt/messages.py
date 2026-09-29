"""
Asking the artist something, and telling them something.

The version this replaces had four things wrong with it, and one of them loses work:

- **Cancel did not cancel.** ``text_prompt_message`` ended with
  ``return prompt_lineEdit.text() if message_box.result != 'Cancel' else ''`` - and the
  result it compared was the button's own text, which is ``'&Cancel'``, never ``'Cancel'``.
  So pressing Cancel returned whatever had been typed, exactly as if the artist had pressed
  OK, and the caller went ahead and used it.
- **The stylesheet was thrown away.** The box read the project's stylesheet, applied it, and
  then called ``setStyleSheet`` twice more with one-line rules. The last call wins, so every
  message box in the framework has been unstyled since those two lines were added.
- **An error box offered Yes and Cancel.** Yes to what?
- Buttons were reported by their label, with ``'&Yes'`` patched to ``'Yes'`` at one call
  site and not at the others, so a caller comparing to ``'No'`` never matched.

The button constants and the string answers are kept, because tools compare to them. New
code should use :func:`ask`, which answers True or False.
"""

# python imports
from mca.common import log
from mca.common.pyqt import pygui
from mca.common.resources import resources


logger = log.MCA_LOGGER

#: The stylesheet a message box uses when nobody says otherwise.
DEFAULT_STYLE = 'dark_theme'


def _button(name, fallback=0):
    """
    One of QMessageBox's standard buttons, without needing Qt at import time.

    The module this replaces read all twenty at module scope, so importing it on a machine
    with no Qt failed before the first line of any function ran.

    :param str name: The button's name, for example 'Ok'.
    :param int fallback: What to answer when there is no Qt.
    :return: The button value.
    """

    if not pygui.AVAILABLE:
        return fallback
    box = pygui.qtwidgets.QMessageBox
    standard = getattr(box, 'StandardButton', box)
    return getattr(standard, name, getattr(box, name, fallback))


class _Buttons(object):
    """The standard buttons, looked up when they are used rather than when this is imported."""

    def __getattr__(self, item):
        return _button(item)


_buttons = _Buttons()


def __getattr__(name):
    """
    Answer the M_* names the framework uses, without asking Qt for them at import.

    :param str name: An attribute name.
    :return: The button value.
    """

    if name.startswith('M_'):
        wanted = ''.join(part.title() for part in name[2:].split('_'))
        # Ok, YesToAll, NoButton, RestoreDefaults: title case with the underscores removed.
        return _button(wanted)
    raise AttributeError(name)


def clean_label(text):
    """
    :param str text: A button's label, which carries its keyboard mnemonic: ``'&Yes'``.
    :return: The word a caller means: ``'Yes'``.
    :rtype: str
    """

    return str(text or '').replace('&', '').strip()


class MCAMessageBox(pygui.qtwidgets.QMessageBox if pygui.AVAILABLE else object):
    """A message box that looks like the rest of the framework."""

    def __init__(self, title, text, detail_text=None, style=None, sound=None, parent=None):
        """
        :param str title: The window title, without the MCA prefix.
        :param str text: What to say.
        :param str detail_text: More, behind a Details button.
        :param str style: A stylesheet name.
        :param str sound: A sound to play.
        :param parent: The parent widget.
        """

        super(MCAMessageBox, self).__init__(parent=parent)
        self.title = title
        self.result = ''

        if sound:
            self._play(sound)

        # One stylesheet, applied once. The version this replaces applied the project's and
        # then overwrote it twice with one-liners.
        sheet = resources.read_stylesheet(style or DEFAULT_STYLE)
        extra = 'QLabel { min-width: 200px; } QPushButton { padding: 6px 14px; }'
        self.setStyleSheet('{}\n{}'.format(sheet, extra) if sheet else extra)

        self.setWindowTitle('MCA {}'.format(title))
        self.setText(text)
        if detail_text:
            self.setDetailedText(str(detail_text))

        self.buttonClicked.connect(self._button_clicked)

    @staticmethod
    def _play(sound):
        """
        :param str sound: A sound file name. Missing sound support is not worth a failure.
        """

        try:
            from mca.common.utils import sounds

            sounds.play_sound(sound)
        except Exception as error:                                   # noqa: BLE001
            logger.debug('No sound played (%s).', error)

    def _button_clicked(self, button):
        """
        :param button: The button that was pressed.
        """

        self.result = clean_label(button.text())


def _show(box, buttons):
    """
    :param box: The message box.
    :param buttons: The standard buttons to offer.
    :return: Which button was pressed, as a word.
    :rtype: str
    """

    box.setStandardButtons(buttons)
    pygui.exec_dialog(box)
    return box.result


def question_message(title, text, detail_text=None, style=None, sound=None, icon=None,
                     parent=None, tri_option=False):
    """
    Ask a yes or no question.

    :param str title: The window title.
    :param str text: The question.
    :param str detail_text: More, behind a Details button.
    :param str style: A stylesheet name.
    :param str sound: A sound to play.
    :param str icon: An icon name from the resource library.
    :param parent: The parent widget.
    :param bool tri_option: Offer Cancel as well as Yes and No.
    :return: 'Yes', 'No' or 'Cancel'.
    :rtype: str
    """

    box = MCAMessageBox(title, text, detail_text, style, sound, parent)
    _set_icon(box, icon)
    buttons = _buttons.Yes | _buttons.No
    if tri_option:
        buttons = buttons | _buttons.Cancel
    return _show(box, buttons)


def ask(title, text, detail_text=None, parent=None):
    """
    The same question, answered as a bool - which is what a caller actually wants.

    :param str title: The window title.
    :param str text: The question.
    :param str detail_text: More, behind a Details button.
    :param parent: The parent widget.
    :return: True for yes.
    :rtype: bool
    """

    return question_message(title, text, detail_text=detail_text, parent=parent) == 'Yes'


def info_message(title, text, detail_text=None, style=None, sound=None, icon=None,
                 parent=None):
    """
    Tell the artist something.

    :param str title: The window title.
    :param str text: What to say.
    :param str detail_text: More, behind a Details button.
    :param str style: A stylesheet name.
    :param str sound: A sound to play.
    :param str icon: An icon name.
    :param parent: The parent widget.
    :return: 'OK'.
    :rtype: str
    """

    box = MCAMessageBox(title, text, detail_text, style, sound, parent)
    _set_icon(box, icon)
    return _show(box, _buttons.Ok)


def error_message(title, text, detail_text=None, style=None, sound=None, icon=None,
                  parent=None):
    """
    Tell the artist something went wrong.

    :param str title: The window title.
    :param str text: What went wrong.
    :param str detail_text: More, behind a Details button.
    :param str style: A stylesheet name.
    :param str sound: A sound to play. None by default now: every error used to play one.
    :param str icon: An icon name.
    :param parent: The parent widget.
    :return: 'OK'.
    :rtype: str
    """

    box = MCAMessageBox(title, text, detail_text, style, sound, parent)
    _set_icon(box, icon)
    if pygui.AVAILABLE:
        box.setIcon(pygui.qtwidgets.QMessageBox.Critical)
    # Ok, not Yes and Cancel. There was nothing to say yes to.
    return _show(box, _buttons.Ok)


def text_prompt_message(title, text, starting_text=None, detail_text=None, style=None,
                        sound=None, icon=None, parent=None):
    """
    Ask the artist to type something.

    :param str title: The window title.
    :param str text: What to ask for.
    :param str starting_text: What the box starts with.
    :param str detail_text: More, behind a Details button.
    :param str style: A stylesheet name.
    :param str sound: A sound to play.
    :param str icon: An icon name.
    :param parent: The parent widget.
    :return: What was typed, or '' when the artist cancelled - which it now really does.
    :rtype: str
    """

    box = MCAMessageBox(title, text, detail_text, style, sound, parent)
    _set_icon(box, icon)

    field = pygui.qtwidgets.QLineEdit()
    if starting_text:
        field.setText(str(starting_text))
    layout = box.layout()
    layout.addWidget(field, 2, 0, 1, -1)

    box.setStandardButtons(_buttons.Ok | _buttons.Cancel)
    field.setFocus()
    pygui.exec_dialog(box)

    # The old comparison was against 'Cancel' while the result held '&Cancel', so cancelling
    # returned the typed text exactly as if OK had been pressed.
    return '' if box.result in ('Cancel', '') else field.text()


def _set_icon(box, icon):
    """
    :param box: The message box.
    :param str icon: An icon name from the resource library, or None.
    """

    if not icon:
        return
    found = resources.pixmap(icon)
    if found is not None:
        box.setIconPixmap(found)
