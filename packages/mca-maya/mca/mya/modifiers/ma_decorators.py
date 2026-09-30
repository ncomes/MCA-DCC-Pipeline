"""
The contexts in :mod:`mca.mya.modifiers.contexts`, spelled as decorators.

Most pipeline functions want the borrow-and-return behaviour for their whole body, and a
decorator says that at the top of the function where a reader will see it. Every one of
these is the matching context and nothing else, so there is one implementation of each
piece of save-and-restore rather than two that drift apart.

What was wrong before:

- Each of the twelve decorators carried its own copy of the save-change-restore dance, and
  they had drifted: some queried with ``cmds`` and restored with ``pm``, the display-layer
  and animation-layer ones did their looping *outside* the ``try`` so a failure part way
  through left the scene changed, and ``keep_namespace_decorator`` restored the *relative*
  namespace name, which lands in the wrong place from anywhere but the root.
- Every decorator was wrapped in ``try: ... except Exception: raise`` - three times in some
  of them, nested. That construct does nothing at all; it was roughly a third of the file.
- ``undo_decorator`` caught the failure and did ``raise Exception(traceback.format_exc())``,
  which replaced the real exception type with a bare ``Exception`` carrying the traceback as
  its *message*. Callers could no longer catch what they meant to catch, and the traceback
  the user saw pointed here instead of at the failure.
- ``repeat_static_command_decorator`` built the MEL for Maya's "repeat last" by appending
  each argument twice - once bare, once quoted - so the command it registered was a syntax
  error. Nothing called it. Gone.
- ``ignore_prompts_decorator`` and ``viewport_off`` had no callers either. ``viewport_off``
  also branched on ``getApplicationVersionAsFloat() >= 2016``, which has been true of every
  Maya the pipeline supports for a decade. Both gone.
"""

# python imports
from functools import wraps

# mca imports
from mca.common import log
from mca.mya.modifiers import contexts


logger = log.MCA_LOGGER


def _decorator_for(context_factory, doc):
    """
    Build a decorator that runs the wrapped function inside a context.

    :param callable context_factory: Called with no arguments to get the context manager.
    :param str doc: The decorator's docstring.
    :return: The decorator.
    :rtype: callable
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with context_factory():
                return fn(*args, **kwargs)
        return wrapper

    decorator.__doc__ = doc
    return decorator


#: Everything the function does is one undo entry. See :func:`contexts.undo_chunk_context`.
undo_decorator = _decorator_for(
    contexts.undo_chunk_context,
    'Make everything the wrapped function does one entry in the undo queue.\n\n'
    '    :param callable fn: The function being decorated.\n')

#: Nothing the function does enters the undo queue. See :func:`contexts.disable_undo_context`.
not_undoable_decorator = _decorator_for(
    contexts.disable_undo_context,
    'Keep everything the wrapped function does out of the undo queue.\n\n'
    '    :param callable fn: The function being decorated.\n')

#: The viewport does not redraw while the function runs. See :func:`contexts.suspend_refresh_context`.
freeze_renderer_decorator = _decorator_for(
    contexts.suspend_refresh_context,
    'Stop the viewport redrawing while the wrapped function runs.\n\n'
    '    :param callable fn: The function being decorated.\n')

#: No cycle warnings while the function runs. See :func:`contexts.disable_cycle_check_warnings_context`.
disable_cycle_check_decorator = _decorator_for(
    contexts.disable_cycle_check_warnings_context,
    'Stop Maya warning about evaluation cycles while the wrapped function runs.\n\n'
    '    :param callable fn: The function being decorated.\n')

#: The selection is put back afterwards. See :func:`contexts.maintained_selection_context`.
keep_selection_decorator = _decorator_for(
    contexts.maintained_selection_context,
    'Put the selection back after the wrapped function runs, skipping anything it '
    'deleted.\n\n    :param callable fn: The function being decorated.\n')

#: The current frame is put back afterwards. See :func:`contexts.maintain_time_context`.
keep_current_frame_decorator = _decorator_for(
    contexts.maintain_time_context,
    'Put the current frame back after the wrapped function runs.\n\n'
    '    :param callable fn: The function being decorated.\n')

#: The active namespace is put back afterwards. See :func:`contexts.maintain_namespace_context`.
keep_namespace_decorator = _decorator_for(
    contexts.maintain_namespace_context,
    'Put the active namespace back after the wrapped function runs.\n\n'
    '    :param callable fn: The function being decorated.\n')

#: Auto-key is put back the way the user had it. See :func:`contexts.maintain_autokey_context`.
keep_autokey_decorator = _decorator_for(
    contexts.maintain_autokey_context,
    "Put auto-key back the way the user had it after the wrapped function runs.\n\n"
    '    :param callable fn: The function being decorated.\n')

#: Every display layer is visible while the function runs. See :func:`contexts.display_layers_visible_context`.
make_display_layers_visible_decorator = _decorator_for(
    contexts.display_layers_visible_context,
    'Show every display layer while the wrapped function runs, then put each back.\n\n'
    '    :param callable fn: The function being decorated.\n')

#: Every animation layer is unlocked while the function runs. See :func:`contexts.unlocked_animation_layers_context`.
unlock_animation_layers = _decorator_for(
    contexts.unlocked_animation_layers_context,
    'Unlock every animation layer while the wrapped function runs, then put each lock '
    'back.\n\n    :param callable fn: The function being decorated.\n')
