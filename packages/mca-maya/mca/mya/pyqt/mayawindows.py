"""
The window classes every Maya tool in the pipeline is built on.

Two things they add to ``mca-common``'s windows. First, they parent themselves to Maya's main
window, so a tool behaves like part of Maya: it stays in front of the viewport, it minimises with
Maya, and it closes when Maya closes rather than leaving a window nobody can get rid of. Second,
they carry :class:`MayaWindowEvents`, which is how a tool listens for the selection changing or a
scene opening - and, just as importantly, how it stops listening when it closes. A tool window that
closes without unregistering leaves Maya calling into a destroyed Qt object on the artist's next
click, which is a hard crash; see :mod:`mca.mya.utils.events`.

What was wrong before:

- **``MCAMayaWindow`` could not unregister the events it was written to unregister.** Its
  ``eventFilter`` calls ``self.unregister_event(callback)`` on close, and the class does not inherit
  :class:`MayaWindowEvents`, so it has no such method - while ``MCAMayaQWidget``, twenty lines
  below, does inherit it. The loop only stayed quiet because nothing could ever put anything in
  ``self._callbacks``: the methods that fill it are on the mixin the class was missing. So the one
  window class most tools use had the event handling written for it and none of it connected.
- **A window that was never shown never cleaned up at all.** Qt sends no close event for one:
  ``QMainWindow.close()`` on a hidden window answers True and sends nothing, where a plain
  ``QWidget`` does send one - which is why the panel class appeared to work. A tool that builds its
  window with ``show_window=False``, registers a listener and throws the window away left Maya
  calling into a destroyed Qt object. There is a second net on ``destroyed`` now, and the suite
  checks that case specifically.
- **``self.events_register`` was often never set at all.** ``if events_register:
  self.events_register = ... if events_register else None`` - the inner conditional cannot be false
  inside the ``if``, and when ``events_register`` is False the attribute is simply not created. Any
  later call to ``register_event`` then fails on ``if not self.events_register`` with an
  ``AttributeError`` rather than making one.
- **The default parent was worked out when the module was imported.** ``parent=MAYA_MAIN_WINDOW``
  as a default argument, where ``MAYA_MAIN_WINDOW = ma_main_window.get_maya_window()`` runs at
  import time - so every window ever made was parented to whatever Maya's main window was the first
  time anything imported this module. ``None`` in a batch Maya; ``None`` in an interactive one too
  if the import happened during start-up. Default arguments are evaluated once, at definition.
- **``MCAMayaWindow`` showed itself twice.** It passes ``show_window`` down to the base class,
  which shows the window, and then calls ``self.show()`` again.
- ``register_import_event`` was the only one of the four not named after the event it registers -
  ``register_after_import_event`` - so the set did not read as a set.
- The module docstring said "Module that contains the mca decorators at a base python level".
"""

# python imports

# software specific imports
import maya.cmds as cmds

# mca imports
from mca.common import log
from mca.common.pyqt import common_windows
from mca.common.pyqt.pygui import qtcore
from mca.mya.pyqt.utils import ma_main_window
from mca.mya.utils import events


logger = log.MCA_LOGGER


class MayaWindowEvents(object):
    """
    Listening for Maya's events, and stopping when the window goes.

    Mixed into the window classes below. Everything it registers is remembered by name, so
    :meth:`unregister_all` can take the lot off when the window closes - which is the whole point.
    """

    def __init__(self, events_register=False, *args, **kwargs):
        """
        :param bool events_register: Set up the register now. It is made on first use otherwise, so
            a window that never listens for anything never touches Maya's callbacks at all.
        """

        super(MayaWindowEvents, self).__init__(*args, **kwargs)
        #: The names this window has registered, in the order it registered them.
        self._callbacks = []
        #: Always set, even when nothing has been registered yet - the version this replaces left
        #: the attribute uncreated when its argument was False, and every later call to register
        #: anything then failed on an AttributeError rather than making one.
        self.events_register = events.EventsRegister() if events_register else None

    def _register(self):
        """
        :return: The register, made if this window has not needed one yet.
        :rtype: events.EventsRegister
        """

        if self.events_register is None:
            self.events_register = events.EventsRegister()
        return self.events_register

    def register_event(self, unique_id, fnc):
        """
        Listen for the selection changing.

        :param str unique_id: A name for this listener, unique across the whole of Maya.
        :param callable fnc: Called when the selection changes.
        """

        self._register().register_selection_changed_event(unique_id, fnc)
        self._remember(unique_id)

    def register_after_open_event(self, unique_id, fnc):
        """
        Listen for a scene having been opened.

        :param str unique_id: A name for this listener, unique across the whole of Maya.
        :param callable fnc: Called after a scene opens.
        """

        self._register().register_after_open_event(unique_id, fnc)
        self._remember(unique_id)

    def register_after_new_event(self, unique_id, fnc):
        """
        Listen for a new scene having been made.

        :param str unique_id: A name for this listener, unique across the whole of Maya.
        :param callable fnc: Called after a new scene is made.
        """

        self._register().register_after_new_event(unique_id, fnc)
        self._remember(unique_id)

    def register_after_import_event(self, unique_id, fnc):
        """
        Listen for a file having been imported.

        :param str unique_id: A name for this listener, unique across the whole of Maya.
        :param callable fnc: Called after an import.
        """

        self._register().register_after_import_event(unique_id, fnc)
        self._remember(unique_id)

    def _remember(self, unique_id):
        """
        :param str unique_id: A name that has just been registered.
        """

        if unique_id not in self._callbacks:
            self._callbacks.append(unique_id)

    def unregister_event(self, unique_id):
        """
        Stop listening for one thing.

        :param str unique_id: The name it was registered under.
        :return: Whether there was one to stop.
        :rtype: bool
        """

        if unique_id in self._callbacks:
            self._callbacks.remove(unique_id)
        if self.events_register is None:
            return False
        return self.events_register.unregister_event(unique_id)

    def unregister_all(self):
        """
        Stop listening for everything this window registered.

        Called when the window closes. A callback left registered against a window that is gone is
        the crash :mod:`mca.mya.utils.events` exists to prevent.

        :return: The names that were taken off.
        :rtype: list(str)
        """

        taken_off = []
        for unique_id in list(self._callbacks):
            if self.unregister_event(unique_id):
                taken_off.append(unique_id)
        return taken_off


