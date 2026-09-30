"""
Maya's events, and the guard around them: mca.mya.utils.events.

The suite registers real callbacks in a real Maya, sets them off, and takes them off again - and
leaves none behind, because a callback left registered in a Maya the suite did not start is the
crash this module exists to prevent.

    mayapy tests/test_events.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


class Recorder(object):
    """Something to hand a register and then ask what happened."""

    def __init__(self):
        self.calls = []

    def note(self, *args, **kwargs):
        self.calls.append(args)

    def blow_up(self, *args, **kwargs):
        self.calls.append(args)
        raise ValueError('deliberate')


def body(suite):
    harness.add_sibling_packages()

    import maya.cmds as cmds
    import maya.api.OpenMaya as om
    import pymel.core as pm
    from mca.mya.utils import events

    register = events.EventsRegister()
    try:
        suite.check('the register is a singleton', events.EventsRegister() is register)
        suite.check('and it starts with nothing registered', register.events == {},
                    str(register.events))

        # -- the selection event ---------------------------------------------------------- #
        harness.new_scene()
        watcher = Recorder()
        callback_id = register.register_selection_changed_event('suite_selection', watcher.note)
        # An integer, because this is Maya's current API. The old one answers a PyCapsule, which
        # cannot be compared or usefully logged - and holding on to callbacks properly is what this
        # module is for.
        suite.check('registering answers a callback id, as an integer',
                    isinstance(callback_id, int), repr(callback_id))
        suite.check('and the event is on the register', 'suite_selection' in register.events)

        node = pm.createNode('transform', name='watched')
        cmds.select(str(node), replace=True)
        suite.check('changing the selection sets the callback off', len(watcher.calls) >= 1,
                    str(watcher.calls))

        # Every event is filed the same way, which is the whole point of the rewrite.
        record = register.events['suite_selection']
        suite.check('the record holds the callback id', record['callback'] == callback_id)
        suite.check('and the message class it came from',
                    record['message_class'] is om.MModelMessage)
        suite.check('and how to register it again', callable(record['register_again']))

        # -- pausing, which used to be a TypeError for thirteen of the fifteen events ------ #
        before_pause = len(watcher.calls)
        suite.check('an event can be paused', register.pause_event('suite_selection') is True)
        cmds.select(clear=True)
        cmds.select(str(node), replace=True)
        suite.check('and does not fire while it is paused',
                    len(watcher.calls) == before_pause, str(watcher.calls))
        suite.check('it is off the register while paused',
                    'suite_selection' not in register.events)
        suite.check('and on the paused list', 'suite_selection' in register.paused_events)

        suite.check('it can be resumed', register.resume_event('suite_selection') is True)
        cmds.select(clear=True)
        suite.check('and fires again afterwards', len(watcher.calls) > before_pause,
                    str(watcher.calls))
        suite.check('pausing something that is not registered answers False',
                    register.pause_event('no_such_event') is False)
        suite.check('and resuming something that was not paused',
                    register.resume_event('no_such_event') is False)

        # -- registering the same name twice replaces it ----------------------------------- #
        second = Recorder()
        register.register_selection_changed_event('suite_selection', second.note)
        suite.check('there is still one event of that name', len(register.events) == 1,
                    str(sorted(register.events)))
        first_count = len(watcher.calls)
        cmds.select(str(node), replace=True)
        suite.check('the new callback fires', len(second.calls) >= 1, str(second.calls))
        suite.check('and the one it replaced does not',
                    len(watcher.calls) == first_count, str(watcher.calls))

        suite.check('unregistering answers True',
                    register.unregister_event('suite_selection') is True)
        suite.check('and the event is gone', 'suite_selection' not in register.events)
        count_after = len(second.calls)
        cmds.select(clear=True)
        suite.check('and it no longer fires', len(second.calls) == count_after)
        suite.check('unregistering something that is not there answers False',
                    register.unregister_event('suite_selection') is False)

        # -- scene events ------------------------------------------------------------------ #
        opened = Recorder()
        register.register_after_new_event('suite_after_new', opened.note)
        suite.check('an after-new event registers', 'suite_after_new' in register.events)
        cmds.file(new=True, force=True)
        suite.check('and fires when a new scene is made', len(opened.calls) >= 1,
                    str(opened.calls))

        imported = Recorder()
        register.register_after_import_event('suite_after_import', imported.note)
        suite.check('an after-import event registers', 'suite_after_import' in register.events)

        scene_path = os.path.join(suite.temp, 'to_import.ma').replace('\\', '/')
        pm.createNode('transform', name='will_be_imported')
        cmds.file(rename=scene_path)
        cmds.file(save=True, type='mayaAscii')
        cmds.file(new=True, force=True)
        cmds.file(scene_path, i=True, force=True)
        suite.check('and fires when a file is imported', len(imported.calls) >= 1,
                    str(imported.calls))

        register.register_after_open_event('suite_after_open', Recorder().note)
        suite.check('an after-open event registers too', 'suite_after_open' in register.events)

        # Any scene message by name, which is the general door.
        general = Recorder()
        register.register_scene_event('suite_before_save', om.MSceneMessage.kBeforeSave,
                                      general.note)
        cmds.file(rename=os.path.join(suite.temp, 'saved_once.ma').replace('\\', '/'))
        cmds.file(save=True, type='mayaAscii')
        suite.check('a scene message registered by type fires', len(general.calls) >= 1,
                    str(general.calls))

        # -- a named event ----------------------------------------------------------------- #
        timed = Recorder()
        register.register_event_callback('suite_time', 'timeChanged', timed.note)
        suite.check('a named event registers', 'suite_time' in register.events)
        cmds.currentTime(11)
        suite.check('and fires', len(timed.calls) >= 1, str(timed.calls))

        # -- a callback that raises --------------------------------------------------------- #
        # A tool's bug used to propagate up through Maya's API and could take the event dispatch
        # with it.
        breaker = Recorder()
        register.register_event_callback('suite_breaker', 'timeChanged', breaker.blow_up)
        cmds.currentTime(12)
        suite.check('a callback that raises still ran', len(breaker.calls) >= 1,
                    str(breaker.calls))
        cmds.currentTime(13)
        suite.check('and the event still fires afterwards - the exception went nowhere',
                    len(breaker.calls) >= 2, str(breaker.calls))
        suite.check('and the register is intact', 'suite_breaker' in register.events)

        # -- the dead Qt receiver guard ----------------------------------------------------- #
        # The crash this module is mostly here for. Checked through the two pieces the guard is
        # built from, because actually destroying a widget's C++ side and then setting Maya's event
        # off is the crash itself, not a test of it.
        suite.check('a plain function has no receiver to be dead',
                    events._is_dead_qt_receiver(watcher.note) is False)

        def free_function():
            pass

        suite.check('nor does a free function',
                    events._is_dead_qt_receiver(free_function) is False)

        class NotAQtObject(object):
            def method(self):
                pass

        suite.check('a bound method on something that is not a Qt object is not dead either',
                    events._is_dead_qt_receiver(NotAQtObject().method) is False)

        suite.check('a callback can be named without being called',
                    events._callback_label(watcher.note).endswith('note'),
                    events._callback_label(watcher.note))
        suite.check('and so can a free function',
                    'free_function' in events._callback_label(free_function))

        class Unnameable(object):
            def __getattr__(self, name):
                raise RuntimeError('Internal C++ object already deleted')

        # This is the exact shape of the failure the label helper exists for: repr() on a bound
        # method whose receiver is gone raises, and that exception, raised while building the
        # warning about the dead receiver, used to reach Maya's event loop.
        suite.check('a callback that raises when looked at still gets a label',
                    isinstance(events._callback_label(Unnameable()), str),
                    repr(events._callback_label(Unnameable())))

        # -- what was dropped --------------------------------------------------------------- #
        for name in ('register_user_event', 'add_user_event', 'post_user_event',
                     'register_dag_changes_event', 'register_node_added_event',
                     'register_node_removed_event', 'register_keyframe_changed_event',
                     'register_attribute_changed_event', 'register_tool_changed_event',
                     'register_event_event'):
            suite.check('{} is gone - no callers'.format(name),
                        not hasattr(register, name))
        suite.check('the parent_id property is gone - it read an attribute never set',
                    not hasattr(events.EventsRegister, 'parent_id'))
        suite.check('_safe_callback_wrapper is gone with the monkey patch it served',
                    not hasattr(events, '_safe_callback_wrapper'))
        suite.check('but the note about why that patch was a mistake is kept',
                    'dangling pointer' in (events.__doc__ or ''))

        # -- and nothing is left behind ------------------------------------------------------ #
        taken_off = register.unregister_all()
        suite.check('everything can be taken off at once', len(taken_off) >= 5, str(taken_off))
        suite.check('and the register is empty', register.events == {}, str(register.events))
    finally:
        # Whatever happened above, this Maya does not keep the suite's callbacks.
        register.unregister_all()
        register.paused_events.clear()
        harness.new_scene()

    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('events', body))
