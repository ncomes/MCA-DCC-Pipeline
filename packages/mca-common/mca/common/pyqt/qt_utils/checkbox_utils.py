"""
Reading check boxes.
"""

# mca imports
from mca.common.pyqt import pygui


def get_checkbox_text(checkbox_list, only_true=True):
    """
    :param checkbox_list: A check box, or several. Anything that is not one is skipped.
    :param bool only_true: Only the ticked ones.
    :return: What each says.
    :rtype: list(str)
    """

    if not isinstance(checkbox_list, (tuple, list)):
        checkbox_list = [checkbox_list]

    found = []
    for checkbox in checkbox_list:
        if not isinstance(checkbox, pygui.qtwidgets.QCheckBox):
            continue
        if only_true and not checkbox.isChecked():
            continue
        found.append(checkbox.text())
    return found


def get_checked(checkbox_list):
    """
    :param checkbox_list: A check box, or several.
    :return: The ticked ones themselves, for a caller that wants the widgets.
    :rtype: list
    """

    if not isinstance(checkbox_list, (tuple, list)):
        checkbox_list = [checkbox_list]
    return [one for one in checkbox_list
            if isinstance(one, pygui.qtwidgets.QCheckBox) and one.isChecked()]
