"""
Source control, from a tool's point of view.

```python
from mca.common import sourcecontrol

sourcecontrol.checkout(scene_path)
if not sourcecontrol.submit(files, 'rig: hero, arm fixes'):
    ...
```

A tool never names Perforce. Which backend answers is a studio's business, decided by
``MCA_SOURCE_CONTROL``:

===============  ==============================================================
unset            Work it out: the first backend that says it is set up here.
``perforce``     Perforce, whether or not it is set up - so it can say why not.
``none``         Nothing. Every operation succeeds and does nothing.
===============  ==============================================================

Adding one means writing a class against :class:`base.SourceControl` and putting it in
:data:`BACKENDS`. Nothing else in the framework changes.
"""

# python imports
import os

# MCA python imports
from mca.common import log
from mca.common.sourcecontrol import base


logger = log.MCA_LOGGER

#: The environment variable that decides.
VARIABLE = 'MCA_SOURCE_CONTROL'

#: Name to how to build it, imported only when asked for so that a machine with no Perforce
#: never imports ``winreg``.
BACKENDS = {
    'perforce': 'mca.common.sourcecontrol.perforce:Perforce',
    'none': 'mca.common.sourcecontrol.base:NoSourceControl',
}

#: The order autodetection tries them in. ``none`` is not in it: it is what is left.
DETECTION_ORDER = ('perforce',)

#: Worked out once, because Perforce takes a second to answer and everything asks.
_CURRENT = None


def build(name):
    """
    Make one backend by name.

    :param str name: A key of :data:`BACKENDS`.
    :return: The backend, or None when there is no such name or it could not be imported.
    :rtype: base.SourceControl or None
    """

    path = BACKENDS.get((name or '').strip().lower())
    if not path:
        return None

    module_name, class_name = path.split(':')
    try:
        module = __import__(module_name, fromlist=[class_name])
        return getattr(module, class_name)()
    except Exception as error:                                       # noqa: BLE001
        # A backend that cannot even be built must not stop a DCC starting.
        logger.warning('Could not set up "%s" source control: %s', name, error)
        return None


def current():
    """
    The backend this machine is using.

    :return: Always something - :class:`base.NoSourceControl` when nothing else answers.
    :rtype: base.SourceControl
    """

    global _CURRENT
    if _CURRENT is None:
        _CURRENT = _choose()
        logger.debug('Source control: %s.', _CURRENT.name)

    return _CURRENT


def _choose():
    """
    :return: What ``MCA_SOURCE_CONTROL`` says, or the first backend that is set up here.
    :rtype: base.SourceControl
    """

    asked = os.environ.get(VARIABLE, '').strip().lower()
    if asked:
        backend = build(asked)
        if backend:
            return backend
        logger.warning('%s is set to "%s", which is not a source control the framework knows '
                       'about. Carrying on with none.', VARIABLE, asked)
        return base.NoSourceControl()

    for name in DETECTION_ORDER:
        backend = build(name)
        if backend and backend.available():
            return backend

    return base.NoSourceControl()


def use(name_or_backend):
    """
    Use a particular backend for the rest of this session - for a test, or a tool that knows
    better.

    :param name_or_backend: A name from :data:`BACKENDS`, or a backend.
    :return: What is now in use.
    :rtype: base.SourceControl
    """

    global _CURRENT
    if isinstance(name_or_backend, base.SourceControl):
        _CURRENT = name_or_backend
    else:
        _CURRENT = build(name_or_backend) or base.NoSourceControl()

    return _CURRENT


def reset():
    """
    Forget what was worked out, so the next question asks again. What ``shutdown()`` and the
    suites use.
    """

    global _CURRENT
    _CURRENT = None


# --------------------------------------------------------------------------------------- #
# The front door. Every one of these is the same call on whichever backend is in use, so a
# tool never has to ask which one that is.
# --------------------------------------------------------------------------------------- #
def available():
    """
    :return: Whether this machine has source control set up at all.
    :rtype: bool
    """

    return current().available()


def name():
    """
    :return: What it is called - ``'perforce'``, ``'none'``.
    :rtype: str
    """

    return current().name


def info():
    """
    :return: What it knows about this machine.
    :rtype: dict
    """

    return current().info()


def checkout(paths, changelist=''):
    """
    Make files writable and mark them as being worked on.

    :param paths: One path or many.
    :param str changelist: Where to put them, where that means something.
    :return: How it went.
    :rtype: base.Result
    """

    return current().checkout(paths, changelist=changelist)


def add(paths, changelist=''):
    """
    :param paths: One path or many.
    :param str changelist: Where to put them.
    :return: How it went.
    :rtype: base.Result
    """

    return current().add(paths, changelist=changelist)


def delete(paths, changelist=''):
    """
    :param paths: One path or many.
    :param str changelist: Where to put them.
    :return: How it went.
    :rtype: base.Result
    """

    return current().delete(paths, changelist=changelist)


def revert(paths, unchanged_only=True):
    """
    :param paths: One path or many.
    :param bool unchanged_only: Only the ones nobody has edited.
    :return: How it went.
    :rtype: base.Result
    """

    return current().revert(paths, unchanged_only=unchanged_only)


def sync(paths, force=False):
    """
    :param paths: One path or many.
    :param bool force: Throw local changes away and take the latest.
    :return: How it went.
    :rtype: base.Result
    """

    return current().sync(paths, force=force)


def submit(paths, description=''):
    """
    :param paths: One path or many.
    :param str description: What changed.
    :return: How it went.
    :rtype: base.Result
    """

    return current().submit(paths, description=description)


def add_placeholders(folders):
    """
    Give every empty folder something to store, where source control needs that.

    :param folders: One folder or many.
    :return: The placeholder files that are there afterwards.
    :rtype: list[str]
    """

    return current().add_placeholders(folders)
