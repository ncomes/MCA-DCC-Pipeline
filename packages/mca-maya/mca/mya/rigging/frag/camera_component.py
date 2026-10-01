"""

A camera on a control, so an animator can key a shot the way they key a character.

One FK control on one joint, with the camera parent constrained to the control. Like the clavicle,
it is an :class:`~fk_component.FKComponent` underneath and exists as its own class because a rig
has to be able to find the camera: a FRAG node carries nothing but its class name to say what it
is.

What was wrong before:

- **The class spells its version ``LATEST_VERSION``**, so ``CameraComponent.VERSION`` is
  ``FKComponent``'s. Both happen to be 1, which is the only reason nothing has gone wrong: the
  moment either class's number moves, ``FRAGNode.update`` is comparing the node's version against
  the *parent* class's and either does nothing or looks for a step named from the wrong pair. It is
  ``VERSION``, as it is on every other component.
- **A camera whose control has no free channel raised.** ``constraint.parent_constraint_safe``
  answers None when every channel it would drive is locked, and the answer went straight into
  ``connect_node`` - which puts it through ``pm.PyNode``, and ``pm.PyNode(None)`` raises. The
  control is built with its translates unlocked, so this needs a locked rig to reach; it says what
  happened instead.
- **``create`` takes no ``**kwargs``**, so a rebuild cannot hand it a component's recorded argument
  list - and this class does not replace the ``buildKwargs`` block ``FKComponent.create`` writes,
  so what is recorded is FK's argument list, most of which this signature has no parameter for. It
  takes ``**kwargs``, and records the two things of its own that a rebuild needs.
- ``node.pynode.fragType.set(...)`` was written by hand where the attribute has a constant, as did
  the renaming. ``get_cam`` and ``get_cam_flag`` each read a list and took its first entry with
  their own guard; both are one line.
"""

# mca imports
from mca.common import log
from mca.common.utils import lists
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging.frag import fk_component
from mca.mya.rigging.frag import frag_base
from mca.mya.utils import attr_utils
from mca.mya.utils import constraint
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: What the component keeps its pieces on.
CAMERA_ATTR = 'cam'
CONSTRAINTS_ATTR = 'constraints'


class CameraComponent(fk_component.FKComponent):
    """
    One FK control driving a camera.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, joint, side, region, cam, scale=1.0, **kwargs):
        """
        Build the component over one joint and attach a camera to it.

        :param FRAGNode frag_parent: The rig this belongs to.
        :param pm.nt.Joint joint: The joint the control drives.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param pm.nt.Transform cam: The camera to put on the control.
        :param float scale: How big to draw the control.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component.
        :rtype: CameraComponent
        """

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        # A camera is moved as well as turned, so its control keeps its translate channels.
        node = fk_component.FKComponent.create(frag_parent, joint, joint, side=side, region=region,
                                               scale=scale, lock_child_translate_axes=(),
                                               lock_root_translate_axes=())

        node.pynode.attr(frag_base.FRAG_TYPE_ATTR).set(CameraComponent.__name__)
        node.set_version(CameraComponent.VERSION)
        node.pynode.rename('{0}_{1}_{2}'.format(CameraComponent.__name__, side, region))

        # This replaces the block FKComponent.create wrote, because this class takes a different
        # argument list - so everything a rebuild needs has to be in here.
        attr_utils.set_compound_attribute_groups(node.pynode, frag_base.BUILD_KWARGS_ATTR,
                                                 {'scale': scale})

        camera_component = CameraComponent(node.pynode)
        flag_node = camera_component.get_cam_flag()
        camera_constraint = constraint.parent_constraint_safe(flag_node, cam, mo=True)

        camera_component.connect_node(cam, CAMERA_ATTR, frag_base.FRAG_PARENT_ATTR)
        if camera_constraint:
            camera_component.connect_node(camera_constraint, CONSTRAINTS_ATTR,
                                          frag_base.FRAG_PARENT_ATTR)
        else:
            # pm.PyNode(None) raises, so the version before raised here rather than saying this.
            logger.warning('%s has no channel free to be driven, so %s is not on the control.',
                           cam, cam)

        return camera_component

    def get_cam_flag(self):
        """
        :return: The control the camera is on, or None when the component has lost it.
        :rtype: frag_flag.Flag or None
        """

        return lists.get_first_in_list(self.get_flags())

    def get_cam(self):
        """
        :return: The camera, or None when the component has lost it.
        :rtype: pm.nt.Transform or None
        """

        return self.pynode.attr(CAMERA_ATTR).get()