class _ClosesCleanly(object):
    """
    Taking a window's listeners off when the window goes.

    Two ways, because neither on its own covers it:

    - ``closeEvent``, which is what happens when somebody closes the window. The version this
      replaces did this through an ``eventFilter`` that watched for ``QEvent.Close`` and then
      called ``self.closeEvent(event)`` by hand - a longer way round to the same place, and one
      that has a hole in it, see below.
    - ``destroyed``, Qt's signal for the C++ object actually going away. This is the one that
      matters, because **Qt sends no close event at all for a window that was never shown**:
      ``QMainWindow.close()`` on a hidden window answers True and sends nothing. (A plain
      ``QWidget`` does send one, which is why the panel class appeared to work and the window class
      did not.) A tool that builds its window with ``show_window=False``, registers a listener and
      then throws the window away would otherwise leave Maya calling into a destroyed Qt object on
      the artist's next click, which is the crash this whole arrangement exists to prevent.

    The destruction handler deliberately holds the *list of names*, not the window: a slot holding
    the window would keep it alive, and by the time ``destroyed`` fires the Python wrapper may not
    be usable anyway.
    """

    def _watch_for_destruction(self):
        """Take the listeners off if this window is destroyed without being closed."""

        registered_names = self._callbacks

        def clean_up(*args):
            if not registered_names:
                return
            register = events.EventsRegister()
            for unique_id in list(registered_names):
                register.unregister_event(unique_id)
            del registered_names[:]

        self.destroyed.connect(clean_up)

    def closeEvent(self, event):
        """
        :param event: The close event.
        """

        self.unregister_all()
        super(_ClosesCleanly, self).closeEvent(event)


class MCAMayaWindow(_ClosesCleanly, MayaWindowEvents, common_windows.MCAMainWindow):
    """
    A tool's own window, parented to Maya.

    The mixin order matters: ``_ClosesCleanly`` first so its ``closeEvent`` is the one Qt finds,
    then :class:`MayaWindowEvents` for the registering - which is what the version this replaces
    left out, so its close handler called a method the class did not have.
    """

    def __init__(self, title='Maya Tool', ui_path=None, version='1.0.0', parent=None,
                 show_window=True, events_register=False):
        """
        :param str title: The tool's name, shown in the title bar.
        :param str ui_path: A ``.ui`` file to load as the window's contents.
        :param str version: The tool's version, shown beside the name.
        :param parent: The window to sit on. Maya's main window otherwise - worked out now, not
            when this module was imported, which is what the version this replaces did.
        :param bool show_window: Show it straight away.
        :param bool events_register: Set up the event register now rather than on first use.
        """

        super(MCAMayaWindow, self).__init__(
            events_register=events_register,
            title=title, ui_path=ui_path, version=version,
            parent=parent if parent is not None else ma_main_window.get_maya_window(),
            show_window=show_window)

        # The base class has already shown it if it was asked to; the version this replaces called
        # show() again here.
        self._watch_for_destruction()


class MCAMayaQWidget(_ClosesCleanly, MayaWindowEvents, common_windows.ParentableWidget):
    """
    A panel meant to live inside something else - a Maya workspace, another tool's window.
    """

    def __init__(self, ui_path=None, style=None, parent=None, events_register=False,
                 show_window=True):
        """
        :param str ui_path: A ``.ui`` file to load as the contents.
        :param str style: A stylesheet name.
        :param parent: The widget to live in. Maya's main window otherwise.
        :param bool events_register: Set up the event register now rather than on first use.
        :param bool show_window: Show it straight away.
        """

        super(MCAMayaQWidget, self).__init__(
            events_register=events_register,
            ui_path=ui_path, style=style,
            parent=parent if parent is not None else ma_main_window.get_maya_window())

        self._watch_for_destruction()
        if show_window and not cmds.about(batch=True):
            self.show()
