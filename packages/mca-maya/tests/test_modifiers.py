"""
The scene state borrowed and given back: mca.mya.modifiers.

Needs a real Maya, because every check here is about what Maya actually does with undo
queues, namespaces, display layers and animation layers - which is the part a stub would
get wrong in exactly the way the code used to.

    mayapy tests/test_modifiers.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def body(suite):
    harness.add_sibling_packages()

    import maya.cmds as cmds
    from mca.mya.modifiers import contexts
    from mca.mya.modifiers import ma_decorators

    # Batch Maya starts with undo off, and half of these checks are about the undo queue.
    cmds.undoInfo(state=True, infinity=True)

    # -- undo_chunk_context ------------------------------------------------------------- #
    harness.new_scene()
    with contexts.undo_chunk_context('mca_test_chunk'):
        for index in range(5):
            cmds.createNode('transform', name='chunk_{}'.format(index))
    suite.check('five nodes made inside an undo chunk exist',
                cmds.objExists('chunk_0') and cmds.objExists('chunk_4'))
    cmds.undo()
    suite.check('one undo removes the whole chunk, not one node of it',
                not cmds.objExists('chunk_0') and not cmds.objExists('chunk_4'))

    # A failure inside the block must still close the chunk, or every later undo entry is
    # swallowed into it.
    def blow_up():
        with contexts.undo_chunk_context('mca_test_failing'):
            cmds.createNode('transform', name='doomed')
            raise ValueError('deliberate')

    suite.raises('a failure inside an undo chunk propagates', blow_up)
    cmds.createNode('transform', name='after_the_failure')
    cmds.undo()
    suite.check('the chunk was closed despite the failure, so the next undo stands alone',
                not cmds.objExists('after_the_failure') and cmds.objExists('doomed'))

    # -- disable_undo_context ----------------------------------------------------------- #
    harness.new_scene()
    cmds.createNode('transform', name='before_disable')
    with contexts.disable_undo_context():
        cmds.createNode('transform', name='not_recorded')
    suite.check('a node made with undo off is still in the scene',
                cmds.objExists('not_recorded'))
    suite.check('undo is back on afterwards', cmds.undoInfo(query=True, stateWithoutFlush=True))
    cmds.undo()
    suite.check('undo skipped the unrecorded node and removed the one before it',
                cmds.objExists('not_recorded') and not cmds.objExists('before_disable'))

    # -- suspend_refresh_context -------------------------------------------------------- #
    harness.new_scene()
    with contexts.suspend_refresh_context():
        cmds.createNode('transform', name='while_suspended')
    suite.check('work done with the viewport suspended still happens',
                cmds.objExists('while_suspended'))

    def suspend_and_fail():
        with contexts.suspend_refresh_context():
            raise ValueError('deliberate')

    suite.raises('a failure with the viewport suspended propagates', suspend_and_fail)
    # If refresh were left suspended the next one would be a no-op rather than an error, so
    # the check that matters is that Maya still answers at all.
    cmds.refresh()
    suite.check('Maya still refreshes after a failure inside the context', True)

    # -- disable_cycle_check_warnings_context ------------------------------------------- #
    # Batch Maya pins cycle-check evaluation off and will not turn it on, so what can be
    # checked here is the contract - off inside, and whatever it was on the way out - rather
    # than a particular value. In a Maya with a window the same code restores a True.
    harness.new_scene()
    before = cmds.cycleCheck(query=True, evaluation=True)
    with contexts.disable_cycle_check_warnings_context():
        suite.check('cycle checking is off inside the context',
                    not cmds.cycleCheck(query=True, evaluation=True))
    suite.check('the previous setting is restored, not forced either way',
                cmds.cycleCheck(query=True, evaluation=True) == before)

    # -- maintained_selection_context --------------------------------------------------- #
    harness.new_scene()
    keeper = cmds.createNode('transform', name='keeper')
    other = cmds.createNode('transform', name='other')
    cmds.select(keeper, replace=True)
    with contexts.maintained_selection_context():
        cmds.select(other, replace=True)
    suite.check('the selection is put back', cmds.ls(selection=True) == [keeper])

    # The bug this was written for: restoring a PyNode whose node is gone raises, which
    # turned a working operation into a failure.
    cmds.select(keeper, replace=True)
    with contexts.maintained_selection_context():
        cmds.delete(keeper)
        cmds.select(other, replace=True)
    suite.check('a deleted node is dropped from the restored selection, not raised over',
                cmds.ls(selection=True) == [])

    cmds.select(clear=True)
    with contexts.maintained_selection_context():
        cmds.select(other, replace=True)
    suite.check('nothing selected before means nothing selected after',
                cmds.ls(selection=True) == [])

    # -- maintain_time_context ---------------------------------------------------------- #
    harness.new_scene()
    cmds.currentTime(17, edit=True)
    with contexts.maintain_time_context():
        cmds.currentTime(90, edit=True)
    suite.check('the current frame is put back', cmds.currentTime(query=True) == 17)

    def move_time_and_fail():
        with contexts.maintain_time_context():
            cmds.currentTime(200, edit=True)
            raise ValueError('deliberate')

    suite.raises('a failure inside the time context propagates', move_time_and_fail)
    suite.check('the frame is put back after a failure too', cmds.currentTime(query=True) == 17)

    # -- maintain_namespace_context ----------------------------------------------------- #
    # The real bug: the old decorator read the *relative* namespace name, so from anywhere
    # deeper than a direct child of the root it restored the wrong one - or nothing.
    harness.new_scene()
    cmds.namespace(setNamespace=':')
    cmds.namespace(add='char')
    cmds.namespace(setNamespace=':char')
    cmds.namespace(add='rig')
    cmds.namespace(setNamespace=':char:rig')
    suite.check('a nested namespace is active to start with',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':char:rig')
    with contexts.maintain_namespace_context():
        cmds.namespace(setNamespace=':')
    suite.check('a nested namespace is restored in full, not by its relative name',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':char:rig')

    # And when the block deletes the namespace it was in, the context has to land somewhere
    # rather than raise on the way out.
    cmds.namespace(setNamespace=':char:rig')
    with contexts.maintain_namespace_context():
        cmds.namespace(setNamespace=':')
        cmds.namespace(removeNamespace=':char:rig')
    suite.check('a namespace deleted inside the block leaves us at the root, not in an error',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':')
    cmds.namespace(setNamespace=':')

    # -- maintain_autokey_context ------------------------------------------------------- #
    harness.new_scene()
    cmds.autoKeyframe(state=True)
    with contexts.maintain_autokey_context():
        cmds.autoKeyframe(state=False)
        suite.check('auto-key can be turned off inside the context',
                    not cmds.autoKeyframe(query=True, state=True))
    suite.check('auto-key is put back on', cmds.autoKeyframe(query=True, state=True))
    cmds.autoKeyframe(state=False)
    with contexts.maintain_autokey_context():
        cmds.autoKeyframe(state=True)
    suite.check('auto-key off before means off after',
                not cmds.autoKeyframe(query=True, state=True))

    # -- display_layers_visible_context ------------------------------------------------- #
    harness.new_scene()
    cmds.createNode('transform', name='on_a_layer')
    shown = cmds.createDisplayLayer(name='shown_layer', empty=True)
    hidden = cmds.createDisplayLayer(name='hidden_layer', empty=True)
    cmds.setAttr('{}.visibility'.format(hidden), False)
    with contexts.display_layers_visible_context():
        suite.check('a hidden display layer is shown inside the context',
                    cmds.getAttr('{}.visibility'.format(hidden)))
        suite.check('an already visible layer stays visible',
                    cmds.getAttr('{}.visibility'.format(shown)))
    suite.check('the hidden layer is hidden again afterwards',
                not cmds.getAttr('{}.visibility'.format(hidden)))
    suite.check('the visible layer is left visible',
                cmds.getAttr('{}.visibility'.format(shown)))

    def show_layers_and_fail():
        with contexts.display_layers_visible_context():
            raise ValueError('deliberate')

    suite.raises('a failure inside the display layer context propagates', show_layers_and_fail)
    suite.check('display layer visibility is restored after a failure',
                not cmds.getAttr('{}.visibility'.format(hidden)))

    # A layer deleted inside the block must not be set on the way out.
    with contexts.display_layers_visible_context():
        cmds.delete(hidden)
    suite.check('a display layer deleted inside the block is not restored over',
                not cmds.objExists(hidden))

    # -- unlocked_animation_layers_context ---------------------------------------------- #
    harness.new_scene()
    cmds.createNode('transform', name='animated')
    locked_layer = cmds.animLayer('locked_layer')
    cmds.animLayer(locked_layer, edit=True, lock=True)
    open_layer = cmds.animLayer('open_layer')
    with contexts.unlocked_animation_layers_context():
        suite.check('a locked animation layer is unlocked inside the context',
                    not cmds.animLayer(locked_layer, query=True, lock=True))
        suite.check('an unlocked layer stays unlocked',
                    not cmds.animLayer(open_layer, query=True, lock=True))
    suite.check('the locked layer is locked again afterwards',
                cmds.animLayer(locked_layer, query=True, lock=True))
    suite.check('the unlocked layer is left unlocked',
                not cmds.animLayer(open_layer, query=True, lock=True))

    def unlock_and_fail():
        with contexts.unlocked_animation_layers_context():
            raise ValueError('deliberate')

    suite.raises('a failure inside the animation layer context propagates', unlock_and_fail)
    suite.check('animation layer locks are restored after a failure',
                cmds.animLayer(locked_layer, query=True, lock=True))

    # -- the decorators ----------------------------------------------------------------- #
    harness.new_scene()

    @ma_decorators.undo_decorator
    def make_three():
        """Build three nodes."""
        for index in range(3):
            cmds.createNode('transform', name='deco_{}'.format(index))
        return 'done'

    suite.check('a decorated function still returns its value', make_three() == 'done')
    suite.check('functools.wraps is kept - the name survives', make_three.__name__ == 'make_three')
    suite.check('functools.wraps is kept - the docstring survives',
                make_three.__doc__ == 'Build three nodes.')
    cmds.undo()
    suite.check('undo_decorator makes the whole call one undo',
                not cmds.objExists('deco_0') and not cmds.objExists('deco_2'))

    # The bug: undo_decorator used to catch the failure and re-raise
    # `Exception(traceback.format_exc())`, so a caller could no longer catch what it meant
    # to catch, and the traceback pointed at the decorator.
    @ma_decorators.undo_decorator
    def raise_a_value_error():
        raise ValueError('the real problem')

    caught = None
    try:
        raise_a_value_error()
    except Exception as error:
        caught = error
    suite.check('undo_decorator lets the original exception type through',
                isinstance(caught, ValueError), 'got {}'.format(type(caught).__name__))
    suite.check('undo_decorator does not replace the message with a traceback',
                str(caught) == 'the real problem', repr(str(caught)))

    @ma_decorators.keep_selection_decorator
    def select_something_else():
        cmds.select(cmds.createNode('transform', name='distraction'), replace=True)

    picked = cmds.createNode('transform', name='picked')
    cmds.select(picked, replace=True)
    select_something_else()
    suite.check('keep_selection_decorator puts the selection back',
                cmds.ls(selection=True) == [picked])

    @ma_decorators.keep_current_frame_decorator
    def scrub_away():
        cmds.currentTime(300, edit=True)

    cmds.currentTime(42, edit=True)
    scrub_away()
    suite.check('keep_current_frame_decorator puts the frame back',
                cmds.currentTime(query=True) == 42)

    @ma_decorators.keep_namespace_decorator
    def wander_off():
        cmds.namespace(setNamespace=':')

    cmds.namespace(setNamespace=':')
    cmds.namespace(add='deco')
    cmds.namespace(setNamespace=':deco')
    cmds.namespace(add='inner')
    cmds.namespace(setNamespace=':deco:inner')
    wander_off()
    suite.check('keep_namespace_decorator restores a nested namespace',
                cmds.namespaceInfo(currentNamespace=True, absoluteName=True) == ':deco:inner')
    cmds.namespace(setNamespace=':')

    @ma_decorators.keep_autokey_decorator
    def turn_autokey_on():
        cmds.autoKeyframe(state=True)

    cmds.autoKeyframe(state=False)
    turn_autokey_on()
    suite.check('keep_autokey_decorator puts auto-key back',
                not cmds.autoKeyframe(query=True, state=True))

    @ma_decorators.not_undoable_decorator
    def quietly_make_one():
        cmds.createNode('transform', name='unrecorded_by_decorator')

    harness.new_scene()
    cmds.undoInfo(state=True, infinity=True)
    cmds.createNode('transform', name='recorded')
    quietly_make_one()
    cmds.undo()
    suite.check('not_undoable_decorator keeps its work out of the queue',
                cmds.objExists('unrecorded_by_decorator') and not cmds.objExists('recorded'))

    @ma_decorators.disable_cycle_check_decorator
    def check_cycle_state():
        return cmds.cycleCheck(query=True, evaluation=True)

    before = cmds.cycleCheck(query=True, evaluation=True)
    suite.check('disable_cycle_check_decorator turns it off for the call',
                not check_cycle_state())
    suite.check('and leaves the setting as it found it',
                cmds.cycleCheck(query=True, evaluation=True) == before)

    @ma_decorators.freeze_renderer_decorator
    def work_with_the_viewport_frozen():
        return cmds.createNode('transform', name='frozen_work')

    suite.check('freeze_renderer_decorator runs the function',
                work_with_the_viewport_frozen() == 'frozen_work')

    @ma_decorators.make_display_layers_visible_decorator
    def read_layer_visibility(layer):
        return cmds.getAttr('{}.visibility'.format(layer))

    layer = cmds.createDisplayLayer(name='deco_layer', empty=True)
    cmds.setAttr('{}.visibility'.format(layer), False)
    suite.check('make_display_layers_visible_decorator shows the layer for the call',
                read_layer_visibility(layer))
    suite.check('and hides it again', not cmds.getAttr('{}.visibility'.format(layer)))

    @ma_decorators.unlock_animation_layers
    def read_layer_lock(layer):
        return cmds.animLayer(layer, query=True, lock=True)

    anim_layer = cmds.animLayer('deco_anim_layer')
    cmds.animLayer(anim_layer, edit=True, lock=True)
    suite.check('unlock_animation_layers unlocks the layer for the call',
                not read_layer_lock(anim_layer))
    suite.check('and locks it again', cmds.animLayer(anim_layer, query=True, lock=True))

    # -- what was dropped --------------------------------------------------------------- #
    for name in ('repeat_static_command_decorator', 'ignore_prompts_decorator', 'viewport_off'):
        suite.check('{} is gone'.format(name), not hasattr(ma_decorators, name))
    for name in ('no_panel_refresh_context', 'namespace_context', 'unlock_attribute_context',
                 'unlock_node_context'):
        suite.check('{} is gone'.format(name), not hasattr(contexts, name))

    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('modifiers', body))
