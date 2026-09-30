"""
Skeleton markup: describing a skeleton on the skeleton itself.

A rig builder has to be able to find "the left arm" in a skeleton it has never seen. Doing that by
name means every skeleton in the studio has to be named the same way for ever, so instead the
description is written onto the joints as string attributes, and the builders read those:

- ``skelSide`` and ``skelRegion`` - which side ('left', 'right', 'center') and which region
  ('arm', 'spine', ...) a joint belongs to. With no ``skelSide``, Maya's own ``joint.side`` enum
  is read instead, which is what a skeleton imported from elsewhere will have.
- ``chainStart`` and ``chainEnd`` - the region name, written on the first and last joint of a
  chain. A chain's end often belongs to the *next* region: the wrist ends the arm and names the
  hand.
- ``chainTwist`` - the twist chain a helper joint belongs to, for joints that are not part of the
  main chain.
- ``hierarchyStart`` - the first joint of the animatable hierarchy, below the root.
- ``skExport`` and ``animationExport`` - whether the joint goes into the skeletal mesh export and
  the animation export. Absent means yes.

:class:`JointMarkup` reads and writes that markup on one joint. :class:`ChainMarkup` walks a whole
skeleton and sorts it into a region to side to chain lookup, so a builder can ask for the start,
the end, or the whole of a named chain.

What was wrong before:

- **A joint could not be marked as not-exported.** ``is_sk_export`` and ``is_animation_export``
  stored "no" by *deleting* the attribute - and their getters created the attribute with a default
  of True whenever it was missing. So setting either to False removed the attribute and the next
  read put it back as True. Checked in a real Maya: set False, read back True. Both the skeleton
  builder and the auto-rigging tool let an artist tick a joint out of an export, and neither tick
  has ever stuck; ``ChainMarkup``'s export lists were the whole skeleton every time. The flag is
  stored now, and absence still means yes.
- **Reading the markup wrote to the scene.** The same two getters added an attribute as a side
  effect of being asked a question, and ``ChainMarkup.parse_joints`` asks both of them about every
  joint - so merely constructing a ``ChainMarkup`` to look something up added two attributes to
  every joint in the skeleton and left the scene dirty. Reading answers the default now and
  creates nothing.
- **Clearing a chain marking raised on a joint that did not have it.** The setters read
  ``if not hasAttr(...): if val: ...add... elif not val: ...delete...`` - so a joint with no
  ``chainStart`` being set to ``''`` matched neither branch and fell through to
  ``self.joint.chainStart.set(val)``: ``AttributeError: nt.Joint('...') has no attribute or method
  named 'chainStart'``. Checked in a real Maya.
- **``hierarchyStart`` could only be set once.** Its setter called ``addAttr`` unguarded, so
  setting it True on a joint that already had it raised ``RuntimeError: Found no valid items to
  add the attribute to``.
- **``chainStart`` assumed that a joint with the attribute also had ``skelRegion``.** It created
  the region attribute only in the branch where ``chainStart`` was missing, then set it either
  way.
- **A region whose chain end came from another region crashed on its own middle joints.** A wrist
  in the arm region with ``chainEnd = 'hand'`` files that end under ``chain_dict['hand'][side]``,
  and it builds that entry as an empty dictionary - no ``'joints'`` key. The guard that would have
  created one is an ``elif`` on the side not being there yet, and it is there. So the next hand
  joint with neither a start nor an end marking hit
  ``chain_dict['hand'][side]['joints'].append(...)`` and raised ``KeyError: 'joints'``. Reproduced
  from the real parse order: wrist, hand, palm.
- **``parse_joints`` did not reset everything it fills.** ``_invalid_joints`` and
  ``_hierarchyStart`` were left alone, so parsing a second time appended to the first pass's
  invalid list and kept a hierarchy start that may have been removed since.
- ``is_valid`` was ``not any(self._invalid_joints)``, which walks a list of PyNodes testing each
  one's truthiness to answer a question about the list's length.
- ``remove_is_start`` and ``remove_is_end`` had no callers; setting the property to ``''`` is the
  same thing, and now works.
- ``_invalid_joints``, ``_animationJoints`` and ``_skJoints`` were read from outside the class -
  they have public properties now.
"""

# python imports

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.startup.configs import ma_consts
from mca.mya.utils import dag
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: The side and region a joint belongs to.
SIDE_ATTR = 'skelSide'
REGION_ATTR = 'skelRegion'

