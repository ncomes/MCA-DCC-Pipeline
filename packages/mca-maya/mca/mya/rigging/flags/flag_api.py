"""
Menu facing flag commands: resolves which FRAG rigs the user means (single rig in scene or selected rigs) and
applies the flag_utils operations (zero, select, show / hide, remove animation) to them.
"""

import pymel.core as pm

from mca.common import log
from mca.mya.pyqt import dialogs
from mca.mya.rigging import frag
from mca.mya.rigging.flags import flag_utils

logger = log.MCA_LOGGER


def check_for_rigs():
    """
    Finds the FRAG rig(s) a flag command should operate on and prompts the user when none can be resolved.

    NOTE: the return type is inconsistent and callers rely on it: with exactly one FRAG rig in the scene that rig is
    returned on its own (not in a list); with more than one rig, a list of the FRAG rigs found from the current
    selection is returned (possibly empty); with no rigs in the scene an empty list is returned after an info prompt.

    :return: Returns the single FRAG rig in the scene, or a list of the selected FRAG rigs.
    :rtype: FRAGRig or list[FRAGRig]
    """

    # Find every FRAG rig in the scene.
    frag_rigs = frag.get_frag_rigs()
    if not frag_rigs:
        dialogs.info_prompt(title='No Rigs', text='No Rigs Found in the scene\n'
                                                  'Make sure the rig is a FRAG Rig.')
        return []

    # Check to see if there is only one rig in the scene.
    if len(frag_rigs) == 1:
        return frag_rigs[0]

    # When there is more than one rig, get the rigs from the selection.
    selection = pm.selected()
    frag_rigs = []

    for node in selection:
        frag_rig = frag.get_frag_rig(node)
        if frag_rig:
            frag_rigs.append(frag_rig)
    return frag_rigs


def zero_flags_cmd():
    """
    Sets all the flag attributes that are keyable back to their default values.
    """

    frag_rigs = check_for_rigs()
    if frag_rigs:
        flag_utils.zero_flags(frag_rigs)


def select_all_flags_cmd():
    """
    Selects all the flag for the selected rigs.
    """

    frag_rigs = check_for_rigs()
    if frag_rigs:
        flag_utils.select_all_flags(frag_rigs)


def show_flags_cmd():
    """
    Shows all the flag for the selected rigs.
    """

    frag_rigs = check_for_rigs()
    if frag_rigs:
        flag_utils.flags_visibility(node_list=frag_rigs, toggle=False, on=True)


def hide_flags_cmd():
    """
    Hides all the flag for the selected rigs.
    """

    frag_rigs = check_for_rigs()
    if frag_rigs:
        flag_utils.flags_visibility(node_list=frag_rigs, toggle=False, on=False)


def remove_animation():
    """
    Removes all the keys from all the flags for the selected rigs.
    """

    frag_rigs = check_for_rigs()
    if frag_rigs:
        for rig in frag_rigs:
            flag_utils.cut_all_flag_animations(rig_node=rig)
