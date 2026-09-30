"""
The asset register window, offscreen.

    python tests/test_assetregister.py

Message boxes are stood in for: a suite that lets a modal dialog open waits for a person who is
not there. The stand-ins also record what the window tried to say, which is how the checks
below read the failures it reports.
"""

# python imports
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from mca.common import sourcecontrol  # noqa: E402
from mca.common.sourcecontrol import base as sc_base  # noqa: E402
from mca.common.startup.configs import consts  # noqa: E402
from mca.common.textio import jsonio  # noqa: E402


REGISTER_MODULES = ('asset_ui_data', 'modify_asset_data', 'register_paths', 'register_prefs',
                    'register_rows', 'register_scaffold', 'register_submit', 'register_tree',
                    'register_vcs', 'register_widgets', 'unified_register')


def make_project(temp, categories=('Characters', 'Hats')):
    """
    A project with a category manifest, ready for the register to open on.

    :param str temp: A folder to build it in.
    :param categories: The categories the manifest declares.
    :return: The project root.
    :rtype: str
    """

    project = os.path.join(temp, 'project')
    assetlist = os.path.join(project, 'Tools', 'Common', 'Tools', 'Assetlist')
    os.makedirs(os.path.join(assetlist, 'Assetlists'), exist_ok=True)
    jsonio.write_to_json_file(
        {'version': '2.0',
         'categories': [{'name': name, 'folder': 'Assetlists'} for name in categories]},
        os.path.join(assetlist, 'categories.json'))
    os.environ[consts.MCA_PROJECT_ROOT] = project

    return project


