"""
The toolbox: the artists' tool palettes, their files, and the API that edits them.

    python tests/test_toolbox.py

The headless half needs no Qt. The widget is built offscreen where PySide is installed.
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from mca.common import sourcecontrol  # noqa: E402
from mca.common.tools.toolbox import toolbox_api, toolbox_library, toolbox_model  # noqa: E402
from mca.common.tools.toolbox import toolbox_runner, toolbox_vcs  # noqa: E402


def body(suite):
    sourcecontrol.use('none')

    shared_root = os.path.join(suite.temp, 'shared', 'Toolbox')
    local_root = os.path.join(suite.temp, 'local', 'Toolbox')
    os.makedirs(shared_root)
    os.makedirs(local_root)

    # ---------------------------------------------------------------- #
    # which backend writes a shared file
    # ---------------------------------------------------------------- #
    # The library defaulted to P4Backend outright, so on a machine with no Perforce every
    # `p4 fstat` came back "not installed", prepare_edit read that as a file it could not check
    # out, and every edit to a shared toolbox failed with an error box.
    suite.check('with no Perforce on the machine, shared files are written straight to disk',
                type(toolbox_vcs.shared_backend()).__name__ == 'LocalBackend',
                type(toolbox_vcs.shared_backend()).__name__)

    local = toolbox_vcs.LocalBackend()
    read_only = os.path.join(suite.temp, 'read_only.yaml')
    with open(read_only, 'w', encoding='utf-8') as opened:
        opened.write('name: x\n')
    os.chmod(read_only, 0o444)
    try:
        if os.access(read_only, os.W_OK):
            # Running as root, which can write a read-only file regardless, so there is nothing
            # here to refuse.
            suite.check('a read-only file is refused before anything is written', True,
                        'skipped: this process can write read-only files')
            suite.check('and the refusal is written for an artist, naming the file', True,
                        'skipped')
        else:
            message = suite.raises('a read-only file is refused before anything is written',
                                   local.prepare_edit, read_only)
            suite.check('and the refusal is written for an artist, naming the file',
                        'read_only.yaml' in message, message)
    finally:
        os.chmod(read_only, 0o644)
    suite.check('a writable file is prepared with nothing to say about it',
                local.prepare_edit(read_only) == [] and
                local.after_write(read_only, False) == [])
    suite.check('and deleting one takes it off disk',
                local.delete(read_only) == [] and not os.path.isfile(read_only))

    # ---------------------------------------------------------------- #
    # the data, and the files it lives in
    # ---------------------------------------------------------------- #
    item = toolbox_model.ToolboxItem(name='Build A Rig', item_type='button',
                                     command={'code': 'print("hello")'},
                                     tooltip='Builds one', tags=['rigging'])
    suite.check('an item gets an id of its own and knows it has something to run',
                item.id and item.has_command)
    suite.check('and its id stays readable, with something unique on the end, so a file name '
                'and a history entry can be read by a person',
                item.id.startswith('build_a_rig_') and
                toolbox_model.make_id('Build A Rig') != item.id,
                item.id)
    suite.check('its search text covers its name, tooltip and tags',
                'rig' in item.search_text() and 'builds one' in item.search_text(),
                item.search_text())
    copy = item.copy(new_id=True)
    suite.check('a copy is the same item with a different id',
                copy.name == item.name and copy.id != item.id)

    section = toolbox_model.ToolboxSection(name='Rigging Tools', items=[item])
    suite.check('a section finds its items by id, and knows where they are',
                section.get_item(item.id) is item and section.index_of(item.id) == 0)
    suite.check('and an item it has never heard of is None, not a raise',
                section.get_item('nothing') is None)

    path = os.path.join(suite.temp, 'section.yaml')
    toolbox_model.write_yaml(path, section.to_dict())
    again = toolbox_model.ToolboxSection.from_dict(toolbox_model.read_yaml(path))
    suite.check('a section goes to YAML and comes back the same',
                again.name == 'Rigging Tools' and len(again.items) == 1 and
                again.items[0].name == 'Build A Rig',
                str(again))
    suite.check('a colour is normalised however it was written, and three digits become six',
                toolbox_model.normalize_color('#ABCDEF') == '#abcdef' and
                toolbox_model.normalize_color('abc') == '#aabbcc' and
                toolbox_model.normalize_color([255, 0, 128]) == '#ff0080')
    suite.check('and no colour at all is None, which is what clears one',
                toolbox_model.normalize_color('') is None and
                toolbox_model.normalize_color('not a colour') is None)

    # ---------------------------------------------------------------- #
    # the library, and the API over it
    # ---------------------------------------------------------------- #
    library = toolbox_library.ToolboxLibrary(dcc='Maya', shared_root=shared_root,
                                            local_root=local_root)
    toolbox_api.set_library(library)

    listed = toolbox_api.list_toolboxes()
    suite.check('a library with nothing in it still has All Tools',
                listed['ok'] and toolbox_model.ALL_TOOLS in
                [row['name'] for row in listed['result']], str(listed))

    made = toolbox_api.create_toolbox('Animation', shared=True)
    suite.check('a toolbox can be made', made['ok'], made['message'])
    suite.check('and making it twice is refused rather than wiping the first',
                toolbox_api.create_toolbox('Animation', shared=True)['ok'] is False)

    added = toolbox_api.add_section('Animation', 'Playback', background='#223344')
    suite.check('a section can be added to it, with a colour',
                added['ok'], added['message'])
    section_id = added['result']

    first = toolbox_api.add_item(section_id, 'Play', code='print("play")', tooltip='Plays')
    suite.check('an item can be added to the section', first['ok'], first['message'])
    item_id = first['result']['item_id']
    second = toolbox_api.add_item(section_id, 'Stop', code='print("stop")')
    suite.check('and another', second['ok'])

    suite.check('an item is found by searching for it',
                'Play' in [row['name'] for row in toolbox_api.find_items('play')['result']],
                str(toolbox_api.find_items('play')['result']))
    suite.check('and read back by its id',
                toolbox_api.get_item(item_id)['result']['name'] == 'Play')
    suite.check('an id nobody has is refused rather than answering nothing',
                toolbox_api.get_item('not-an-id')['ok'] is False)

    suite.check('an item can be renamed and given different code',
                toolbox_api.update_item(item_id, name='Play Forward',
                                        code='print("forward")')['ok'] and
                toolbox_api.get_item(item_id)['result']['name'] == 'Play Forward')
    suite.check('given a colour, which belongs to the toolbox rather than the section',
                toolbox_api.set_item_color('Animation', item_id, '#ff0000')['ok'])
    suite.check('duplicated',
                toolbox_api.duplicate_item(item_id)['ok'])
    suite.check('and moved within its section',
                toolbox_api.move_item(item_id, section_id)['ok'])

    # An item is allowed no command - a label or an embedded panel has nothing to run - and it
    # says so rather than pretending otherwise.
    empty = toolbox_api.add_item(section_id, 'Just A Label')
    suite.check('an item with nothing to run is allowed, since not every item runs something',
                empty['ok'], empty['message'])
    suite.check('and it knows it has no command',
                not library.find_item(empty['result']['item_id'])[1].has_command)

    # ---------------------------------------------------------------- #
    # running what an item says
    # ---------------------------------------------------------------- #
    ran = toolbox_runner.run_command({'code': 'result = 6 * 7'}, label='suite')
    suite.check('an item\'s code runs and says it worked', bool(ran), ran.error)
    broke = toolbox_runner.run_command({'code': 'raise ValueError("no")'}, label='suite')
    suite.check('and code that raises is a failure carrying the message, not a raise '
                'into whatever asked',
                not broke and 'no' in broke.error, broke.error)
    missing = toolbox_runner.run_command({'kind': toolbox_model.COMMAND_CALLABLE,
                                         'target': 'nothing.at.all:ever'})
    suite.check('a target nobody can import is a failure that says so, not a raise',
                not missing and missing.error, missing.error)

    callable_kind = toolbox_model.COMMAND_CALLABLE
    problems = toolbox_runner.check_command({'kind': callable_kind,
                                            'target': 'mca.common.nothing:missing'})
    suite.check('a static check finds a tool whose module is not there, without importing it',
                problems, str(problems))
    suite.check('and one whose module is there but has no such function',
                toolbox_runner.check_command({'kind': callable_kind,
                                              'target': 'mca.common.log:no_such_thing'}),
                str(toolbox_runner.check_command({'kind': callable_kind,
                                                  'target': 'mca.common.log:no_such_thing'})))
    # It walked sys.path for the module's file and skipped the empty entry, which is the current
    # directory - and that is how the framework is on the path for every `python -m` run from
    # the packages folder. So every mca module read as missing, and the toolbox showed the artist
    # every tool as broken.
    suite.check('and says nothing at all about a tool that is fine',
                not toolbox_runner.check_command(
                    {'kind': callable_kind, 'target': 'mca.common.log:setup_file_logging'}),
                str(toolbox_runner.check_command(
                    {'kind': callable_kind, 'target': 'mca.common.log:setup_file_logging'})))
    suite.check('a bad import inside an item\'s own code is found too',
                toolbox_runner.check_command({'kind': toolbox_model.COMMAND_PYTHON,
                                              'code': 'from mca.common.nope import thing'}) and
                not toolbox_runner.check_command({'kind': toolbox_model.COMMAND_PYTHON,
                                                  'code': 'from mca.common import log'}))
    checked = toolbox_api.check_items('Animation')
    suite.check('the whole toolbox can be checked at once',
                checked['ok'], checked['message'])

    # ---------------------------------------------------------------- #
    # taking things away
    # ---------------------------------------------------------------- #
    suite.check('an item can be deleted',
                toolbox_api.delete_item(item_id)['ok'] and
                toolbox_api.get_item(item_id)['ok'] is False)
    suite.check('a section can be taken out of one toolbox without being deleted',
                toolbox_api.remove_section_from_toolbox('Animation', section_id)['ok'])
    suite.check('and deleted outright',
                toolbox_api.delete_section(section_id)['ok'])
    suite.check('a toolbox can be deleted',
                toolbox_api.delete_toolbox('Animation')['ok'] and
                'Animation' not in [row['name'] for row in
                                    toolbox_api.list_toolboxes()['result']])
    suite.check('All Tools cannot be deleted - it is every shared section',
                toolbox_api.delete_toolbox(toolbox_model.ALL_TOOLS)['ok'] is False)

    suite.check('and the library can be re-read from disk',
                toolbox_api.reload()['ok'])

    # ---------------------------------------------------------------- #
    # the widget
    # ---------------------------------------------------------------- #
    from mca.common.pyqt import pygui

    if not pygui.AVAILABLE:
        suite.note('skipped', 'no Qt here, so the widget was not built')
        print('SKIPPED (widget only): neither PySide6 nor PySide2 is installed.')
    else:
        from mca.common.tools.toolbox import toolbox_widgets

        application = (pygui.qtwidgets.QApplication.instance() or
                       pygui.qtwidgets.QApplication([]))
        pygui.qtcore.QSettings.setDefaultFormat(pygui.qtcore.QSettings.IniFormat)
        pygui.qtcore.QCoreApplication.setOrganizationName('MechanicalArtTests')
        suite.check('Qt starts offscreen', application is not None)

        # The item types are Qt widgets, so the registry only exists where Qt does.
        types = toolbox_api.list_item_types()
        suite.check('the kinds of item a toolbox can hold are listed',
                    types['ok'] and types['result'], str(types['message']))

        toolbox_api.create_toolbox('Rigging', shared=True)
        section = toolbox_api.add_section('Rigging', 'Skinning')
        section_id = section['result']
        toolbox_api.add_item(section_id, 'Bind', code='print("bind")')

        widget = toolbox_widgets.ToolboxWidget(library=library, toolbox_name='Rigging')
        suite.check('the toolbox widget builds, with the toolbox it was asked for',
                    widget is not None)
        widget.deleteLater()

    sourcecontrol.reset()
    suite.note('toolboxes', len(toolbox_api.list_toolboxes()['result']))


if __name__ == '__main__':
    sys.exit(harness.run('toolbox', body))
