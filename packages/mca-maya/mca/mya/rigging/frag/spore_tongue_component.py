"""
FRAG component that extends the spline IK component with a travelling "spore" bulge along the chain.

Built on SplineIKComponent, it adds ``spore`` and ``spore_scale`` attributes to the end flag (mirrored onto the mid
helper joint for animation recovery) and a node network per inner leaf joint that scales the joint with a parabolic
bulge as the spore value travels from the base to the tip. When the base component can retract, the bulge is
multiplied into the existing retract scale instead of replacing it.
"""

import pymel.core as pm

from mca.common.utils import lists
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging.frag import frag_base, spline_ik_component
from mca.mya.utils import naming


class SporeTongueComponent(spline_ik_component.SplineIKComponent):
    """
    Spline IK component with a travelling bulge.

    Retypes the SplineIKComponent network node to SporeTongueComponent and adds the ``remapNodes``, ``multNodes``
    and ``addNodes`` links for the spore network.
    """

    VERSION = 2

    # Attributes baked onto the mid helper joint that attach_to_skeleton reconnects to the end flag.
    ATTACH_ATTRS = ['retract', 'spore', 'spore_scale']

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent,
               start_joint,
               end_joint,
               end_helper_joint,
               mid_helper_joint,
               leaf_joint_list,
               side,
               region,
               start_helper_joint=None,
               mid_flag=True,
               can_retract=True,
               **kwargs):
        """
        This wraps the complex spline IK component and adds the projectile feature.

        :param FRAGNode frag_parent: FRAG Rig FRAGNode.
        :param Joint start_joint: Start joint of the chain.
        :param Joint end_joint: End joint of the chain.
        :param Joint end_helper_joint: A joint separated, but co-located with the end joint of the primary chain
        :param Joint mid_helper_joint: A joint located between the start/end joint, but not part of the primary chain
        :param list[Joint] leaf_joint_list: One leaf joint per chain joint, in order. They receive the scale so the
            primary skeleton stays scale free.
        :param str side: The side in which the component is on the body.
        :param str region: The name of the region.  EX: "Arm"
        :param Joint start_helper_joint: A joint separated, but co-located with the start joint of the primary chain.
            If a joint is not supplied a flag will not be created for this.
        :param bool mid_flag: If we should create a mid component flag. Currently always forced on.
        :param bool can_retract: If this component will be setup with the ability to retract. Currently always forced
            on.
        :param dict kwargs: Extra build arguments passed through to SplineIKComponent.create.
        :return: The newly created SporeTongueComponent
        :rtype: SporeTongueComponent
        """

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        pm.namespace(set=f'{root_namespace}:')

        # mid_flag and can_retract are currently forced on regardless of the arguments: the spore network below
        # merges into the retract scale plugs and expects the mid flag layout.
        node = spline_ik_component.SplineIKComponent.create(frag_parent=frag_parent,
                                                            start_joint=start_joint,
                                                            end_joint=end_joint,
                                                            leaf_joint_list=leaf_joint_list,
                                                            end_helper_joint=end_helper_joint,
                                                            mid_helper_joint=mid_helper_joint,
                                                            side=side,
                                                            region=region,
                                                            start_helper_joint=start_helper_joint,
                                                            mid_flag=True,
                                                            can_retract=True,
                                                            **kwargs)

        # reset our node types.
        node.pynode.setAttr(frag_base.FRAG_TYPE_ATTR, SporeTongueComponent.__name__)
        node.pynode.setAttr('version', SporeTongueComponent.VERSION)

        # get the objects we need to set the scale
        end_flag = node.pynode.endFlag.get()
        helper_joint = node.pynode.helperJoint.get()
        leaf_joint_list = node.pynode.leafJoints.get()[1:-1]

        # add attrs and connection them so we can recover them later.
        for x in [end_flag, helper_joint]:
            if not x.hasAttr('spore'):
                x.addAttr('spore', dv=0, min=0, max=10, k=True)
            if not x.hasAttr('spore_scale'):
                x.addAttr('spore_scale', dv=1, min=.6, max=10, k=True)
        end_flag.spore >> helper_joint.spore
        end_flag.spore_scale >> helper_joint.spore_scale

        # The spore attribute runs 0-10 along the chain; each leaf joint owns one increment of that range.
        increment_value = 10 / (len(leaf_joint_list) + 1)
        # add our total scale modifiers in
        max_scale = pm.createNode('plusMinusAverage', n=f'{region}_{side}_spore_max_scale')
        max_scale.input1D[0].set(-1)
        end_flag.spore_scale >> max_scale.input1D[1]
        max_scale.operation.set(2)  # subtract: spore_scale - 1
        mult_nodes = []
        remap_nodes = []
        add_nodes = []

        add_nodes.append(max_scale)

        for index, leaf_joint_node in enumerate(leaf_joint_list):
            # we want a min scale of 1 so the ends of our bell curve are equal to 1
            # we want a max of 2 scale so our sum at our peak is 2
            # equation looks like this -N*X^2 + -2N*X + 1
            # N is our max scale output, X is our remap out
            # this creates a parabola in the 0-2 range with 1 at it's peak
            remap = pm.createNode('remapValue', n=f'{naming.get_basename(leaf_joint_node)}_remap')
            remap_nodes.append(remap)
            end_flag.spore >> remap.inputValue
            remap.inputMin.set(index * increment_value)
            remap.inputMax.set((index + 2) * increment_value)
            remap.outputMin.set(0)
            remap.outputMax.set(2)

            # this handles the X^2 and -2X portion of our equation
            input_multi = pm.createNode('multiplyDivide', n=f'{naming.get_basename(leaf_joint_node)}_input_multi')
            mult_nodes.append(input_multi)
            remap.outValue >> input_multi.input1X
            remap.outValue >> input_multi.input2X
            input_multi.input1Y.set(-2)
            max_scale.output1D >> input_multi.input2Y

            # this handles the -N and N portion of our equation
            parabola_multi = pm.createNode('multiplyDivide',
                                           n=f'{naming.get_basename(leaf_joint_node)}_parabola_multi')
            mult_nodes.append(parabola_multi)
            max_scale.output1D >> parabola_multi.input1X
            input_multi.outputX >> parabola_multi.input2X

            input_multi.outputY >> parabola_multi.input1Y
            remap.outValue >> parabola_multi.input2Y

            # add it all together to get our finished quadratic
            scale_sum = pm.createNode('plusMinusAverage', n=f'{naming.get_basename(leaf_joint_node)}_scale_sum')
            add_nodes.append(scale_sum)
            parabola_multi.outputX >> scale_sum.input1D[0]
            parabola_multi.outputY >> scale_sum.input1D[1]
            scale_sum.input1D[2].set(1)

            # apply it to our live joints.
            original_plug = lists.get_first_in_list(leaf_joint_node.sz.listConnections(p=True))
            if not original_plug:
                # The original component could not retract, so the bulge owns the scale plugs.
                scale_sum.output1D >> leaf_joint_node.sy
                scale_sum.output1D >> leaf_joint_node.sz
            else:
                # The base component could retract, so disconnect that and merge our scale values into it.
                pm.disconnectAttr(leaf_joint_node.sy)
                pm.disconnectAttr(leaf_joint_node.sz)

                retract_merge_multi = pm.createNode('multiplyDivide',
                                                    n=f'{naming.get_basename(leaf_joint_node)}_retract_merge_multi')
                mult_nodes.append(retract_merge_multi)

                original_plug >> retract_merge_multi.input1X
                scale_sum.output1D >> retract_merge_multi.input2X

                retract_merge_multi.outputX >> leaf_joint_node.sy
                retract_merge_multi.outputX >> leaf_joint_node.sz

        node.connect_nodes(remap_nodes, 'remapNodes', 'fragParent')
        node.connect_nodes(mult_nodes, 'multNodes', 'fragParent')
        node.connect_nodes(add_nodes, 'addNodes', 'fragParent')

        return node
