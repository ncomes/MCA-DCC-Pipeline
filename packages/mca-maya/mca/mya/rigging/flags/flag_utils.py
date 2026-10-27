"""
Operations on the flags of FRAG rigs: zeroing keyable attributes, toggling the flag display layers, selecting all
flags and cutting flag animation.
"""

import pymel.core as pm

from mca.common import log
from mca.mya.pyqt import dialogs
from mca.mya.rigging import frag
from mca.mya.utils import attr_utils, display_layers

logger = log.MCA_LOGGER


def zero_flags(node_list):
    """
    Sets all the flag attributes that are keyable back to their default values.

    :param list[pm.nt.PyNode] node_list: List of nodes connected to a rig
    """

    if not node_list:
        node_list = frag.get_frag_rigs()

    if not node_list:
        dialogs.info_prompt(title='Nothing Selected', text='Please select a FRAG rig.')
        return

    if not isinstance(node_list, list):
        node_list = [node_list]

    frag_rigs = []

    if all(isinstance(x, frag.FRAGRig) for x in node_list):
        frag_rigs = list(node_list)
        logger.info('All nodes were FRAGRigs.')
    else:
        for node in node_list:
            frag_rig = frag.get_frag_rig(node)
            if frag_rig:
                frag_rigs.append(frag_rig)

    frag_rigs = list(set(frag_rigs))
    for frag_rig in frag_rigs:
        for flag_node in frag_rig.get_flags():
            attr_utils.reset_attrs(flag_node)


def flags_visibility(node_list, toggle=False, on=False):
    """
    Toggles the visibility layer for the flags.

    :param list[pm.nt.PyNode] node_list: List of nodes connected to a rig
    :param bool toggle: uses the function as a toggle.  If toggle is true, the 'on' flag will not be used.
    :param bool on: If True, the flags layer will be visible.  If False, the flags layer will not be visible.
    """

    if not node_list:
        logger.warning('Please select a flag.')
        return

    if not isinstance(node_list, list):
        node_list = [node_list]

    frag_rigs = []

    if all(isinstance(x, frag.FRAGRig) for x in node_list):
        frag_rigs = list(node_list)
        logger.info('All nodes were FRAGRigs.')
    else:
        for node in node_list:
            frag_rig = frag.get_frag_rig(node)
            if frag_rig:
                frag_rigs.append(frag_rig)

    frag_rigs = list(set(frag_rigs))
    for frag_rig in frag_rigs:
        flags = frag_rig.get_flags()
        display_lyrs = display_layers.get_display_layers(flags)
        if not display_lyrs:
            logger.warning(f'{frag_rig.pynode}: Rig is not under a layer.')
            continue
        if toggle:
            value = display_lyrs[0].v.get()
            for display_lyr in display_lyrs:
                display_lyr.v.set(not value)
            continue

        for display_lyr in display_lyrs:
            display_lyr.v.set(on)


def select_all_flags(node_list):
    """
    Selects all the flag for the selected rigs.

    :param list[pm.nt.PyNode] node_list: List of nodes connected to a rig
    """

    if not node_list:
        logger.warning('Please select a flag.')
        return

    if not isinstance(node_list, list):
        node_list = [node_list]

    frag_rigs = []

    for node in node_list:
        frag_rig = frag.get_frag_rig(node)
        if frag_rig:
            frag_rigs.append(frag_rig)

    frag_rigs = list(set(frag_rigs))
    for frag_rig in frag_rigs:
        pm.select(frag_rig.get_flags())


def cut_all_flag_animations(rig_node):
    """
    Cut animation from all the flags on a rig.

    :param pm.nt.DagNode rig_node: a node on the rig.
    :return: Returns if True, the keys were cut successfully
    :rtype: bool
    """

    frag_rig = frag.get_frag_rig(rig_node)
    if not frag_rig:
        return False
    flags = frag_rig.get_flags()
    for flag_node in flags:
        pm.cutKey(flag_node)
    zero_flags(flags)
    return True
