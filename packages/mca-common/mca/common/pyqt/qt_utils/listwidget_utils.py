"""
Reading and selecting in list widgets.
"""

# mca imports
from mca.common import log


logger = log.MCA_LOGGER


def get_qlist_widget_items(qlist_widget):
    """
    :param qlist_widget: A QListWidget.
    :return: What every row says, in order.
    :rtype: list(str)
    """

    return [qlist_widget.item(index).text() for index in range(qlist_widget.count())]


def select_position_qlist_widget_item(qlist_widget, index=0):
    """
    Select a row by its number.

    :param qlist_widget: A QListWidget.
    :param int index: Which row.
    :return: Whether there was such a row.
    :rtype: bool
    """

    if index < 0 or index >= qlist_widget.count():
        return False
    qlist_widget.setCurrentRow(index)
    return True


def select_qlist_widget_item(qlist_widget, item):
    """
    Select a row by what it says.

    :param qlist_widget: A QListWidget.
    :param str item: The text to look for.
    :return: Whether it was found.
    :rtype: bool
    """

    wanted = str(item)
    for index in range(qlist_widget.count()):
        if qlist_widget.item(index).text() == wanted:
            qlist_widget.setCurrentRow(index)
            return True
    return False


def get_selected_items(qlist_widget):
    """
    :param qlist_widget: A QListWidget.
    :return: What the selected rows say.
    :rtype: list(str)
    """

    return [one.text() for one in qlist_widget.selectedItems()]