#: The region name, written on a chain's first and last joint.
CHAIN_START_ATTR = 'chainStart'
CHAIN_END_ATTR = 'chainEnd'

#: The twist chain a helper joint belongs to.
CHAIN_TWIST_ATTR = 'chainTwist'

#: Whether the joint goes into each export. Absent means yes.
SK_EXPORT_ATTR = 'skExport'
ANIMATION_EXPORT_ATTR = 'animationExport'

#: The first joint of the animatable hierarchy.
HIERARCHY_START_ATTR = 'hierarchyStart'


class JointMarkup(object):
    """
    The markup on one joint, as properties.

    Reading never changes the scene. Writing adds the attribute it needs; writing a falsy value to
    one of the chain markings removes the attribute again, which is how a marking is cleared.
    """

    def __init__(self, joint_node):
        """
        :param pm.nt.Joint joint_node: The joint whose markup this is.
        """

        self.node = joint_node

    def __repr__(self):
        return '{0}({1})'.format(type(self).__name__, self.node)

    @property
    def joint(self):
        """
        :return: The joint being read or written.
        :rtype: pm.nt.Joint
        """

        return self.node

    # ----------------------------------------------------------------------------------- #
    # reading and writing an attribute that may not be there
    # ----------------------------------------------------------------------------------- #
    def _read(self, attr_name, default=None):
        """
        An attribute's value, or a default when the joint does not have it.

        :param str attr_name: The attribute to read.
        :param default: What to answer when it is not there.
        :return: The value, or the default.
        """

        if not self.joint.hasAttr(attr_name):
            return default
        return self.joint.attr(attr_name).get()

    def _write(self, attr_name, value, attr_kwargs=None, remove_when_falsy=False):
        """
        Set an attribute, adding it first when the joint does not have it.

        :param str attr_name: The attribute to write.
        :param value: What to write.
        :param dict attr_kwargs: How to build the attribute, when it has to be built.
        :param bool remove_when_falsy: A falsy value removes the attribute rather than storing it.
            This is how a chain marking is cleared. It is *not* how an export flag stores "no" -
            that was the bug.
        """

        if remove_when_falsy and not value:
            if self.joint.hasAttr(attr_name):
                self.joint.deleteAttr(attr_name)
            # Nothing to write, and nothing to raise about either - the old setters fell through
            # to a set() on an attribute they had just decided not to create.
            return

        if not self.joint.hasAttr(attr_name):
            self.joint.addAttr(attr_name, **(attr_kwargs or {'dt': 'string'}))
        self.joint.attr(attr_name).set(value)

    # ----------------------------------------------------------------------------------- #
    # side and region
    # ----------------------------------------------------------------------------------- #
    @property
    def side(self):
        """
        :return: The side the joint is on, in lower case.
        :rtype: str
        """

        if self.joint.hasAttr(SIDE_ATTR):
            return self.joint.attr(SIDE_ATTR).get()

        # No markup: fall back to Maya's own joint side enum, which is what an imported skeleton
        # will have.
        return ma_consts.SIDE_LABELS[self.joint.side.get()].lower()

    @side.setter
    def side(self, value):
        """
        :param value: A side name, or an index into :data:`ma_consts.SIDE_LABELS`.
        """

        if isinstance(value, str):
            self._write(SIDE_ATTR, value.lower())
        elif isinstance(value, int) and not isinstance(value, bool):
            self._write(SIDE_ATTR, ma_consts.SIDE_LABELS[value].lower())
        else:
            logger.warning('%s is not a side name or an index into %s, so the side of %s was left '
                           'alone.', value, ma_consts.SIDE_LABELS, self.joint)

    @property
    def region(self):
        """
        The region the joint belongs to.

        With no ``skelRegion`` the chain markings are used instead, because a joint that starts or
        ends a chain names its region by doing so.

        :return: The region, or None when the joint has no region markup at all.
        :rtype: str or None
        """

        if self.joint.hasAttr(REGION_ATTR):
            return self.joint.attr(REGION_ATTR).get()
        return self.chainStart or self.chainEnd or self.chainTwist or None

    @region.setter
    def region(self, value):
        """
        :param str value: The region name.
        """

        self._write(REGION_ATTR, value)

    # ----------------------------------------------------------------------------------- #
    # chain markings
    # ----------------------------------------------------------------------------------- #
    @property
    def chainTwist(self):
        """
        :return: The twist chain's name, or False when the joint is not a twist joint.
        :rtype: str or bool
        """

        return self._read(CHAIN_TWIST_ATTR, default=False)

    @chainTwist.setter
    def chainTwist(self, value):
        """
        :param str value: The twist chain this joint belongs to. Falsy clears it.
        """

        self._write(CHAIN_TWIST_ATTR, value, remove_when_falsy=True)

    @property
    def chainStart(self):
        """
        :return: The region this joint starts, or False when it does not start one.
        :rtype: str or bool
        """

        return self._read(CHAIN_START_ATTR, default=False)

    @chainStart.setter
    def chainStart(self, value):
        """
        Mark the joint as the start of a chain, which also names its region.

        :param str value: The region name. Falsy clears the marking, leaving the region alone.
        """

        self._write(CHAIN_START_ATTR, value, remove_when_falsy=True)
        if value:
            # Outside the branch that creates chainStart: a joint can have chainStart already and
            # still be missing skelRegion, and the old setter then raised on the line below.
            self._write(REGION_ATTR, value)

    @property
    def chainEnd(self):
        """
        :return: The region this joint ends, or False when it does not end one.
        :rtype: str or bool
        """

        return self._read(CHAIN_END_ATTR, default=False)

    @chainEnd.setter
    def chainEnd(self, value):
        """
        :param str value: The region this joint ends. Falsy clears the marking.
        """

        self._write(CHAIN_END_ATTR, value, remove_when_falsy=True)

    # ----------------------------------------------------------------------------------- #
    # export flags
    # ----------------------------------------------------------------------------------- #
    @property
    def is_sk_export(self):
        """
        :return: Whether the joint goes into the skeletal mesh export. True when unmarked.
        :rtype: bool
        """

        return bool(self._read(SK_EXPORT_ATTR, default=True))

    @is_sk_export.setter
    def is_sk_export(self, value):
        """
        :param bool value: Whether the joint goes into the skeletal mesh export.
        """

        # Stored, not deleted. Deleting was how False used to be stored, and the getter then
        # created the attribute again with a default of True.
        self._write(SK_EXPORT_ATTR, bool(value), attr_kwargs={'at': 'bool', 'dv': True})

    @property
    def is_animation_export(self):
        """
        :return: Whether the joint goes into the animation export. True when unmarked.
        :rtype: bool
        """

        return bool(self._read(ANIMATION_EXPORT_ATTR, default=True))

    @is_animation_export.setter
    def is_animation_export(self, value):
        """
        :param bool value: Whether the joint goes into the animation export.
        """

        self._write(ANIMATION_EXPORT_ATTR, bool(value), attr_kwargs={'at': 'bool', 'dv': True})

    @property
    def hierarchyStart(self):
        """
        :return: Whether this joint is the first of the animatable hierarchy.
        :rtype: bool
        """

        return bool(self._read(HIERARCHY_START_ATTR, default=False))

    @hierarchyStart.setter
    def hierarchyStart(self, value):
        """
        :param bool value: Whether this joint is the first of the animatable hierarchy. Falsy
            clears the marking, since there is only ever one.
        """

        self._write(HIERARCHY_START_ATTR, bool(value),
                    attr_kwargs={'at': 'bool', 'dv': True}, remove_when_falsy=True)

    # ----------------------------------------------------------------------------------- #
    # reading the joint itself
    # ----------------------------------------------------------------------------------- #
    @property
    def name(self):
        """
        :return: The joint's name without its namespace or its path.
        :rtype: str
        """

        return naming.get_basename(self.joint.name())

    def get_joint_index(self):
        """
        Where this joint sits in its own chain.

        This walks the whole skeleton to answer, because the chain is a property of the markup
        across the skeleton rather than of this joint - so it is not a thing to call in a loop.

        :return: The index, or None when the joint's chain cannot be found.
        :rtype: int or None
        """

        root_joint = dag.get_absolute_parent(self.joint, node_type=pm.nt.Joint)
        if not root_joint:
            logger.warning('%s is not under a root joint, so it has no chain to be an index in.',
                           self.joint)
            return None

        joint_chain_list = ChainMarkup(root_joint).get_full_chain(self.region, self.side)
        if self.node not in joint_chain_list:
            return None
        return joint_chain_list.index(self.node)

    def get_world_matrix(self):
        """
        :return: The joint's world matrix, as sixteen numbers.
        :rtype: list(float)
        """

        return pm.xform(self.joint, matrix=True, query=True, worldSpace=True)

    def getParent(self):
        """
        :return: The parent, wrapped when it is a joint and raw when it is not, or None.
        :rtype: JointMarkup or pm.nt.Transform or None
        """

        parent_node = self.joint.getParent()
        if isinstance(parent_node, pm.nt.Joint):
            return JointMarkup(parent_node)
        return parent_node

    def getChildren(self):
        """
        :return: The immediate child joints, wrapped.
        :rtype: list(JointMarkup)
        """

        return [JointMarkup(child) for child in self.joint.getChildren(type=pm.nt.Joint)]


