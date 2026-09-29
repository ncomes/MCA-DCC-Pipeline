"""
Taking widgets and layouts apart, and reading what is in them.
"""

# mca imports
from mca.common.pyqt import pygui


def delete_items_of_layout(layout):
    """
    Remove and destroy everything in a layout, however deeply nested.

    :param layout: A QLayout.
    :return: How many widgets were removed.
    :rtype: int
    """

    removed = 0
    if layout is None:
        return removed

    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
            removed += 1
        else:
            removed += delete_items_of_layout(item.layout())
    return removed


def delete_layout_and_children(parent_layout, layout_to_remove):
    """
    Empty a layout and take it out of the one holding it.

    :param parent_layout: The layout it lives in.
    :param layout_to_remove: The layout to remove.
    :return: Whether it was found and removed.
    :rtype: bool
    """

    delete_items_of_layout(layout_to_remove)
    if parent_layout is None:
        return False

    for index in range(parent_layout.count()):
        item = parent_layout.itemAt(index)
        if item is not None and item.layout() is layout_to_remove:
            parent_layout.removeItem(item)
            return True
    return False


def get_qwidget_text(qwidget_list):
    """
    :param qwidget_list: A widget, or several.
    :return: What each of them says. A widget with no text is skipped rather than raising.
    :rtype: list(str)
    """

    if not isinstance(qwidget_list, (tuple, list)):
        qwidget_list = [qwidget_list]

    found = []
    for widget in qwidget_list:
        reader = getattr(widget, 'text', None)
        if callable(reader):
            found.append(reader())
    return found
