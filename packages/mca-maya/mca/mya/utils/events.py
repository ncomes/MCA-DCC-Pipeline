"""
Maya's own events, and a safe way to listen for them.

Maya can tell Python when the selection changes, when a scene opens, when a node is added -
things ``scriptJob`` does not cover. The catch is that Maya holds the callback as a raw C
function pointer with no Python reference behind it, so a callback that outlives what it belongs
to does not raise: it crashes the process. Most of what is in here exists because of that.

:class:`EventsRegister` is a singleton holding every callback the pipeline has registered, filed
under a name the caller chooses, so it can be taken off again by that name. Every callback goes
out wrapped, and the wrapper:

- skips the call, and unregisters itself, when the callback is a bound method on a Qt object whose
  C++ side has been destroyed - which is the crash above, and the one this module has cost the
  most time to;
- catches anything the callback raises, so a bug in one tool cannot poison Maya's event dispatch
  for every other tool.

.. note:: An earlier revision monkey-patched ``om.MEventMessage``, ``MModelMessage`` and
    ``MSceneMessage`` so that callbacks registered *outside* this register - by dwpicker, by the
    MetaHuman editor - got the same guard. That made things worse. OpenMaya's SWIG bridge keeps the
    Python callable as a raw C function pointer and no strong Python reference, so Python's garbage
    collector reclaimed the wrapper closure and Maya later called a dangling pointer: a hard crash
    with no traceback and no ``MayaCrashLog``, only a Windows minidump. Every six-minute crash on
    2026-05-08 was this. The fix for a third-party tool is to patch its own registration, not to
    wrap Maya's API globally. The wrapper that patch used had no other caller and is gone; this
    note is the part worth keeping.

What was wrong before:

- **Every event but two was stored in a shape the pause and resume methods could not read.**
  ``register_scene_event`` and ``register_selection_changed_event`` filed a dictionary - the
  callback id, the arguments, how to register it again - and the other thirteen filed the bare
  callback id. ``pause_event`` opens with ``self.events[unique_id]['message_type']``, which is
  ``TypeError: 'int' object is not subscriptable`` for all thirteen. Everything is filed the same
  way now, so what works for one event works for all of them.
- **Three log lines did not say what they were meant to.** Two were
  ``logger.info('Registering {unique_id}')`` - no ``f`` - so they logged the braces. The third was
  ``logger.info(f'Registering {0}'.format(unique_id))``: an f-string *and* a ``.format()``, where
  the f-string turns ``{0}`` into the number zero and the ``format`` then has nothing left to
  fill, so it logged "Registering 0".
- **``register_tool_changed_event`` registered the callback unwrapped**, alone among the fifteen -
  so the one kind of callback most likely to belong to a tool window had no dead-receiver guard at
  all.
- **The ``parent_id`` property read an attribute that is never set.** ``__init__`` does not create
  ``_parent_id``, so the getter is an ``AttributeError`` waiting for its first caller. It had
  none.
- **Every event fire logged twice at info level.** "Event Starting" and "Event Complete", on every
  selection change, in a log the artists read. They are debug lines now.
- Fifteen of the nineteen registration methods had no caller anywhere in the pipeline - the user
  events, the DAG and DG families, the node and animation families, ``pause_event`` and
  ``resume_event``. What is left is what is called, plus the two general doors those were built
  on: :meth:`EventsRegister.register_scene_event` for anything in Maya's scene-message list, and
  :meth:`EventsRegister.register_event_callback` for anything in its named-event list. 661 lines
  became fewer than half that.
- **It was the last module in the package on Maya's old API.** ``maya.OpenMaya`` rather than
  ``maya.api.OpenMaya``, which matters here more than most places: the old API answers a
  ``PyCapsule`` for a callback id where the new one answers an integer, so a callback id could not
  be compared, logged usefully or stored in anything that expects a number. Given that everything
  in this module is about holding on to callbacks properly, being on the API that does that is the
  point.
- Tabs for indentation.
"""

# python imports
import functools

# software specific imports
import maya.api.OpenMaya as om

