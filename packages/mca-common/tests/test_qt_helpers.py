"""
The small Qt helpers: menus, widgets, gifs, and the syntax highlighter.

    python tests/test_qt_helpers.py
"""

# python imports
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import harness  # noqa: E402

harness.add_package_to_path()

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def body(suite):
    from mca.common.pyqt import pygui

    # The syntax highlighter had `Sequence[int] | str` in an annotation, which is evaluated
    # when the function is defined and is Python 3.10 and later - so importing it in Maya
    # 2022, which is 3.7, raised TypeError before anything ran. It is checked here first
    # because it needs no Qt to go wrong.
    import ast

    source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'mca', 'common', 'pyqt', 'syntax_highlighter.py')
    with open(source, 'r', encoding='utf-8') as opened:
        tree = ast.parse(opened.read())
    futures = [name.name for node in tree.body
               if isinstance(node, ast.ImportFrom) and node.module == '__future__'
               for name in node.names]
    suite.check('the syntax highlighter puts its annotations off until something asks for '
                'them, so it imports in Maya 2022 as well as 2026',
                'annotations' in futures, str(futures))

    if not pygui.AVAILABLE:
        suite.note('skipped', 'no Qt here')
        print('SKIPPED: neither PySide6 nor PySide2 is installed for this Python.')
        return

    from mca.common.pyqt import movies, syntax_highlighter
    from mca.common.pyqt.qt_utils import (checkbox_utils, combobox_utils, general_utils,
                                          listwidget_utils, qt_menus, uiloaders)

    application = pygui.qtwidgets.QApplication.instance() or pygui.qtwidgets.QApplication([])
    suite.check('Qt starts offscreen', application is not None)

    # ---------------------------------------------------------------- #
    # Menus
    # ---------------------------------------------------------------- #
    window = pygui.qtwidgets.QMainWindow()
    window.setMenuBar(pygui.qtwidgets.QMenuBar(window))

    menu = qt_menus.MainWindowsMenus.create('MCA', window)
    suite.check('the framework\'s menu is added to a window that has a menu bar',
                menu is not None and menu.menu.objectName() == 'MCA')

    again = qt_menus.MainWindowsMenus.create('MCA', window)
    suite.check('and asking again finds the one that is there rather than adding a second',
                again.menu is menu.menu)

    bare = pygui.qtwidgets.QWidget()
    suite.check('a window with no menu bar answers None rather than raising - it used to '
                'call .children() on it', qt_menus.MainWindowsMenus.create('MCA', bare)
                is None)

    pressed = []
    menu.add_action('First', lambda: pressed.append('first'))
    menu.add_action('Second', lambda: pressed.append('second'))
    menu.add_separator()
    menu.add_action('Third', lambda: pressed.append('third'))
    suite.check('actions are added', len(menu.menu.actions()) == 4,
                str([one.text() for one in menu.menu.actions()]))

    # The one that could never work: the return False was inside the loop, so only the
    # first action could ever be removed.
    suite.check('an action that is not the first one can be removed',
                menu.remove_action('Third'))
    suite.check('and it really is gone',
                'Third' not in [one.text() for one in menu.menu.actions()],
                str([one.text() for one in menu.menu.actions()]))
    suite.check('the first one can be removed too', menu.remove_action('First'))
    suite.check('and one that is not there answers False rather than stopping at the first',
                not menu.remove_action('Never Existed'))

    for action in menu.menu.actions():
        if action.text() == 'Second':
            action.trigger()
    suite.check('an action still does what it was given', pressed == ['second'], str(pressed))

    suite.check('a menu can be taken back out', menu.remove_menu())

    # ---------------------------------------------------------------- #
    # Widgets
    # ---------------------------------------------------------------- #
    boxes = [pygui.qtwidgets.QCheckBox('Rigs'), pygui.qtwidgets.QCheckBox('Anims'),
             pygui.qtwidgets.QLabel('not a checkbox')]
    boxes[0].setChecked(True)
    suite.check('only the ticked boxes are read, and anything that is not one is skipped',
                checkbox_utils.get_checkbox_text(boxes) == ['Rigs'],
                str(checkbox_utils.get_checkbox_text(boxes)))
    suite.check('and all of them can be asked for',
                checkbox_utils.get_checkbox_text(boxes, only_true=False) ==
                ['Rigs', 'Anims'])

    combo = pygui.qtwidgets.QComboBox()
    combo.addItems(['maya', 'mobu', 'unreal'])
    suite.check('a drop-down reads back what is in it',
                combobox_utils.get_all_combobox_items(combo) == ['maya', 'mobu', 'unreal'])
    suite.check('an item can be selected by name, and says so',
                combobox_utils.set_combobox_item(combo, 'unreal') and
                combo.currentText() == 'unreal')
    suite.check('one that is not there answers False rather than selecting something else',
                not combobox_utils.set_combobox_item(combo, 'houdini') and
                combo.currentText() == 'unreal')
    suite.check('and a one-item list reads the same way as any other',
                combobox_utils.get_all_combobox_items(
                    (lambda box: (box.addItem('only'), box)[1])(
                        pygui.qtwidgets.QComboBox())) == ['only'])

    listing = pygui.qtwidgets.QListWidget()
    listing.addItems(['hero', 'villain', 'extra'])
    suite.check('a list widget reads back',
                listwidget_utils.get_qlist_widget_items(listing) ==
                ['hero', 'villain', 'extra'])
    suite.check('and a row can be selected by what it says',
                listwidget_utils.select_qlist_widget_item(listing, 'villain') and
                listing.currentRow() == 1)
    suite.check('a row that is not there answers False',
                not listwidget_utils.select_qlist_widget_item(listing, 'nobody'))
    suite.check('and a row number out of range does too, rather than raising',
                not listwidget_utils.select_position_qlist_widget_item(listing, 99))

    holder = pygui.qtwidgets.QWidget()
    outer = pygui.qtwidgets.QVBoxLayout(holder)
    inner = pygui.qtwidgets.QHBoxLayout()
    inner.addWidget(pygui.qtwidgets.QPushButton('one'))
    inner.addWidget(pygui.qtwidgets.QPushButton('two'))
    outer.addLayout(inner)
    suite.check('a layout can be emptied and taken out of the one holding it',
                general_utils.delete_layout_and_children(outer, inner))
    suite.check('and emptying nothing is not an error',
                general_utils.delete_items_of_layout(None) == 0)
    suite.check('what widgets say can be read, skipping anything with nothing to say',
                general_utils.get_qwidget_text(
                    [pygui.qtwidgets.QPushButton('go'), pygui.qtwidgets.QWidget()]) == ['go'])

    # ---------------------------------------------------------------- #
    # Loading a .ui file
    # ---------------------------------------------------------------- #
    suite.check('a .ui file that is not there answers None rather than handing back a '
                'widget made from a file that never opened',
                uiloaders.ui_importer(os.path.join(suite.temp, 'nothing.ui')) is None)

    # ---------------------------------------------------------------- #
    # Gifs
    # ---------------------------------------------------------------- #
    gif = os.path.join(suite.temp, 'spinner.gif')
    with open(gif, 'wb') as opened:
        opened.write(b'GIF89a\x01\x00\x01\x00\x00\xff\x00,\x00\x00\x00\x00'
                     b'\x01\x00\x01\x00\x00\x02\x00;')
    label = movies.MovieLabel(gif)
    suite.check('a gif label holds a movie and keeps hold of it',
                label.movie is not None and label.movie is label.movie)
    button = movies.GifHoverToolButton(gif)
    suite.check('and a hover button starts still', button.movie.state() !=
                pygui.qtgui.QMovie.Running)

    # ---------------------------------------------------------------- #
    # The highlighter
    # ---------------------------------------------------------------- #
    editor = pygui.qtwidgets.QPlainTextEdit()
    highlighter = syntax_highlighter.PythonHighlighter(editor.document())
    editor.setPlainText('def thing():\n    return "text"  # a comment\n')
    application.processEvents()
    suite.check('the syntax highlighter attaches to a document and runs over it',
                highlighter.document() is editor.document())

    for widget in (window, bare, holder, listing, combo, editor, label, button):
        widget.deleteLater()
    application.processEvents()

    suite.note('checks_written', len(suite.checks))


if __name__ == '__main__':
    sys.exit(harness.run('qt_helpers', body))
