"""
The data helpers: lists, strings, dictionaries, objects and the clock.

    python tests/test_utils.py
"""

# python imports
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

from mca.common.utils import (dict_utils, lists, methods, pyutils, strings,  # noqa: E402
                              timedate)


def body(suite):
    # ---------------------------------------------------------------- #
    # lists: the off-by-one that hid the only item in a list
    # ---------------------------------------------------------------- #
    # len(list) > abs(index) is wrong for negative indices, so the last item of a one-item
    # list answered the default. One spine, one root, one of anything is the normal case.
    suite.check('the last item of a one-item list is that item',
                lists.get_last_in_list(['hero']) == 'hero',
                str(lists.get_last_in_list(['hero'])))
    suite.check('and counting back from the end reaches the front',
                lists.get_index_in_list(['a', 'b'], -2) == 'a',
                str(lists.get_index_in_list(['a', 'b'], -2)))
    suite.check('an empty list still answers the default',
                lists.get_last_in_list([], 'nothing') == 'nothing' and
                lists.get_first_in_list([]) is None)
    suite.check('and an index nobody has answers it too',
                lists.get_index_in_list(['a'], 5, 'no') == 'no' and
                lists.get_index_in_list(['a'], -5, 'no') == 'no')
    suite.check('which index exists is asked the same way',
                lists.index_exists_in_list(['a', 'b'], -1) and
                lists.index_exists_in_list(['a', 'b'], 1) and
                not lists.index_exists_in_list(['a', 'b'], 2) and
                not lists.index_exists_in_list([], 0))

    suite.check('anything can be made a list',
                lists.force_list(None) == [] and lists.force_list('one') == ['one'] and
                lists.force_list(('a', 'b')) == ['a', 'b'] and
                lists.force_list(['a']) == ['a'])
    suite.check('and a tuple', lists.force_tuple(None) == () and
                lists.force_tuple('one') == ('one',) and
                lists.force_tuple(['a', 'b']) == ('a', 'b'))

    suite.check('duplicates are found once each',
                lists.get_duplicates(['a', 'b', 'a', 'c', 'a']) == ['a', 'a'],
                str(lists.get_duplicates(['a', 'b', 'a', 'c', 'a'])))
    suite.check('the commonest item is found, and nothing answers None',
                lists.get_most_common_item_in_list(['a', 'b', 'b']) == 'b' and
                lists.get_most_common_item_in_list([]) is None)
    suite.check('a list can be walked two at a time',
                list(lists.pairwise([1, 2, 3, 4])) == [(1, 2), (3, 4)])
    suite.check('nested lists flatten, however deep',
                lists.flatten_list([1, [2, [3, [4]]], 5]) == [1, 2, 3, 4, 5],
                str(lists.flatten_list([1, [2, [3, [4]]], 5])))
    suite.check('and Nones can be taken out',
                lists.remove_none([1, None, 2, None]) == [1, 2])

    suite.check('a value can be set past the end of a list',
                lists.set_list_value_at([1, 2], 4, 'x') == [1, 2, None, None, 'x'],
                str(lists.set_list_value_at([1, 2], 4, 'x')))
    suite.check('and before the start of one',
                lists.set_list_value_at([2, 3], -2, 0) == [0, None, 2, 3],
                str(lists.set_list_value_at([2, 3], -2, 0)))
    original = [1, 2]
    lists.set_list_value_at(original, 4, 'x')
    suite.check('without changing the list it was given', original == [1, 2], str(original))
    suite.raises('and an index that is not a whole number is refused',
                 lists.set_list_value_at, [1], 'two', 'x')

    # ---------------------------------------------------------------- #
    # strings
    # ---------------------------------------------------------------- #
    # Documented as replacing / and \ both; it replaced \, and / only when the whole string
    # was one slash - so 'rig/hero' went on to be used as a file name unchanged.
    suite.check('both path separators come out of a name meant for a file',
                strings.clean_file_string('rig/hero') == 'rig_hero' and
                strings.clean_file_string(r'rig\hero') == 'rig_hero',
                strings.clean_file_string('rig/hero'))
    suite.check('and the rest of what a file system refuses',
                strings.clean_file_string('a:b?c') == 'a_b_c')

    # It answered a map object, so len() raised and a second walk found nothing - and it
    # took digits one at a time.
    numbers = strings.get_numbers_from_string('spine_012_to_014')
    suite.check('numbers come out of a name whole, and as a list',
                numbers == [12, 14], str(numbers))
    suite.check('and the same list can be read twice', len(numbers) == 2 and
                list(numbers) == [12, 14])
    suite.check('they can be had as text too',
                strings.get_numbers_from_string('vtx[12]', as_string=True) == ['12'])
    suite.check('a trailing number is read on its own',
                strings.get_trailing_numbers('spine_04') == 4 and
                strings.get_trailing_numbers('spine') is None and
                strings.get_trailing_numbers(None) is None)

    suite.check('an extension is added once and only when it is missing',
                strings.append_extension('scene', 'ma') == 'scene.ma' and
                strings.append_extension('scene.ma', '.ma') == 'scene.ma' and
                strings.append_extension('scene.', 'ma') == 'scene.ma')

    suite.check('a random string starts with a letter when it has to',
                strings.generate_random_string(6)[0].isalpha())
    suite.check('and an impossible length answers empty rather than None',
                strings.generate_random_string(0) == '')
    suite.check('a guid comes out in the right shape',
                re.match(r'^\w{4}-\w{5}-\w{5}-\w{4}$', strings.generate_guid()) is not None,
                strings.generate_guid())

    suite.check('a namespace is the first three letters, lower case',
                strings.create_namespace('SampleGame') == 'sam')
    suite.check('and no name answers three random letters rather than raising TypeError',
                len(strings.create_namespace(None)) == 3)

    # obj.im_class is Python 2 only, so describing a method raised AttributeError.
    class Thing(object):
        def method(self):
            pass

    suite.check('a method can be described without a Python 2 attribute',
                'method' in strings.debug_object_string(Thing().method, 'nope'),
                strings.debug_object_string(Thing().method, 'nope'))
    suite.check('and so can anything else, rather than answering None',
                strings.debug_object_string(42, 'nope') is not None,
                strings.debug_object_string(42, 'nope'))

    # ---------------------------------------------------------------- #
    # methods: the one that always answered nothing
    # ---------------------------------------------------------------- #
    class Rig(object):
        name = 'hero'
        joints = 12

        def build(self):
            pass

    # The append sat inside `if filter_out:`, so the ordinary call found everything and
    # then returned an empty list.
    names = methods.get_property_names(Rig())
    suite.check('reading what is on an object with no filter really answers what is on it',
                sorted(names) == ['joints', 'name'], str(names))
    suite.check('and a filter takes things out',
                methods.get_property_names(Rig(), ['joints']) == ['name'])
    suite.check('methods are not properties', 'build' not in names)

    # ---------------------------------------------------------------- #
    # dictionaries
    # ---------------------------------------------------------------- #
    sliced = dict_utils.get_dict_slice({'a': [1, 2], 'b': [3]}, 1, 'none')
    suite.check('the same position is taken from every list',
                sliced == {'a': 2, 'b': 'none'}, str(sliced))
    suite.check('merging keeps what is underneath where the top says nothing',
                dict_utils.merge({'a': 1, 'nested': {'x': 1, 'y': 2}},
                                 {'nested': {'y': 9}}) ==
                {'a': 1, 'nested': {'x': 1, 'y': 9}},
                str(dict_utils.merge({'a': 1, 'nested': {'x': 1, 'y': 2}},
                                     {'nested': {'y': 9}})))

    # ---------------------------------------------------------------- #
    # ObjectDict: writing through a nested value
    # ---------------------------------------------------------------- #
    settings = pyutils.ObjectDict({'window': {'width': 800}, 'name': 'tool'})
    suite.check('a key can be read as an attribute', settings.name == 'tool')
    settings.window.width = 1024
    suite.check('and writing through a nested one really writes - it used to answer a copy '
                'and throw the change away',
                settings['window']['width'] == 1024, str(settings))
    settings.other = 'new'
    suite.check('a new attribute becomes a key', settings['other'] == 'new')
    suite.raises('and a key nobody set raises AttributeError, not KeyError',
                 getattr, settings, 'nothing')

    # ---------------------------------------------------------------- #
    # paths and the environment
    # ---------------------------------------------------------------- #
    folder, name, extension = pyutils.split_path(os.path.join('C:', 'art', 'hero.ma'))
    suite.check('a path splits into its three parts',
                (name, extension) == ('hero', '.ma'), str((folder, name, extension)))

    os.environ.pop('MCA_TEST_PATHS', None)
    pyutils.append_path_env_var('MCA_TEST_PATHS', 'one')
    pyutils.append_path_env_var('MCA_TEST_PATHS', 'two')
    pyutils.append_path_env_var('MCA_TEST_PATHS', 'one')
    suite.check('a path is added once and kept in order',
                os.environ['MCA_TEST_PATHS'] == os.pathsep.join(['one', 'two']),
                os.environ['MCA_TEST_PATHS'])
    pyutils.prepend_path_env_var('MCA_TEST_PATHS', 'first')
    suite.check('and one can be put in front, where it wins',
                os.environ['MCA_TEST_PATHS'].split(os.pathsep)[0] == 'first',
                os.environ['MCA_TEST_PATHS'])
    os.environ.pop('MCA_TEST_PATHS', None)

    suite.check('the user has a display name, on this machine as well as on Windows',
                bool(pyutils.get_user_display_name()), pyutils.get_user_display_name())

    # ---------------------------------------------------------------- #
    # the clock: seconds padded on the wrong side
    # ---------------------------------------------------------------- #
    # second += '0' turned five seconds past the minute into :50, in three places.
    for attempt in range(3):
        now = time.localtime()
        written = timedate.get_current_time()
        if time.localtime().tm_sec == now.tm_sec:
            break
    seconds = written.rsplit(':', 1)[-1]
    suite.check('the seconds are padded on the left, so five past reads as 05',
                len(seconds) == 2 and int(seconds) == now.tm_sec, written)
    suite.check('the date reads day first by default, padded',
                timedate.get_current_date().startswith('{:02d}-'.format(now.tm_mday)),
                timedate.get_current_date())
    suite.check('and year first when asked',
                timedate.get_current_date(reverse_date=True).startswith(str(now.tm_year)),
                timedate.get_current_date(reverse_date=True))
    suite.check('a separator can be chosen',
                timedate.get_current_date(separator='/').count('/') == 2,
                timedate.get_current_date(separator='/'))
    suite.check('the time alone is just the time',
                re.match(r'^\d{2}:\d{2}:\d{2}$', timedate.get_current_time(False))
                is not None, timedate.get_current_time(False))
    suite.check('date and time together read the same way',
                re.match(r'^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$',
                         timedate.get_date_and_time()) is not None,
                timedate.get_date_and_time())
    suite.check('another timezone answers a time rather than needing pytz',
                re.match(r'^\d{2}:\d{2}:\d{2}$', timedate.get_current_pst_time()) is not None,
                timedate.get_current_pst_time())
    suite.check('and this machine can say what timezone it is in',
                isinstance(timedate.get_time_zone(), str))

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('utils', body))