class ChainMarkup(object):
    """
    A skeleton's markup, sorted into chains.

    Construction walks the hierarchy below the root joint and reads every joint's markup. Nothing
    in the scene is created or changed by it - which was not true of the version this replaces.
    """

    def __init__(self, root):
        """
        :param pm.nt.Joint root: The skeleton's root joint.
        """

        self._root = root
        self._hierarchyStart = None
        self._skJoints = []
        self._animationJoints = []
        self._joints = []
        self._twist_joints = {}
        self._chain = {}
        self._invalid_joints = []
        self._skeleton_dict = None

        self.parse_joints()

    def __repr__(self):
        return '{0}({1})'.format(type(self).__name__, self._root)

    # ----------------------------------------------------------------------------------- #
    # what was found
    # ----------------------------------------------------------------------------------- #
    @property
    def is_valid(self):
        """
        :return: True when every joint in the hierarchy has region markup.
        :rtype: bool
        """

        return not self._invalid_joints

    @property
    def invalid_joints(self):
        """
        :return: The joints with no region markup, which is what makes a skeleton not valid.
        :rtype: list(pm.nt.Joint)
        """

        return self._invalid_joints

    @property
    def root(self):
        """
        :return: The skeleton's root joint.
        :rtype: pm.nt.Joint
        """

        return self._root

    @property
    def hierarchyStart(self):
        """
        :return: The joint marked as the start of the animatable hierarchy, or None.
        :rtype: pm.nt.Joint or None
        """

        return self._hierarchyStart

    @property
    def joints(self):
        """
        :return: Every joint in the hierarchy, in the order it was walked.
        :rtype: list(pm.nt.Joint)
        """

        return self._joints

    @property
    def sk_joints(self):
        """
        :return: The joints that go into the skeletal mesh export.
        :rtype: list(pm.nt.Joint)
        """

        return self._skJoints

    @property
    def animation_joints(self):
        """
        :return: The joints that go into the animation export.
        :rtype: list(pm.nt.Joint)
        """

        return self._animationJoints

    @property
    def chain(self):
        """
        :return: ``{region: {side: {'chain_start': j, 'chain_end': j, 'joints': [j, ...]}}}``.
        :rtype: dict
        """

        return self._chain

    @property
    def twist_joints(self):
        """
        :return: ``{side: {twist chain name: {'parent': j, 'joints': [j, ...]}}}``.
        :rtype: dict
        """

        return self._twist_joints

    @property
    def skeleton_dict(self):
        """
        The skeleton as a name to joint lookup, for mapping one skeleton onto another.

        Worked out when it is first asked for rather than at construction, which is what lets this
        module stay out of ``joint_utils`` at import time - the two used to import each other.

        :return: ``{joint name: joint}``, with the root under ``'root'``.
        :rtype: dict
        """

        if self._skeleton_dict is None:
            from mca.mya.rigging import joint_utils
            self._skeleton_dict = joint_utils.create_skeleton_dict(self._root)
        return self._skeleton_dict

    # ----------------------------------------------------------------------------------- #
    # the walk
    # ----------------------------------------------------------------------------------- #
    @ma_decorators.keep_selection_decorator
    def parse_joints(self):
        """
        Read every joint's markup and rebuild the chain, twist and export lookups from it.

        Everything this fills is cleared first, so parsing twice gives the same answer as parsing
        once - the version before kept the first pass's invalid joints and hierarchy start.
        """

        self._joints = dag.get_children_in_order(self.root, pm.nt.Joint)
        self._hierarchyStart = None
        self._skJoints = []
        self._animationJoints = []
        self._twist_joints = {}
        self._invalid_joints = []
        chain_dict = {}

        for joint_node in self._joints:
            # The wrapper is for reading; the lookups hold the PyNode, because callers go on to
            # do Maya work with what they find.
            wrapped_joint = JointMarkup(joint_node)

            if wrapped_joint.hierarchyStart:
                self._hierarchyStart = joint_node
            if wrapped_joint.is_sk_export:
                self._skJoints.append(joint_node)
            if wrapped_joint.is_animation_export:
                self._animationJoints.append(joint_node)

            if wrapped_joint.chainTwist:
                side_twist_dict = self._twist_joints.setdefault(wrapped_joint.side, {})
                twist_chain = side_twist_dict.setdefault(wrapped_joint.chainTwist,
                                                         {'parent': joint_node.getParent(),
                                                          'joints': []})
                twist_chain['joints'].append(joint_node)

            skel_region = wrapped_joint.region
            if not skel_region:
                self._invalid_joints.append(joint_node)
                continue

            skel_side = wrapped_joint.side
            if not skel_side:
                continue

            # setdefault throughout: a region and side can already be in here because another
            # joint filed its chain end under them, and that used to leave an entry with no
            # 'joints' key for the next middle joint to trip over.
            side_dict = self._chain_side(chain_dict, skel_region, skel_side)

            if wrapped_joint.chainStart:
                side_dict['chain_start'] = joint_node
            if wrapped_joint.chainEnd:
                # A chain's end usually belongs to the next region along - the wrist ends the arm
                # and starts the hand - so it is filed under the region it ends.
                end_side_dict = self._chain_side(chain_dict, wrapped_joint.chainEnd, skel_side)
                end_side_dict['chain_end'] = joint_node
            if not wrapped_joint.chainStart and not wrapped_joint.chainEnd:
                side_dict['joints'].append(joint_node)

        self._chain = chain_dict

    @staticmethod
    def _chain_side(chain_dict, region, side):
        """
        The entry for one region and side, made if it is not there yet.

        :param dict chain_dict: The lookup being built.
        :param str region: The region.
        :param str side: The side.
        :return: ``{'joints': [...]}``, plus whatever has been filed in it already.
        :rtype: dict
        """

        return chain_dict.setdefault(region, {}).setdefault(side, {'joints': []})

    # ----------------------------------------------------------------------------------- #
    # asking about a chain
    # ----------------------------------------------------------------------------------- #
    def get_start(self, region, side):
        """
        :param str region: The region.
        :param str side: The side.
        :return: The chain's first joint, or None when nothing matches.
        :rtype: pm.nt.Joint or None
        """

        return self._chain.get(region, {}).get(side, {}).get('chain_start', None)

    def get_end(self, region, side):
        """
        :param str region: The region.
        :param str side: The side.
        :return: The chain's last joint, or None when nothing matches.
        :rtype: pm.nt.Joint or None
        """

        return self._chain.get(region, {}).get(side, {}).get('chain_end', None)

    def get_chain(self, region, side):
        """
        :param str region: The region.
        :param str side: The side.
        :return: The first and last joint - either may be None when only one end is marked up -
            or None when there is no such chain at all.
        :rtype: tuple(pm.nt.Joint, pm.nt.Joint) or None
        """

        side_dict = self._chain.get(region, {}).get(side, {})
        if not side_dict:
            return None
        return side_dict.get('chain_start', None), side_dict.get('chain_end', None)

    def get_full_chain(self, region, side):
        """
        Every joint in a chain, in order.

        :param str region: The region.
        :param str side: The side.
        :return: The start, then the middle joints, then the end. Empty when nothing matches.
        :rtype: list(pm.nt.Joint)
        """

        side_dict = self._chain.get(region, {}).get(side, {})
        joint_list = []
        chain_start = side_dict.get('chain_start', None)
        if chain_start:
            joint_list.append(chain_start)
        joint_list += side_dict.get('joints', [])
        chain_end = side_dict.get('chain_end', None)
        if chain_end:
            joint_list.append(chain_end)

        if not joint_list:
            logger.warning('No joints match the lookup %s, %s. Check the markup on the skeleton.',
                           region, side)
        return joint_list
