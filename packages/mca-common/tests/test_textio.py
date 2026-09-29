"""
The data files the pipeline keeps, checked without a DCC.

Every check is something the three modules this replaces got wrong: a missing file that
raised out of a function documented to answer None, a write that emptied the file before it
had the new content, an encoding nobody named, and two readers that disagreed about what to
do with a file that will not parse.

    python tests/test_textio.py
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.textio import alistio, datafile, jsonio, yamlio  # noqa: E402


def body(suite):
    temp = suite.temp

    # ---------------------------------------------------------------- #
    # Round trips
    # ---------------------------------------------------------------- #
    data = {'name': 'Wayward', 'rigs': ['hero', 'villain'], 'count': 3, 'deep': {'a': 1}}

    for name, write, read in (('yaml', yamlio.write_to_yaml_file, yamlio.read_yaml_file),
                              ('json', jsonio.write_to_json_file, jsonio.read_json_file)):
        path = os.path.join(temp, 'round.{}'.format(name))
        written = write(data, path)
        suite.check('{} writes and says where'.format(name),
                    written and os.path.isfile(written), str(written))
        suite.check('and reads back exactly what went in'.format(name), read(path) == data,
                    str(read(path)))

    suite.check('key order survives a yaml round trip, without yamlordereddictloader',
                list(yamlio.read_yaml_file(os.path.join(temp, 'round.yaml'))) ==
                list(data), str(list(yamlio.read_yaml_file(os.path.join(temp, 'round.yaml')))))

    # ---------------------------------------------------------------- #
    # The file that is not there
    # ---------------------------------------------------------------- #
    missing = os.path.join(temp, 'no', 'such', 'file.yaml')
    suite.check('reading a file that does not exist answers None rather than raising - '
                'which is what the old os.stat-before-isfile did',
                yamlio.read_yaml_file(missing) is None)
    suite.check('and the same for json', jsonio.read_json_file(missing) is None)
    suite.check('and a default can be asked for',
                jsonio.read_json_file(missing, default={}) == {})

    empty = os.path.join(temp, 'empty.json')
    open(empty, 'w').close()
    suite.check('an empty file answers the default too',
                jsonio.read_json_file(empty) is None)

    # ---------------------------------------------------------------- #
    # A file that will not parse
    # ---------------------------------------------------------------- #
    broken = os.path.join(temp, 'broken.json')
    with open(broken, 'w', encoding='utf-8') as opened:
        opened.write('{"half": ')
    suite.check('a file that will not parse answers the default, the same for both formats',
                jsonio.read_json_file(broken) is None and
                yamlio.read_yaml_file(broken) is None)
    message = suite.raises('and a caller that would rather stop can ask it to',
                           jsonio.read_json_file, broken, strict=True)
    suite.check('and the refusal names the file and the reason',
                'broken.json' in message, message)

    # ---------------------------------------------------------------- #
    # Writing is atomic
    # ---------------------------------------------------------------- #
    # The point: a write that fails leaves what was there, rather than an empty file. The
    # old version opened the real file 'w' and emptied it before it had anything to put in.
    path = os.path.join(temp, 'precious.json')
    jsonio.write_to_json_file({'keep': 'me'}, path)

    class Unwritable(object):
        """Nothing can turn this into JSON or YAML."""

    suite.check('writing something that cannot be represented answers falsy',
                not jsonio.write_to_json_file({'x': Unwritable()}, path))
    suite.check('and the file that was already there is untouched',
                jsonio.read_json_file(path) == {'keep': 'me'}, str(jsonio.read_json_file(path)))
    suite.check('and no temporary file is left behind',
                not [name for name in os.listdir(temp) if name.endswith('.mca-tmp')],
                str(os.listdir(temp)))

    # ---------------------------------------------------------------- #
    # Encoding
    # ---------------------------------------------------------------- #
    accented = {'artist': 'Zoë', 'note': 'naïve café — 日本'}
    path = os.path.join(temp, 'accents.yaml')
    yamlio.write_to_yaml_file(accented, path)
    suite.check('text that is not ascii survives, because the encoding is named rather than '
                'left to the machine code page',
                yamlio.read_yaml_file(path) == accented, str(yamlio.read_yaml_file(path)))

    # ---------------------------------------------------------------- #
    # Folders
    # ---------------------------------------------------------------- #
    nested = os.path.join(temp, 'made', 'up', 'folders', 'file.json')
    suite.check('writing creates the folders it needs',
                bool(jsonio.write_to_json_file({'a': 1}, nested)) and os.path.isfile(nested))

    # ---------------------------------------------------------------- #
    # .alist, which is YAML becoming JSON
    # ---------------------------------------------------------------- #
    legacy = os.path.join(temp, 'legacy.alist')
    yamlio.write_to_yaml_file({'assets': ['a', 'b']}, legacy)
    suite.check('an .alist written as yaml is recognised as yaml',
                alistio.detect_format(legacy) == 'yaml', str(alistio.detect_format(legacy)))
    suite.check('and read without being told which it is',
                alistio.read_alist_file(legacy) == {'assets': ['a', 'b']},
                str(alistio.read_alist_file(legacy)))

    alistio.write_alist_file({'assets': ['a', 'b', 'c']}, legacy)
    suite.check('and saving it again keeps it as yaml, rather than changing format under '
                'somebody who is diffing it',
                alistio.detect_format(legacy) == 'yaml', str(alistio.detect_format(legacy)))

    fresh = os.path.join(temp, 'fresh.alist')
    alistio.write_alist_file({'assets': []}, fresh)
    suite.check('a new .alist is json', alistio.detect_format(fresh) == 'json',
                str(alistio.detect_format(fresh)))
    suite.check('detecting the format of a file that is not there answers None',
                alistio.detect_format(os.path.join(temp, 'nope.alist')) is None)

    # ---------------------------------------------------------------- #
    # The engine underneath
    # ---------------------------------------------------------------- #
    suite.check('the format of a .yaml is known from its name',
                datafile.format_of('x.yaml') == 'yaml')
    suite.check('and of a .json', datafile.format_of('x.json') == 'json')
    suite.check('and an unfamiliar extension is sniffed',
                datafile.format_of('x.whatever', '{"a": 1}') == 'json' and
                datafile.format_of('x.whatever', 'a: 1') == 'yaml')
    suite.check('validate says what can be written',
                datafile.validate({'a': [1, 2]}) and not datafile.validate({'a': Unwritable()}))
    suite.check('maintain_order is accepted and ignored rather than importing a package '
                'that is not installed everywhere',
                yamlio.read_yaml_file(os.path.join(temp, 'round.yaml'),
                                      maintain_order=True) == data)

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('textio', body))
