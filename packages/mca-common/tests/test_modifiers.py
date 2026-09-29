"""
The decorators and the singleton, checked without a DCC.

    python tests/test_modifiers.py
"""

# python imports
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common import log  # noqa: E402
from mca.common.modifiers import decorators, singleton  # noqa: E402


class Recorder(logging.Handler):
    """Keeps what was logged, so a check can look at it."""

    def __init__(self):
        super(Recorder, self).__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def body(suite):
    recorder = Recorder()
    log.MCA_LOGGER.addHandler(recorder)
    previous_level = log.MCA_LOGGER.level
    log.MCA_LOGGER.setLevel(logging.DEBUG)

    try:
        # ------------------------------------------------------------ #
        # timestamp: the one that broke everything it touched
        # ------------------------------------------------------------ #
        @decorators.timestamp
        def counted(a, b=2):
            return a + b

        # func_name is a Python 2 attribute. Reading it raises on every interpreter this
        # framework runs on, so @timestamp made the function it decorated unusable.
        suite.check('a timestamped function still works, and answers what it always did',
                    counted(1, b=3) == 4)
        suite.check('and its name survives the decorator', counted.__name__ == 'counted')
        suite.check('and how long it took was logged',
                    any('counted' in line and 'seconds' in line for line in recorder.lines),
                    str(recorder.lines[-2:]))

        @decorators.timestamp
        def angry():
            raise ValueError('no')

        suite.raises('and a function that raises still raises through it', angry)
        suite.check('and its time was still logged, because the logging is in a finally',
                    any('angry' in line for line in recorder.lines), str(recorder.lines[-2:]))

        # ------------------------------------------------------------ #
        # debug
        # ------------------------------------------------------------ #
        class Tool(object):
            @decorators.debug
            def run(self):
                return 'ran'

        recorder.lines = []
        suite.check('a debugged method answers normally', Tool().run() == 'ran')
        suite.check('and is logged by its full name, rather than joined with a separator '
                    'that could never appear',
                    any('Tool.run' in line for line in recorder.lines), str(recorder.lines))

        # ------------------------------------------------------------ #
        # error: reports and swallows, on purpose
        # ------------------------------------------------------------ #
        recorder.lines = []

        @decorators.error
        def falls_over():
            raise RuntimeError('the rig is inside out')

        answer = falls_over()
        suite.check('a function wearing @error answers None instead of raising, which is '
                    'what keeps the DCC open', answer is None)
        suite.check('and what went wrong is logged, with where it was',
                    any('inside out' in line for line in recorder.lines), str(recorder.lines))

        @decorators.error
        def fine():
            return 'result'

        suite.check('and a function that works is untouched', fine() == 'result')

        # ------------------------------------------------------------ #
        # abstractmethod
        # ------------------------------------------------------------ #
        class Base(object):
            @decorators.abstractmethod
            def export(self):
                return 'the base'

        os.environ.pop(decorators.ABSTRACT_MODE_VARIABLE, None)
        message = suite.raises('an abstract method nobody overrode refuses', Base().export)
        suite.check('and says which one it was',
                    'export' in message, message)

        os.environ[decorators.ABSTRACT_MODE_VARIABLE] = 'warn'
        recorder.lines = []
        suite.check('and in warn mode it runs the base and says so',
                    Base().export() == 'the base' and
                    any('override' in line for line in recorder.lines), str(recorder.lines))
        os.environ.pop(decorators.ABSTRACT_MODE_VARIABLE, None)

        class Maya(Base):
            def export(self):
                return 'maya'

        suite.check('an overridden one is just a method', Maya().export() == 'maya')

        # ------------------------------------------------------------ #
        # repeater
        # ------------------------------------------------------------ #
        ticks = []

        @decorators.repeater(0.01, limit=3)
        def tick():
            ticks.append(1)

        running = tick()
        for _ in range(200):
            if running.calls >= 3:
                break
            time.sleep(0.01)
        running.stop()
        suite.check('a repeating call runs the number of times it was asked to',
                    len(ticks) == 3, str(len(ticks)))
        suite.check('and answers something that can stop it', not running.running)

        # The one that used to kill the thread: an exception inside the repeated call.
        failures = []

        @decorators.repeater(0.01, limit=3)
        def unreliable():
            failures.append(1)
            raise RuntimeError('every time')

        running = unreliable()
        for _ in range(200):
            if running.calls >= 3:
                break
            time.sleep(0.01)
        running.stop()
        suite.check('a call that raises does not kill the timer thread - it used to stop '
                    'repeating with nothing saying why',
                    len(failures) == 3 and running.failures == 3,
                    '{} calls, {} failures'.format(len(failures), running.failures))

        # ------------------------------------------------------------ #
        # The singleton, and letting go of it
        # ------------------------------------------------------------ #
        singleton.teardown()

        class Library(singleton.SimpleSingleton):
            def __init__(self):
                self.built = time.time()

        class Other(object, metaclass=singleton.Singleton):
            pass

        first, second = Library(), Library()
        suite.check('a singleton is built once', first is second)
        suite.check('and a different class gets its own', Other() is not first)

        # The bug: SimpleSingleton and Singleton kept separate registries, and clear_cls
        # and teardown only emptied one - so anything inheriting SimpleSingleton, the
        # resource library included, could never be cleared by anything.
        suite.check('clearing one built through SimpleSingleton really clears it',
                    singleton.clear_cls(Library) and Library() is not first)
        suite.check('and clearing by instance works too',
                    singleton.clear_cls(Library()) is True)
        suite.check('clearing something that was never a singleton answers False',
                    singleton.clear_cls(object()) is False)

        Library()
        Other()
        suite.check('teardown forgets every one of them, whichever way they were made',
                    singleton.teardown() == 2 and singleton.Singleton.instances() == {},
                    str(singleton.Singleton.instances()))

        # The old version refused this outright, and had to: it kept the instance in a
        # class attribute, which a subclass inherits, so parent and child would have shared
        # one object. Keyed by class, they each get their own - which is what a DCC-specific
        # library inheriting a common one needs.
        class MayaLibrary(Library):
            pass

        common, maya = Library(), MayaLibrary()
        suite.check('a subclass of a singleton gets its own instance rather than being '
                    'refused', common is not maya and isinstance(maya, Library),
                    '{} / {}'.format(common, maya))
        suite.check('and each of them is still a singleton in its own right',
                    Library() is common and MayaLibrary() is maya)

    finally:
        log.MCA_LOGGER.removeHandler(recorder)
        log.MCA_LOGGER.setLevel(previous_level)

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('modifiers', body))
