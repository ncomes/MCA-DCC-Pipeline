"""
Reading and setting drop-down lists.
"""

# mca imports
from mca.common import log
from mca.common.pyqt import pygui


logger = log.MCA_LOGGER


def get_all_combobox_items(qcombobox):
    """
    :param qcombobox: A QComboBox.
    :return: Everything in it, in order.
    :rtype: list(str)
    """

    # The version this replaces had a special case for exactly one item that did the same
    # thing as the line below it.
    return [qcombobox.itemText(index) for index in range(qcombobox.count())]


def set_combobox_item(qcombobox, value):
    """
    Select an item by its text.

    :param qcombobox: A QComboBox.
    :param str value: The text to select.
    :return: Whether it was found and selected.
    :rtype: bool
    """

    if not value:
        logger.warning('No value was given to look for in that drop-down.')
        return False

    items = get_all_combobox_items(qcombobox)
    if not items:
        logger.warning('That drop-down is empty.')
        return False
    if value not in items:
        logger.warning('%r is not in that drop-down. It has: %s.', value, ', '.join(items))
        return False

    qcombobox.setCurrentIndex(items.index(value))
    return True


def set_combobox_to_index_matching_string(combo_box, string_to_match, qmatch_flag=None):
    """
    Select the first item matching some text, ignoring case by default.

    :param combo_box: A QComboBox.
    :param str string_to_match: What to look for.
    :param qmatch_flag: A Qt match flag. None ignores case.
    :return: Whether anything matched.
    :rtype: bool
    """

    if qmatch_flag is None:
        qmatch_flag = pygui.qtcore.Qt.MatchFixedString
    index = combo_box.findText(string_to_match, qmatch_flag)
    if index < 0:
        logger.debug('Nothing in that drop-down matches %r.', string_to_match)
        return False
    combo_box.setCurrentIndex(index)
    return True
