"""
The smallest tool in the framework, kept because it is the one to copy.

```python
from mca.common.tools.example_tool import example_ui

example_ui.ExampleUI().show()
```

It shows what a tool gets for free by inheriting :class:`common_windows.MCAMainWindow`: a
title with the framework's name and the tool's version in it, the project's stylesheet, a
remembered size and position, and the framework's own window closing the one already open
rather than leaving two. None of that is written here.

It also shows the two habits worth copying: the window builds its widgets in code, and the
work is a method that could be called without a window at all.

The version this replaces loaded ``example_tool/ui/testui.ui`` from a Qt Designer file in the
common tools folder, which is a folder an open clone does not have - so the example nobody
could run was the one meant to show how. Its button printed
``THE TEST UI IS WORKING!!!`` to standard output, which inside Maya goes to the script editor
if it goes anywhere, so it also demonstrated the one thing no tool should do: use ``print``
where the framework has a logger.
"""

# python imports

# MCA python imports
from mca.common import log
from mca.common.pyqt import common_windows
from mca.common.pyqt.pygui import qtwidgets


logger = log.MCA_LOGGER


class ExampleUI(common_windows.MCAMainWindow):
    """
    A window with a field, a button and somewhere to put the answer.
    """

    VERSION = '2.0.0'

    def __init__(self, style=None, parent=None):
        """
        :param str style: A stylesheet name, or None for the project's.
        :param parent: The parent window, or None to let the framework work it out.
        """

        super(ExampleUI, self).__init__('Example', version=ExampleUI.VERSION, style=style,
                                        parent=parent)

        self.setMinimumSize(320, 140)

        self.name_field = qtwidgets.QLineEdit(parent=self)
        self.name_field.setPlaceholderText('a name')

        self.run_button = qtwidgets.QPushButton('Say hello', parent=self)
        self.run_button.clicked.connect(self.on_run)

        self.answer_label = qtwidgets.QLabel('', parent=self)

        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(8)
        self.main_layout.addWidget(self.name_field)
        self.main_layout.addWidget(self.run_button)
        self.main_layout.addWidget(self.answer_label)
        self.main_layout.addStretch()

    def on_run(self):
        """
        What the button does. A window's job is to collect what the artist typed and hand it
        to something that does not need a window.
        """

        self.answer_label.setText(greeting(self.name_field.text()))

    @property
    def answer(self):
        """
        :return: What the window is showing, which is how a test asks.
        :rtype: str
        """

        return self.answer_label.text()


def greeting(name):
    """
    The work, with no Qt anywhere near it - so it can be called from a farm job, an MCP
    server or a suite.

    :param str name: Who to greet.
    :return: The greeting.
    :rtype: str
    """

    name = (name or '').strip()
    if not name:
        logger.debug('Nobody was named, so the example greeted the room.')
        return 'Hello, whoever you are.'

    return 'Hello, {0}.'.format(name)
