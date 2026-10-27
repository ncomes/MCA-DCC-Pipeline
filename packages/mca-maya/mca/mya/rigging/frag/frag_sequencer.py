"""
FRAGSequencer node: a scene singleton that lists the animation sequences exported from the scene.

Each ``sequence_list`` entry stores the rig, asset id, bookmark, sequence path, frame range and export options for
one sequence. The node is anchored to a ``frag_anchor`` network node so it survives its rig connections being
removed.
"""

import pymel.core as pm

from mca.common.utils import lists
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging.frag import frag_base


def get_frag_sequencer(create=True):
    """
    Find or create the FRAGSequencer node.

    :param bool create: If the new node should be created.
    :return: The scenes FRAGSequencer wrapped in FRAGSequencer class, or None if not found and create=False.
    :rtype: FRAGSequencer or None
    """

    # TODO: maybe merge multiple nodes if they exist?
    sequencer_list = pm.ls('FRAGSequencer', r=True, type=pm.nt.Network)
    if sequencer_list:
        # Wrap the existing PyMel node in FRAGSequencer class
        return FRAGSequencer(lists.get_first_in_list(sequencer_list))
    elif create:
        return FRAGSequencer.create()
    return None


class FRAGSequencer(frag_base.FRAGNode):
    """
    Network node holding the multi compound ``sequence_list`` attribute that describes every exported sequence.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create():
        """
        Creates the FRAGSequencer node. Note this will try and return an existing node rather than make a new one.
        There should only be one FRAGSequencer per scene.

        :return: A new or existing FRAGSequencer node.
        :rtype: FRAGSequencer
        """

        # Set Namespace
        pm.namespace(set=':')

        # Create the FRAG Rig Network Node
        node = get_frag_sequencer(create=False)
        if not node:
            node = frag_base.FRAGNode.create(None, FRAGSequencer.__name__, FRAGSequencer.VERSION)
            pm.addAttr(node.pynode, longName='anchor', attributeType='message')
            # Create a second network connection to keep the node live incase its other connections are removed.
            sequence_anchor = (lists.get_first_in_list(pm.ls('frag_anchor', r=True))
                               or pm.createNode(pm.nt.Network, n='frag_anchor'))
            sequence_anchor.message >> node.pynode.anchor

            pm.addAttr(node.pynode, longName='sequence_list', attributeType='compound', numberOfChildren=10,
                       multi=True)

            pm.addAttr(node.pynode, longName='rig', attributeType='message', parent='sequence_list')
            pm.addAttr(node.pynode, longName='asset_id', dataType='string', parent='sequence_list')
            pm.addAttr(node.pynode, longName='bookmark', attributeType='message', parent='sequence_list')

            pm.addAttr(node.pynode, longName='sequence_path', dataType='string', parent='sequence_list')

            pm.addAttr(node.pynode, longName='start_frame', attributeType='short', parent='sequence_list')
            pm.addAttr(node.pynode, longName='end_frame', attributeType='short', parent='sequence_list')

            pm.addAttr(node.pynode, longName='start_at_zero', attributeType='bool', parent='sequence_list')
            pm.addAttr(node.pynode, longName='root_to_origin', attributeType='bool', parent='sequence_list')
            pm.addAttr(node.pynode, longName='sequence_notes', dataType='string', parent='sequence_list')
            pm.addAttr(node.pynode, longName='ui_index', attributeType='short', parent='sequence_list')

        return node