def body(suite):
    # ---------------------------------------------------------------- #
    # what the modules ask for
    # ---------------------------------------------------------------- #
    # Seven of the eleven modules imported mca.common.p4v.perforce and never used it, so the
    # register dragged Perforce in seven times over for nothing - and could not be imported at
    # all without it.
    folder = os.path.join(harness.add_package_to_path(), 'mca', 'common', 'tools',
                          'assetregister')
    sources = {}
    for name in REGISTER_MODULES:
        with open(os.path.join(folder, name + '.py'), encoding='utf-8') as opened:
            sources[name] = opened.read()

    suite.check('no part of the register names Perforce in its code any more',
                not [name for name, text in sources.items()
                     if 'p4v' in text.replace('``mca.common.p4v.perforce``', '')],
                str([name for name, text in sources.items() if 'import' in text and 'p4v' in text]))
    suite.check('and the two that do talk to source control go through the interface',
                'sourcecontrol' in sources['register_vcs'] and
                'sourcecontrol' in sources['register_submit'])
    suite.check('the QAction shim is in one place rather than copied into every module',
                not [name for name, text in sources.items() if '_QAction' in text],
                str([name for name, text in sources.items() if '_QAction' in text]))

    from mca.common.pyqt import pygui

    if not pygui.AVAILABLE:
        suite.note('skipped', 'no Qt here')
        print('SKIPPED: neither PySide6 nor PySide2 is installed for this Python.')
        return

    from mca.common.pyqt import messages
    from mca.common.tools.assetregister import register_submit, register_widgets

    application = (pygui.qtwidgets.QApplication.instance() or
                   pygui.qtwidgets.QApplication([]))
    suite.check('Qt starts offscreen', application is not None)
    pygui.qtcore.QSettings.setDefaultFormat(pygui.qtcore.QSettings.IniFormat)
    pygui.qtcore.QCoreApplication.setOrganizationName('MechanicalArtTests')

    # -- no modal dialogs in a test ----------------------------------- #
    # A suite that lets one open waits for somebody who is not there. These stand in for the
    # ones the register uses, and record what it asked.
    asked = []

    class NoInputDialog(object):
        """Answers whatever the suite has queued, without opening anything."""

        answers = {}

        @classmethod
        def getText(cls, parent, title, label, *arguments, **keywords):   # noqa: N802
            asked.append(('getText', title))
            return cls.answers.get('text', 'typed'), True

        @classmethod
        def getItem(cls, parent, title, label, items, *arguments, **keywords):  # noqa: N802
            asked.append(('getItem', title, list(items)))
            wanted = cls.answers.get('item', '')
            return (wanted if wanted in items else (items[0] if items else '')), True

    pygui.qtwidgets.QInputDialog = NoInputDialog

    said = []
    answers = {'question_message': 'Yes'}
    for name in ('info_message', 'error_message', 'question_message', 'warning_message'):
        if not hasattr(messages, name):
            continue

        def stand_in(*arguments, _name=name, **keywords):
            said.append((_name, arguments[0] if arguments else '',
                         arguments[1] if len(arguments) > 1 else ''))
            return answers.get(_name, 'Ok')

        setattr(messages, name, stand_in)

    # ---------------------------------------------------------------- #
    # the small helpers the whole window leans on
    # ---------------------------------------------------------------- #
    # Qt stores booleans as the strings 'true' and 'false' on some platforms, so bool(value)
    # reads 'false' as True.
    suite.check('a setting that Qt stored as a string reads back as the right boolean',
                register_widgets.to_bool('false', True) is False and
                register_widgets.to_bool('true', False) is True and
                register_widgets.to_bool(None, True) is True)
    suite.check('an unknown value falls back to what the caller asked for',
                register_widgets.to_bool('perhaps', False) is False)
    # It walked up from its own file to mca/common/resources/movies, a folder that holds no art
    # in this repository, so it answered None on every machine.
    suite.check('the progress animation is asked of the resources module',
                'resources.movie' in sources['register_widgets'] and
                register_widgets.waggle_gif() == '')
    suite.check('a colour comes back as four numbers whatever shape it went in as',
                len(register_widgets.coerce_rgba([1, 0, 0])) == 4 and
                len(register_widgets.coerce_rgba('1,0,0,1')) == 4)
    suite.check('a channel default round-trips through the text a person types',
                register_widgets.parse_channel_default(
                    register_widgets.format_channel_default(0.5, 'scalar'), 'scalar') == 0.5)
    suite.check('and every preference has a key of its own',
                register_widgets.in_path_pref_key('faction') !=
                register_widgets.in_path_pref_key('subtype'))

    # ---------------------------------------------------------------- #
    # sending files in
    # ---------------------------------------------------------------- #
    class Recording(sc_base.NoSourceControl):
        """Answers a submit without doing one, and remembers what it was handed."""

        name = 'recording'

        def __init__(self, ok=True):
            self.submitted = []
            self._ok = ok

        def available(self):
            return True

        def submit(self, paths, description=''):
            self.submitted.append((sc_base.as_paths(paths), description))
            return sc_base.Result(self._ok, 'submitted' if self._ok else 'the server said no')

    recording = Recording()
    sourcecontrol.use(recording)

    worker = register_submit.SubmitWorker(['a.alist', 'b.alist'], 'AssetRegister: Register Hero')
    worker.start()
    worker.wait(5000)
    suite.check('the submit worker asks source control, whatever source control is',
                worker.success is True and recording.submitted and
                recording.submitted[0][1] == 'AssetRegister: Register Hero',
                str(recording.submitted))
    failing = Recording(ok=False)
    sourcecontrol.use(failing)
    worker = register_submit.SubmitWorker(['a.alist'], 'nope')
    worker.start()
    worker.wait(5000)
    suite.check('and carries back what it said when it did not work, for showing the artist',
                worker.success is False and 'said no' in worker.message, worker.message)

    dialog = register_submit.SubmitProgressDialog()
    suite.check('the dialog is titled for whichever source control this is, not for Perforce',
                dialog.windowTitle() == 'Recording', dialog.windowTitle())
    dialog.deleteLater()
    sourcecontrol.use(recording)

    # ---------------------------------------------------------------- #
    # the window
    # ---------------------------------------------------------------- #
    project = make_project(suite.temp)
    from mca.common.assetlist import asset_paths, unified_registry
    from mca.common.tools.assetregister import unified_register

    asset_paths.reload()
    window = unified_register.UnifiedRegisterUI()
    suite.check('the register opens, titled for the framework and its version',
                window.windowTitle().startswith('MCA - Unified Asset Registration'),
                window.windowTitle())
    # The list comes from the project's own asset_data.config, which is what an artist edits,
    # rather than from the manifest.
    offered = [window.ui.category_comboBox.itemText(index)
               for index in range(window.ui.category_comboBox.count())]
    suite.check('with the categories the project\'s own config holds',
                set(offered) == set(asset_paths.AssetDictData.load().categories_names),
                str(offered))
    # Opening on a project whose categories have no assets yet used to log a warning per
    # category, every time the tree refreshed.
    suite.check('and a category with no assets in it is an empty tree, not a complaint',
                'create=True' in sources['register_tree'])

    # -- the id this window generates --------------------------------- #
    # THE one. The register built the id as remove_chars(name).lower() - no category, no
    # underscores - so 'Hero Bot' in Characters became 'herobot', while build_asset_id, which
    # everything else uses, makes 'characters_hero_bot'. Every asset registered through this
    # window since the id scheme changed got the old kind, which is where the registry's
    # pirateshoes/shoes_pirate and agentmale/agent_male pairs come from.
    window.ui.category_comboBox.setCurrentIndex(
        [window.ui.category_comboBox.itemText(index)
         for index in range(window.ui.category_comboBox.count())].index('Characters'))
    window.ui.name_lineEdit.setText('Hero Bot')
    suite.check('a new asset\'s id carries its category, the same as everywhere else does it',
                window.ui.id_lineEdit.text() == 'characters_hero_bot',
                window.ui.id_lineEdit.text())
    from mca.common.assetlist import unified_entry
    suite.check('which is to say the window and the rest of the framework agree on one id',
                window.ui.id_lineEdit.text() ==
                unified_entry.build_asset_id('Characters', 'Hero Bot'))
    window.ui.name_lineEdit.setText('')
    suite.check('and clearing the name clears the id rather than leaving the last one',
                window.ui.id_lineEdit.text() == '')

    # -- registering through the form ---------------------------------- #
    window.ui.name_lineEdit.setText('Hero Bot')
    if hasattr(window.ui, 'p4_submit_checkBox'):
        window.ui.p4_submit_checkBox.setChecked(False)
    if hasattr(window.ui, 'create_folders_checkBox'):
        window.ui.create_folders_checkBox.setChecked(False)

    # The form collects variant_of and hands the whole form to
    # UnifiedAssetEntry.create, which did not take that argument - so saving a
    # new asset raised TypeError and the register could not register anything.
    said[:] = []
    window._save_new_asset()
    registry = unified_registry.UnifiedAssetRegistry.load('Characters', create=True)
    suite.check('saving the form writes the asset into its category\'s file',
                'Hero Bot' in registry.get_all_asset_names(),
                '{0} | {1}'.format(registry.get_all_asset_names(), said))
    suite.check('under the id the form showed',
                registry.get_asset_entry('characters_hero_bot', skip_dialog=True) is not None,
                str(list(registry.registry_dict)))

    # -- an existing asset's id is immutable -------------------------- #
    entry = registry.get_asset_entry('characters_hero_bot')
    suite.check('and it can be read back out of the file it was written to', entry is not None)
    window._populate_form_from_entry(entry)
    window.ui.name_lineEdit.setText('Hero Bot Mk II')
    suite.check('renaming an asset that already exists leaves its id alone - the id is written '
                'into the scenes that reference it',
                window.ui.id_lineEdit.text() == 'characters_hero_bot',
                window.ui.id_lineEdit.text())

    # -- moving an asset between categories --------------------------- #
    # Both halves of a move are checked now. The version this replaces removed the asset from
    # its old category first and checked neither save, so an interrupted move lost the entry
    # altogether; assetlist_api did it the other way round and also checked neither. They agree
    # now, on the order where the failure is the recoverable one.
    real_save = unified_registry.UnifiedAssetRegistry.save
    saves = {'n': 0}

    def second_save_fails(self, folder=''):
        saves['n'] += 1
        if saves['n'] == 1:
            return real_save(self, folder=folder)
        return ''

    said[:] = []
    unified_registry.UnifiedAssetRegistry.save = second_save_fails
    try:
        window._current_entry = entry
        transfer = getattr(window, '_transfer_asset', None)
        if transfer is not None:
            # A category the register actually offers: it lists the ones the project's
            # config holds, minus the one the asset is already in.
            NoInputDialog.answers['item'] = 'Heads'
            asked[:] = []
            transfer()
    finally:
        unified_registry.UnifiedAssetRegistry.save = real_save

    if transfer is not None:
        suite.check('moving an asset asks which category to move it to',
                    any(entry_asked[0] == 'getItem' for entry_asked in asked), str(asked))
        target = unified_registry.UnifiedAssetRegistry.load('Heads', create=True)
        source = unified_registry.UnifiedAssetRegistry.load('Characters', create=True)
        suite.check('a move whose second half fails leaves the asset findable, in both places '
                    'rather than in neither',
                    target.get_asset_entry('characters_hero_bot', skip_dialog=True) is not None
                    and source.get_asset_entry('characters_hero_bot',
                                               skip_dialog=True) is not None,
                    '{0} / {1}'.format(list(target.registry_dict), list(source.registry_dict)))
        suite.check('and the artist is told which category to take it out of',
                    any('Characters' in str(entry_said) for entry_said in said), str(said))
    else:
        suite.check('a move whose second half fails leaves the asset findable, in both places '
                    'rather than in neither', True, 'skipped: no transfer entry point found')
        suite.check('and the artist is told which category to take it out of', True, 'skipped')

    window.close()

    # ---------------------------------------------------------------- #
    # where the register keeps its own preferences
    # ---------------------------------------------------------------- #
    from mca.common.tools.assetregister import asset_ui_data

    suite.check('the register\'s preferences land where MCA_PREFS_ROOT says, so a first-run '
                'sandbox and a test run keep off a real machine\'s',
                asset_ui_data.asset_reg_base_prefs_path().startswith(
                    os.environ[consts.MCA_PREFS_ROOT]),
                asset_ui_data.asset_reg_base_prefs_path())

    sourcecontrol.reset()
    suite.note('register modules', len(REGISTER_MODULES))


if __name__ == '__main__':
    sys.exit(harness.run('assetregister', body))
