"""
One instance of a class, and a way to let go of it.

Letting go is the part that matters here. ``restart()`` exists so a change to the framework
can be picked up without closing Maya, and a singleton that survives a restart is a tool
still holding the old project's paths - looking fine, answering wrong.

The version this replaces had **two** singleton implementations with **two** registries:
``Singleton``, used through a Python 2 ``add_metaclass`` shim, and ``_Singleton``, used
through ``SimpleSingleton``. ``clear_cls()`` and ``teardown()`` only emptied the first one.
Everything that actually inherited ``SimpleSingleton`` - the resource library among them -
could not be cleared at all, by anything, ever. One implementation now, one registry, and
both names still work.
"""

# python imports
from mca.common import log


logger = log.MCA_LOGGER


class Singleton(type):
    """
    A metaclass: a class using it has one instance, built the first time it is asked for.

        class Library(object, metaclass=Singleton):
            ...

    Subclassing one is allowed, and each class gets its own instance. The version this
    replaces refused it outright - ``TypeError: Cannot inherit from singleton class`` - and
    it had to, because it kept the instance in a ``_instance`` attribute on the class, which
    a subclass inherits: parent and child would have shared one object. Keyed by class, that
    cannot happen, so the refusal is not needed and a DCC-specific library can inherit a
    common one.
    """

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in Singleton._instances:
            Singleton._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return Singleton._instances[cls]

    @classmethod
    def instances(mcs):
        """
        :return: Every singleton instance that exists, by class.
        :rtype: dict
        """

        return dict(Singleton._instances)


class SimpleSingleton(object, metaclass=Singleton):
    """
    Inherit this to get a singleton without writing a metaclass.

    The same registry as :class:`Singleton`, which is the whole point: there was one of
    these and one of those, and only half of them could ever be cleared.
    """


def clear_cls(class_or_instance):
    """
    Forget one singleton, so the next call builds a fresh one.

    :param class_or_instance: The class, or the instance it made.
    :return: Whether anything was forgotten.
    :rtype: bool
    """

    for cls, instance in list(Singleton._instances.items()):
        if cls is class_or_instance or instance is class_or_instance:
            # list() first: the old version walked the dictionary it was deleting from,
            # which only survived because it returned before the next step.
            Singleton._instances.pop(cls, None)
            logger.debug('Forgot the single instance of %s.', getattr(cls, '__name__', cls))
            return True
    return False


def teardown():
    """
    Forget every singleton. Called when the framework shuts down or restarts.

    :return: How many were forgotten.
    :rtype: int
    """

    count = len(Singleton._instances)
    Singleton._instances.clear()
    if count:
        logger.debug('Forgot %s singleton instance(s).', count)
    return count