# mca imports
from mca.common import log
from mca.common.modifiers import singleton


logger = log.MCA_LOGGER


def _is_dead_qt_receiver(callback):
    """
    Whether a callback is a bound method on a Qt object Maya has already destroyed.

    This is the crash this module exists for: a tool registers ``self._on_selection_changed``, its
    window is closed without the unregister path firing, and Maya's next selection event dispatches
    into an object whose C++ side is gone.

    :param callback: The callback to judge.
    :return: True when calling it would reach a destroyed Qt object. False whenever that cannot be
        established - no receiver, not a Qt object, no shiboken to ask - because refusing to call a
        live callback is also a bug.
    :rtype: bool
    """

    receiver = getattr(callback, '__self__', None)
    if receiver is None:
        return False

    try:
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken
    except ImportError:
        # No PySide at all. Outside Maya, or in a Maya with no interface; nothing to check.
        return False

    try:
        return not shiboken.isValid(receiver)
    except (TypeError, AttributeError):
        # isValid only complains about receivers that are not Qt objects at all.
        return False


def _callback_label(callback):
    """
    A name for a callback that can be read without touching it.

    ``__qualname__`` is read off the function object rather than off the instance, which matters:
    ``repr()`` on a bound method whose Qt receiver is already deleted raises ``RuntimeError:
    Internal C++ object already deleted`` - and that exception, raised while building a warning
    about a dead receiver, used to propagate back into Maya's event loop. The very thing the
    warning is about.

    :param callback: The callback.
    :return: Something to put in a log line.
    :rtype: str
    """

    try:
        return getattr(callback, '__qualname__', None) or repr(getattr(callback, '__func__',
                                                                      callback))
    except Exception:                                                   # noqa: BLE001
        return '<unnameable callback>'


