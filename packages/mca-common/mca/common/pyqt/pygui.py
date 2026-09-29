"""
One place that knows which Qt this DCC has.

Maya 2022 and 2024 and MotionBuilder ship PySide2; Maya 2025 and 2026 ship PySide6; a
standalone script may have either or neither. Every module that draws anything imports from
here instead of choosing for itself, so the choice is made once and the rest of the framework
does not care.

The version this replaces did the same thing and then, when neither was importable, handed
back a stub that raised ``AttributeError`` for every attribute. That turns "there is no Qt
here" into ``AttributeError: QWidget`` somewhere far away. This one says what is actually
wrong, and :data:`AVAILABLE` lets anything that can carry on without a window do so.
"""

# python imports
import logging


logger = logging.getLogger('MCA')

#: Which binding was found: 'PySide6', 'PySide2' or ''.
BINDING = ''

#: Whether there is a Qt here at all.
AVAILABLE = False


class _Missing(object):
    """
    Stands in for a Qt module that is not here, and says so when it is used.

    Importing ``pygui`` must not raise - a command line tool, a farm job and the test suite
    all import modules that import this - but using it should not be mysterious either.
    """

    def __init__(self, name):
        self._name = name

    def __getattr__(self, item):
        raise ImportError(
            'This needs Qt, and neither PySide6 nor PySide2 could be imported here '
            '({}.{}). Inside a DCC that means its own Qt is not on the path; outside one, '
            'pip install PySide6.'.format(self._name, item))

    def __bool__(self):
        return False

    __nonzero__ = __bool__


try:
    from PySide6 import QtCore as qtcore
    from PySide6 import QtGui as qtgui
    from PySide6 import QtUiTools as qtuitools
    from PySide6 import QtWidgets as qtwidgets
    import shiboken6 as shiboken

    BINDING = 'PySide6'
    AVAILABLE = True
except ImportError:
    try:
        from PySide2 import QtCore as qtcore
        from PySide2 import QtGui as qtgui
        from PySide2 import QtUiTools as qtuitools
        from PySide2 import QtWidgets as qtwidgets
        import shiboken2 as shiboken

        BINDING = 'PySide2'
        AVAILABLE = True
    except ImportError:
        qtcore = _Missing('QtCore')
        qtgui = _Missing('QtGui')
        qtuitools = _Missing('QtUiTools')
        qtwidgets = _Missing('QtWidgets')
        shiboken = _Missing('shiboken')


def exec_dialog(dialog):
    """
    Show a modal dialog, whichever binding this is.

    PySide2 spells it ``exec_``; PySide6 spells it ``exec`` and keeps ``exec_`` only as a
    deprecated alias that has already been dropped once. Written out here rather than at
    every call site.

    :param dialog: A QDialog.
    :return: Its result code.
    :rtype: int
    """

    runner = getattr(dialog, 'exec', None) or getattr(dialog, 'exec_', None)
    if runner is None:
        raise ImportError('That dialog cannot be shown: no exec on {}.'
                          .format(type(dialog).__name__))
    return runner()
