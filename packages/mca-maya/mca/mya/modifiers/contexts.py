"""
The scene states a block of code borrows and gives back.

Every one of these is the same shape: read a piece of Maya's state, change it, run the
caller's code, put the state back whatever happened. That shape is easy to get subtly
wrong, and the version this replaces got it wrong in three places, so it lives here once
and :mod:`mca.mya.modifiers.ma_decorators` is nothing but decorator spellings of these.

What was wrong before:

- ``unlock_node_context`` did ``raise ('Unable to unlock a referenced node: ...')`` - it
  raised a *string*, which in Python 3 is ``TypeError: exceptions must derive from
  BaseException``. The one case it existed to report was the one case it could not report.
- Half the contexts did their setup work *outside* the ``try``, so a failure part way
  through the setup left the scene changed with no ``finally`` to change it back. The
  display-layer and animation-layer cases did this while looping over nodes, which is
  exactly where a failure is likely.
- ``no_panel_refresh_context``, ``namespace_context``, ``unlock_attribute_context``,
  ``unlock_node_context`` and ``disable_undo_context`` had no caller anywhere in the
  pipeline. The ones a decorator needed are kept; the rest are gone.

The state each of these borrows is global to the scene, so nesting two that touch the same
thing gives the innermost one the last word - as with any save-and-restore.
"""

# python imports
from contextlib import contextmanager

# software specific imports
import pymel.core as pm
import maya.cmds as cmds

# mca imports
from mca.common import log


logger = log.MCA_LOGGER


@contextmanager
def undo_chunk_context(name=None):
    """
    Make everything the block does one entry in the undo queue.

    Without this, a function that creates thirty nodes is thirty undos, and a user who
    presses Ctrl-Z once is left with a half-built rig.

    :param str name: What the entry is called in Maya's undo list.
    """

    pm.undoInfo(openChunk=True, chunkName=name or '')
    try:
        yield
    finally:
        pm.undoInfo(closeChunk=True)


@contextmanager
def disable_undo_context():
    """
    Record nothing the block does in the undo queue.

    For work that is about to be thrown away - a temporary duplicate, a measurement rig -
    where filling the queue with it costs memory and buries the user's real last action.

    ``stateWithoutFlush`` rather than ``state``: turning undo off with ``state`` *flushes*
    the queue, so the user loses the history they had before the block ran.
    """

    pm.undoInfo(stateWithoutFlush=False)
    try:
        yield
    finally:
        pm.undoInfo(stateWithoutFlush=True)


@contextmanager
def suspend_refresh_context():
    """
    Stop the viewport redrawing while the block runs.

    The single biggest speed-up available to any function that touches many nodes: Maya
    redraws after each change otherwise.
    """

    pm.refresh(suspend=True)
    try:
        yield
    finally:
        pm.refresh(suspend=False)


@contextmanager
def disable_cycle_check_warnings_context():
    """
    Stop Maya warning about evaluation cycles while the block runs.

    A rig being built passes through states that do contain cycles, and the warning for
    each one is noise that hides real problems.

    .. note:: This only quiets the main panel. A torn-off panel can still report.
    """

    was_on = pm.cycleCheck(evaluation=True, query=True)
    pm.cycleCheck(evaluation=False)
    try:
        yield
    finally:
        pm.cycleCheck(evaluation=was_on)


@contextmanager
def maintained_selection_context():
    """
    Put the selection back the way it was.

    Anything the block deleted is dropped from the restored selection, and if none of it
    survived the selection ends up empty rather than holding whatever the block last
    picked.

    Example:
        >>> scene = pm.newFile(force=True)
        >>> node = pm.createNode('transform', name='newGroup')
        >>> pm.select('persp')
        >>> with maintained_selection_context():
        ...     pm.select(node, replace=True)
        >>> node in pm.ls(selection=True)
        False
    """

    # Long names rather than PyNodes: a PyNode whose node the block deleted throws on the
    # way back in, which turned a working operation into a failure. A name is just a
    # string, and cmds.objExists answers for it without resurrecting anything.
    previous_selection = cmds.ls(selection=True, long=True) or []
    try:
        yield
    finally:
        try:
            still_there = [name for name in previous_selection if cmds.objExists(name)]
            if still_there:
                cmds.select(still_there, replace=True, noExpand=True)
            else:
                # Either nothing was selected to begin with, or all of it is gone. Both
                # mean an empty selection - not whatever the block happened to leave
                # picked.
                cmds.select(clear=True)
        except Exception:
            logger.debug('Could not restore the selection.', exc_info=True)


@contextmanager
def maintain_time_context():
    """
    Put the current frame back where it was.
    """

    current_time = cmds.currentTime(query=True)
    try:
        yield
    finally:
        cmds.currentTime(current_time, edit=True)


@contextmanager
def maintain_namespace_context():
    """
    Put the active namespace back to the one that was active.

    The absolute name, not the relative one: ``namespaceInfo`` without ``absoluteName``
    answers ``'rig'`` for ``':char:rig'``, and setting *that* back from somewhere else in
    the tree either lands in the wrong namespace or fails outright. The version this
    replaces read the relative name and worked around it by setting ``':'`` first, which
    only helps when the original was a direct child of the root.
    """

    original = cmds.namespaceInfo(currentNamespace=True, absoluteName=True)
    try:
        yield
    finally:
        try:
            cmds.namespace(setNamespace=original)
        except RuntimeError:
            # The namespace the block was in can be gone - it deleted or merged it.
            logger.debug('Could not return to namespace %s.', original, exc_info=True)
            cmds.namespace(setNamespace=':')


@contextmanager
def maintain_autokey_context():
    """
    Put auto-key back the way the user had it.

    Rig and import work that moves controls with auto-key on writes keys the user never
    asked for, so tools turn it off - and have to turn it back on, or the user's next
    hand-animated move silently sets no key.
    """

    was_on = cmds.autoKeyframe(query=True, state=True)
    try:
        yield
    finally:
        cmds.autoKeyframe(state=was_on)


@contextmanager
def display_layers_visible_context():
    """
    Show every display layer while the block runs, then put each one back.

    A hidden layer's nodes cannot be selected or snapped to, so anything that walks the
    scene has to show them first. Each layer's own visibility is restored, not all of them
    set on.
    """

    # Read and set in one loop, inside the try, so a failure part way through still
    # restores the ones already changed. The version this replaces looped before the try.
    original = {}
    try:
        for layer in cmds.ls(type='displayLayer') or []:
            if layer == 'defaultLayer':
                continue
            attribute = '{}.visibility'.format(layer)
            original[attribute] = cmds.getAttr(attribute)
            cmds.setAttr(attribute, True)
        yield
    finally:
        for attribute, value in original.items():
            if cmds.objExists(attribute):
                cmds.setAttr(attribute, value)


@contextmanager
def unlocked_animation_layers_context():
    """
    Unlock every animation layer while the block runs, then put each lock back.

    A locked layer refuses keys, and refuses them quietly, so an exporter or a baker that
    does not unlock first produces a file with nothing animated in it.
    """

    original = {}
    try:
        for layer in cmds.ls(type='animLayer') or []:
            original[layer] = cmds.animLayer(layer, query=True, lock=True)
            cmds.animLayer(layer, edit=True, lock=False)
        yield
    finally:
        for layer, was_locked in original.items():
            if cmds.objExists(layer):
                cmds.animLayer(layer, edit=True, lock=was_locked)