class EventsRegister(object, metaclass=singleton.Singleton):
    """
    Every Maya callback the pipeline has registered, filed under a name.

    A singleton, because Maya's callbacks are global: two registers would each believe they hold
    all of them, and the second one to unregister a name would find nothing there.

    The metaclass spelling used to be ``@decorators.add_metaclass(singleton.Singleton)``, a shim
    from the days of supporting Python 2. ``mca-common`` no longer has it.
    """

    def __init__(self):
        #: Name to a record: Maya's callback id, the message class it came from, and how to
        #: register it again after a pause. Every event is filed this way - the version this
        #: replaces filed two of its fifteen as records and the rest as a bare callback id, which
        #: is why pausing any of the thirteen was a TypeError.
        self.events = {}
        #: Names that were paused, and their records.
        self.paused_events = {}
        #: The function behind each registered name. Kept apart from the record so a record can be
        #: passed around without carrying a strong reference to somebody's widget.
        self._wrapped_functions = {}

    # -- registering -------------------------------------------------------------------- #
    def _register(self, unique_id, function, add_callback, message_class, register_again):
        """
        File one callback, however it was made.

        Every registration goes through here, so every event is stored the same way - which is
        what makes :meth:`unregister_event`, :meth:`pause_event` and :meth:`resume_event` work for
        all of them rather than for the two that happened to be filed as dictionaries.

        :param str unique_id: The name to file it under. An existing one is replaced.
        :param callable function: What the caller wants called.
        :param callable add_callback: Called with the wrapped function; answers Maya's callback id.
        :param message_class: The Maya message class the callback came from. Kept for the record;
            ``MMessage.removeCallback`` takes any callback id whatever registered it.
        :param callable register_again: Called with no arguments to put the callback back after a
            pause.
        :return: Maya's callback id.
        :rtype: int
        """

        # The replace comes first, and it clears the stored function - so the new one is stored
        # after it, not before. Storing it first and then replacing deletes what was just stored,
        # and the callback then fires into nothing.
        self.unregister_event(unique_id)
        self._wrapped_functions[unique_id] = function
        logger.debug('Registering the event %s.', unique_id)
        callback_id = add_callback(self._wrap_event_function(unique_id))
        self.events[unique_id] = {
            'callback': callback_id,
            'message_class': message_class,
            'register_again': register_again,
        }
        return callback_id

    def register_scene_event(self, unique_id, message_type, function):
        """
        Listen for one of Maya's scene messages.

        The message types, each on ``om.MSceneMessage``:

        ===============================  =================================================
        ``kSceneUpdate``                 after any change to which files are loaded
        ``kBeforeNew`` / ``kAfterNew``   around File > New
        ``kBeforeOpen`` / ``kAfterOpen``  around File > Open
        ``kBeforeImport`` / ``kAfterImport``  around File > Import
        ``kBeforeExport`` / ``kAfterExport``  around File > Export
        ``kBeforeSave`` / ``kAfterSave``  around File > Save and Save As
        ``kBeforeReference`` / ``kAfterReference``  around File > Reference
        ``kBeforeRemoveReference`` / ``kAfterRemoveReference``  around removing one
        ``kBeforeImportReference`` / ``kAfterImportReference``  around importing one
        ``kBeforeExportReference`` / ``kAfterExportReference``  around exporting one
        ``kBeforeLoadReference`` / ``kAfterLoadReference``  around loading one
        ``kBeforeUnloadReference`` / ``kAfterUnloadReference``  around unloading one
        ``kBeforePluginLoad`` / ``kAfterPluginLoad``  around a plugin loading
        ``kBeforePluginUnload`` / ``kAfterPluginUnload``  around one unloading
        ``kMayaInitialized``             after start-up, interactive or batch
        ``kMayaExiting``                 just before Maya exits
        ===============================  =================================================

        :param str unique_id: The name to file it under.
        :param int message_type: One of the above.
        :param callable function: Called when it fires, as ``function(extra_data)``.
        :return: Maya's callback id.
        :rtype: int
        """

        return self._register(
            unique_id, function,
            lambda wrapped: om.MSceneMessage.addCallback(message_type, wrapped),
            om.MSceneMessage,
            lambda: self.register_scene_event(unique_id, message_type, function))

    def register_after_new_event(self, unique_id, function):
        """
        Listen for a new scene having been made.

        :param str unique_id: The name to file it under.
        :param callable function: Called as ``function(extra_data)``.
        :return: Maya's callback id.
        :rtype: int
        """

        return self.register_scene_event(unique_id, om.MSceneMessage.kAfterNew, function)

    def register_after_open_event(self, unique_id, function):
        """
        Listen for a scene having been opened.

        :param str unique_id: The name to file it under.
        :param callable function: Called as ``function(extra_data)``.
        :return: Maya's callback id.
        :rtype: int
        """

        return self.register_scene_event(unique_id, om.MSceneMessage.kAfterOpen, function)

    def register_after_import_event(self, unique_id, function):
        """
        Listen for a file having been imported.

        :param str unique_id: The name to file it under.
        :param callable function: Called as ``function(extra_data)``.
        :return: Maya's callback id.
        :rtype: int
        """

        return self.register_scene_event(unique_id, om.MSceneMessage.kAfterImport, function)

    def register_selection_changed_event(self, unique_id, function):
        """
        Listen for the scene's selection changing.

        The one every tool window wants, and the one that has crashed Maya most often - a tool that
        registers a bound method here and is closed without unregistering leaves Maya calling into
        a destroyed Qt object on the artist's next click. The wrapper catches that.

        :param str unique_id: The name to file it under.
        :param callable function: Called as ``function(extra_data)``.
        :return: Maya's callback id.
        :rtype: int
        """

        return self._register(
            unique_id, function,
            lambda wrapped: om.MModelMessage.addCallback(
                om.MModelMessage.kActiveListModified, wrapped),
            om.MModelMessage,
            lambda: self.register_selection_changed_event(unique_id, function))

    def register_event_callback(self, unique_id, event_name, function):
        """
        Listen for one of Maya's named events - anything ``cmds.scriptJob -listEvents`` lists.

        ``'ToolChanged'``, ``'timeChanged'``, ``'NewSceneOpened'``, and so on. This is the general
        door: the version this replaces had a method per event, most of them with no caller.

        :param str unique_id: The name to file it under.
        :param str event_name: Maya's name for the event.
        :param callable function: Called when it fires.
        :return: Maya's callback id.
        :rtype: int
        """

        return self._register(
            unique_id, function,
            lambda wrapped: om.MEventMessage.addEventCallback(event_name, wrapped),
            om.MEventMessage,
            lambda: self.register_event_callback(unique_id, event_name, function))

    # -- unregistering, pausing ---------------------------------------------------------- #
    def unregister_event(self, unique_id):
        """
        Take a callback off, by the name it was filed under.

        :param str unique_id: The name.
        :return: Whether there was one to take off.
        :rtype: bool
        """

        record = self.events.pop(unique_id, None)
        self._wrapped_functions.pop(unique_id, None)
        if record is None:
            return False

        logger.debug('Unregistering the event %s.', unique_id)
        try:
            # MMessage.removeCallback is the one call for every kind of callback; the class it was
            # registered through does not come into it.
            om.MMessage.removeCallback(record['callback'])
        except RuntimeError as error:
            logger.warning('Could not unregister the event %s: %s', unique_id, error)
            return False
        return True

    def unregister_all(self):
        """
        Take every callback off.

        For a tool closing, and for a test run that must not leave callbacks behind in a Maya it
        did not start.

        :return: The names that were taken off.
        :rtype: list(str)
        """

        taken_off = []
        for unique_id in list(self.events):
            if self.unregister_event(unique_id):
                taken_off.append(unique_id)
        return taken_off

    def pause_event(self, unique_id):
        """
        Take a callback off, remembering how to put it back.

        For an operation that would otherwise set the event off hundreds of times - a rig build
        firing a selection-changed handler on every control it makes.

        :param str unique_id: The name.
        :return: Whether there was one to pause.
        :rtype: bool
        """

        record = self.events.get(unique_id)
        if record is None:
            return False
        if not self.unregister_event(unique_id):
            return False
        self.paused_events[unique_id] = record
        return True

    def resume_event(self, unique_id):
        """
        Put a paused callback back.

        :param str unique_id: The name.
        :return: Whether there was one to put back.
        :rtype: bool
        """

        record = self.paused_events.pop(unique_id, None)
        if record is None:
            return False
        record['register_again']()
        return True

    # -- the wrapper --------------------------------------------------------------------- #
    def _wrap_event_function(self, unique_id):
        """
        The callable actually handed to Maya: the caller's function, guarded.

        :param str unique_id: The name the callback is filed under, so the guard can unregister it
            when it finds the receiver dead.
        :return: The wrapped callable.
        :rtype: callable
        """

        return functools.partial(self._logged_event, unique_id)

    def _logged_event(self, unique_id, *args, **kwargs):
        """
        Call a registered function, and let nothing out.

        Everything is inside one ``try``, so the guard itself can never be what crashes Maya.

        :param str unique_id: The name the callback is filed under.
        :return: Whatever the function answered, or None when it was skipped or raised.
        """

        try:
            function = self._wrapped_functions.get(unique_id)
            if function is None:
                logger.debug('The event %s fired with nothing registered for it.', unique_id)
                return None

            label = _callback_label(function)
            if _is_dead_qt_receiver(function):
                logger.warning('The event %s fired into a destroyed Qt receiver (%s); skipping it '
                               'and unregistering.', unique_id, label)
                self.unregister_event(unique_id)
                return None

            logger.debug('Event starting: %s -> %s', unique_id, label)
            try:
                result = function(*args, **kwargs)
            except Exception as error:                                   # noqa: BLE001
                # A tool's bug used to propagate up through Maya's API and could take the event
                # dispatch with it. Logged and swallowed, a buggy tool just does not fire.
                logger.error('The event %s -> %s raised: %s', unique_id, label, error,
                             exc_info=True)
                return None
            logger.debug('Event complete: %s -> %s', unique_id, label)
            return result
        except Exception as error:                                       # noqa: BLE001
            logger.error('The wrapper for the event %s crashed: %s', unique_id, error,
                         exc_info=True)
            return None
