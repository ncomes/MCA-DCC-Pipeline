"""
What the framework asks of source control, and what it does when there is none.

One interface, so that a tool saying "check this out before I write to it" does not know or
care whether the studio runs Perforce, Plastic, Git or nothing at all. The version this
replaces had ``mca.common.p4v.perforce`` imported at the top of ``fileio``, which meant that
reading a text file needed Perforce to be importable, and every tool that wanted a file
checked out named Perforce out loud.

Two rules hold for every backend:

- **Nothing raises.** An operation answers a :class:`Result`, which is False when it did not
  work and carries what the tool said. Source control failing must not lose an artist's
  work, and a tool that cannot check a file out should still be able to save it somewhere.
- **Paths are what the caller has**: one path or many, in any order, absolute.
"""

# python imports
import os

# MCA python imports
from mca.common import log


logger = log.MCA_LOGGER


class Result(object):
    """
    How an operation went. Falsy when it did not work, so ``if not sourcecontrol.add(path):``
    reads properly, and carrying the tool's own words for when a person has to be told.
    """

    __slots__ = ('ok', 'message')

    def __init__(self, ok, message=''):
        self.ok = bool(ok)
        self.message = message or ''

    def __bool__(self):
        return self.ok

    # Python 2 is long gone, but Maya 2022's PySide2 stubs still poke at this.
    __nonzero__ = __bool__

    def __repr__(self):
        return 'Result({0}, {1!r})'.format(self.ok, self.message)


def as_paths(paths):
    """
    Whatever the caller passed, as a list of paths.

    :param paths: One path, or any number of them.
    :return: The paths, normalised, with the empty ones dropped.
    :rtype: list[str]

    Four functions in the version this replaces each carried their own
    ``if not isinstance(file_path_list, list): file_path_list = [file_path_list]``, which is
    also wrong for a tuple or a generator - the usual ways a caller has a few paths.
    """

    if paths is None:
        return []
    if isinstance(paths, (str, bytes)):
        paths = [paths]

    return [os.path.normpath(path) for path in paths if path]


class SourceControl(object):
    """
    The interface. A backend answers :attr:`name`, says whether it can be used, and does as
    much of the rest as it can.
    """

    #: What to call it, and what ``MCA_SOURCE_CONTROL`` may be set to.
    name = ''

    #: A file to drop into an otherwise empty folder so that the folder can be stored at all.
    #: Perforce and Git both version files rather than folders, so a freshly made empty folder
    #: cannot be submitted or committed; ``''`` for a backend that does not care.
    placeholder_name = ''

    #: What goes in it, so that whoever finds one knows why it is there.
    placeholder_text = ('A placeholder, so that this folder can be stored in source control.\n'
                        'Safe to delete once the folder has anything else in it.\n')

    def available(self):
        """
        :return: Whether this machine can actually talk to it right now - the client is
            installed, and it knows which workspace it is in.
        :rtype: bool
        """

        raise NotImplementedError

    def info(self):
        """
        :return: What it knows about this machine: ``user``, ``workspace``, ``port``, and
            whatever else the backend has. Empty when it is not set up.
        :rtype: dict
        """

        raise NotImplementedError

    def add_placeholders(self, folders):
        """
        Give every empty folder something to store, and mark it for adding.

        :param folders: One folder or many.
        :return: The placeholder files that are there afterwards, for a caller that wants to
            submit them. Empty when this backend needs none, or when every folder already has
            something in it.
        :rtype: list[str]

        The same for every backend that versions files rather than folders, which is all of
        them - only :attr:`placeholder_name` differs. The version this replaces had it in
        ``fileio``, calling Perforce from a file helper.
        """

        if not self.placeholder_name:
            return []

        written = []
        for folder in as_paths(folders):
            if not os.path.isdir(folder):
                continue
            # Anything other than our own marker means the folder has something to store.
            contents = os.listdir(folder)
            if contents and contents != [self.placeholder_name]:
                continue

            marker = os.path.join(folder, self.placeholder_name)
            if not os.path.isfile(marker):
                try:
                    with open(marker, 'w', encoding='utf-8') as opened:
                        opened.write(self.placeholder_text)
                except OSError as error:
                    logger.warning('Could not write a placeholder in %s: %s', folder, error)
                    continue
            written.append(marker)

        if written:
            self.add(written)

        return written

    def checkout(self, paths, changelist=''):
        """
        Make files writable and mark them as being worked on - an edit, an add or a delete,
        whichever each file needs.

        :param paths: One path or many.
        :param str changelist: Where to put them, when the backend has such a thing.
        :return: How it went.
        :rtype: Result
        """

        raise NotImplementedError

    def add(self, paths, changelist=''):
        """
        Put new files under source control.

        :param paths: One path or many.
        :param str changelist: Where to put them.
        :return: How it went.
        :rtype: Result
        """

        raise NotImplementedError

    def delete(self, paths, changelist=''):
        """
        Mark files to be deleted.

        :param paths: One path or many.
        :param str changelist: Where to put them.
        :return: How it went.
        :rtype: Result
        """

        raise NotImplementedError

    def revert(self, paths, unchanged_only=True):
        """
        Give files back.

        :param paths: One path or many.
        :param bool unchanged_only: True only gives back the ones nobody has edited, which
            is the safe thing and the default.
        :return: How it went.
        :rtype: Result
        """

        raise NotImplementedError

    def sync(self, paths, force=False):
        """
        Fetch the latest of some files.

        :param paths: One path or many.
        :param bool force: Throw away local changes and take the latest.
        :return: How it went.
        :rtype: Result
        """

        raise NotImplementedError

    def submit(self, paths, description=''):
        """
        Send files in.

        :param paths: One path or many.
        :param str description: What changed, for the history.
        :return: How it went.
        :rtype: Result
        """

        raise NotImplementedError


class NoSourceControl(SourceControl):
    """
    The backend for a machine with no source control - a contractor's laptop, a build agent,
    a clone of the repository somebody is reading on a train.

    Every operation **succeeds**, and says it did nothing. That is deliberate: a tool's job
    is to save the file, and "there is no Perforce here" is not a reason to stop. It is the
    caller's business if it wants to care, and :meth:`available` is how it asks.
    """

    name = 'none'

    #: Nothing to store, so nothing needs a marker to store it.
    placeholder_name = ''

    def available(self):
        return False

    def info(self):
        return {}

    def _nothing(self):
        """
        :return: A success that did nothing.
        :rtype: Result
        """

        return Result(True, 'No source control is set up on this machine.')

    def checkout(self, paths, changelist=''):
        return self._nothing()

    def add(self, paths, changelist=''):
        return self._nothing()

    def delete(self, paths, changelist=''):
        return self._nothing()

    def revert(self, paths, unchanged_only=True):
        return self._nothing()

    def sync(self, paths, force=False):
        return self._nothing()

    def submit(self, paths, description=''):
        return self._nothing()
