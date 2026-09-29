"""
File operations, checked without a DCC.

    python tests/test_fileio.py
"""

# python imports
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.utils import fileio  # noqa: E402


def body(suite):
    temp = suite.temp

    # ---------------------------------------------------------------- #
    # It does not drag source control in with it
    # ---------------------------------------------------------------- #
    # The version this replaces imported mca.common.p4v.perforce at module scope, so nothing
    # could read a text file on a machine without Perforce.
    pulled_in = sorted(name for name in sys.modules
                       if 'p4v' in name or 'perforce' in name or 'plastic' in name)
    suite.check('importing it does not drag source control in with it',
                not pulled_in, str(pulled_in))

    # ---------------------------------------------------------------- #
    # Making paths usable
    # ---------------------------------------------------------------- #
    nested = os.path.join(temp, 'a', 'b', 'c', 'file.txt')
    fileio.touch_path(nested)
    suite.check('touching a path makes the folder it needs',
                os.path.isdir(os.path.dirname(nested)))

    made = fileio.create_file('file.txt', os.path.join(temp, 'a', 'b', 'c'))
    suite.check('a file can be created', bool(made) and os.path.isfile(made), str(made))
    suite.check('and a name with illegal characters is cleaned rather than raising',
                os.path.basename(fileio.create_file('a:b?c.txt', temp)) == 'a_b_c.txt',
                fileio.create_file('a:b?c.txt', temp))

    fileio.touch_path(made, remove=True)
    suite.check('and touching with remove takes it away', not os.path.isfile(made))

    # ---------------------------------------------------------------- #
    # Reading and writing text
    # ---------------------------------------------------------------- #
    path = os.path.join(temp, 'lines.txt')
    suite.check('writing lines works', fileio.write_lines(path, ['one', 'two']))
    suite.check('and reads back as the lines that went in',
                fileio.get_file_lines(path) == ['one', 'two'],
                str(fileio.get_file_lines(path)))

    fileio.write_line(path, 'three', append=True)
    suite.check('appending a line puts it on a line of its own - the old version built the '
                'line it meant to append and then wrote a different one',
                fileio.get_file_lines(path) == ['one', 'two', 'three'],
                str(fileio.get_file_lines(path)))

    accented = 'naïve café — 日本'
    fileio.write_lines(path, [accented])
    suite.check('text that is not ascii survives the round trip',
                fileio.get_file_text(path) == accented, fileio.get_file_text(path))

    suite.check('reading a file that is not there answers the default rather than raising',
                fileio.get_file_text(os.path.join(temp, 'nope.txt')) == '')
    suite.check('and its lines are an empty list',
                fileio.get_file_lines(os.path.join(temp, 'nope.txt')) == [])

    # ---------------------------------------------------------------- #
    # Replacing text
    # ---------------------------------------------------------------- #
    path = os.path.join(temp, 'replace.txt')
    fileio.write_lines(path, ['alpha beta', 'beta gamma', 'delta'])
    changed = fileio.replace(path, 'beta', 'BETA')
    suite.check('replacing text says how many lines it changed', changed == 2, str(changed))
    suite.check('and changed them', fileio.get_file_lines(path) ==
                ['alpha BETA', 'BETA gamma', 'delta'], str(fileio.get_file_lines(path)))
    suite.check('replacing in a file that is not there answers -1 rather than deleting '
                'anything', fileio.replace(os.path.join(temp, 'nope.txt'), 'a', 'b') == -1)
    suite.check('and leaves no temporary file behind',
                not [name for name in os.listdir(temp) if name.endswith('.mca-tmp')],
                str(os.listdir(temp)))

    # ---------------------------------------------------------------- #
    # Copying, moving, renaming
    # ---------------------------------------------------------------- #
    source = os.path.join(temp, 'source.ma')
    fileio.write_line(source, 'a scene')
    folder = os.path.join(temp, 'copies')
    os.makedirs(folder)

    copied = fileio.copy_file(source, folder)
    suite.check('copying into a folder keeps the file name',
                copied == os.path.join(folder, 'source.ma'), str(copied))

    # The old version joined the name onto the destination whenever the destination existed,
    # including when it was a file, which made C:/x/old.ma/new.ma.
    over = os.path.join(folder, 'existing.ma')
    fileio.write_line(over, 'older')
    copied = fileio.copy_file(source, over)
    suite.check('copying over an existing file replaces it, rather than making a path '
                'through it', copied == over and fileio.get_file_text(over) == 'a scene\n'
                or fileio.get_file_text(over).strip() == 'a scene', str(copied))

    suite.check('copying something that is not there answers empty',
                fileio.copy_file(os.path.join(temp, 'nope.ma'), folder) == '')

    moved = fileio.move_file(copied, os.path.join(temp, 'moved.ma'))
    suite.check('moving answers where it went', moved.endswith('moved.ma'), str(moved))
    suite.check('and it really is there, and not where it was',
                os.path.isfile(moved) and not os.path.isfile(copied))

    renamed = fileio.rename_file('moved.ma', temp, 'renamed.ma')
    suite.check('renaming answers the new path', renamed.endswith('renamed.ma'), renamed)
    suite.check('renaming onto a name that is taken refuses and says so',
                fileio.rename_file('renamed.ma', temp, 'source.ma').endswith('renamed.ma'))

    # ---------------------------------------------------------------- #
    # Telling you about a file
    # ---------------------------------------------------------------- #
    suite.check('the size of a file that is not there is 0.0, not a raise',
                fileio.get_file_size(os.path.join(temp, 'nope.ma')) == 0.0)
    suite.check('a real file has a size', fileio.get_file_size(source) >= 0.0)

    stamp = fileio.get_file_timestamp_in_utc(source)
    suite.check('the utc timestamp is a real aware datetime, without pytz',
                stamp is not None and stamp.tzinfo is not None, str(stamp))
    suite.check('and a missing file answers None',
                fileio.get_file_timestamp_in_utc(os.path.join(temp, 'nope.ma')) is None)

    # The old one read the access time under the name "last modified", and padded a
    # single-digit second on the wrong side, so five seconds past printed as :50.
    when = time.localtime(time.time())
    written = fileio.get_last_modified_date(source)
    suite.check('the modified date is the modified time, formatted for a person',
                written.startswith('{:02d}-'.format(when.tm_mday)), written)
    seconds = written.rsplit(':', 1)[-1]
    suite.check('and its seconds are padded on the left, so five seconds is 05 and not 50',
                len(seconds) == 2 and int(seconds) == time.localtime(
                    os.path.getmtime(source)).tm_sec, written)
    suite.check('year-first can be asked for',
                fileio.get_last_modified_date(source, reverse_date=True).startswith(
                    str(when.tm_year)), fileio.get_last_modified_date(source, True))

    # ---------------------------------------------------------------- #
    # Names
    # ---------------------------------------------------------------- #
    suite.check('an extension comes off',
                fileio.remove_extension(os.path.join('C:', 'test', 'file.py')).endswith('file'))
    suite.check('a path with no extension is left alone',
                fileio.remove_extension('file') == 'file')
    suite.check('and a dot in a folder name is not mistaken for one',
                fileio.remove_extension(os.path.join('C:', 'v1.2', 'file')) ==
                os.path.join('C:', 'v1.2', 'file'))
    suite.check('a name that is nothing but illegal characters still answers something '
                'writable', fileio.safe_file_name('///') == '___' or
                fileio.safe_file_name('///') == 'untitled', fileio.safe_file_name('///'))

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('fileio', body))
