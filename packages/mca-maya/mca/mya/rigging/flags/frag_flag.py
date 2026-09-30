"""
Flags: the controls an animator selects.

A flag is a joint drawn as nothing, carrying a NURBS curve shape and a handful of marker
attributes. A joint rather than a transform because a joint has a ``jointOrient``, which is where
a control's build-time orientation can be put without spending its rotate channels; drawn as
nothing so the bone does not show; and the curve shape is what the animator actually clicks.

The shape is not part of the rig build. A rig is built with a placeholder cube on every control,
and :func:`swap_flags` then replaces those with per-rig shapes read from ``.flag`` files - which is
how a rigger reshapes a control without rebuilding anything. :func:`export_flag` writes one of
those files from a shape they have made; :func:`import_flag` reads it back.

:class:`Flag` wraps the control and forwards anything it does not define to the PyNode underneath,
so a flag can be passed anywhere a node is expected.

What was wrong before:

- **Every flag imported from a ``.flag`` file came back with its shape twice.**
  ``deserialize_flag`` builds the transform from the first shape's data - and then builds a second
  curve from the same data and parents that shape in alongside it. For a one-shape flag, which is
  almost all of them, the result is two identical overlapping curves. Checked in a real Maya: two
  shapes on the rebuilt transform. ``swap_flags`` then moves both onto the rig's control, so every
  rig built with custom flag shapes has been carrying doubled curves on every control - twice the
  geometry to draw, and templating or hiding one of them leaves the other behind.
- **The homogeneous-coordinate conversion never ran.** A comment says ``getCVs()`` returns 4D
  points and the code divides each by its ``w``. It returns three components - checked in a real
  Maya - so the branch was dead. It is kept, because a ``.flag`` file written by something that did
  store four is still readable, but it no longer claims to be there for Maya's benefit.
- **A hundred and twenty lines of the class were one-line forwards to the wrapped node.** Fourteen
  dunder methods, each ``return self.node.<the same name>(...)``. They have to exist on the class,
  because Python looks dunders up on the type and never reaches ``__getattr__`` - so they are built
  from a list of names now rather than typed out.
- **``hide_align_transform`` raised on a flag built without an align transform.**
  ``get_align_transform`` answers None for one, and the next line was ``align.v.set(0)``.
- **Re-orienting a flag's align transform reached into the artist's selection.**
  :meth:`Flag.create` builds its joint at the top of the scene, so the align group above it has no
  parent - and the ``orientation`` branch then called ``pm.parent(None, world=True)``, twice.
  ``pm.parent`` given ``None`` falls back to whatever is selected, so that un-parented the current
  selection to the world; with nothing selected it raised ``TypeError: Error retrieving default
  arguments``. Both checked in a real Maya. The branch only ever looked correct because its last
  line put the flag back under its align group.
- **Building a flag changed what the artist had selected.** ``pm.select(cl=True)`` to make the
  joint, and then ``pm.curve``, ``pm.parent`` and ``makeIdentity`` each leaving their own node
  selected - a flag build ended with the new flag selected and whatever the artist had chosen
  gone. The whole of :meth:`Flag.create` runs inside the maintained-selection context now, which
  is also what stops the ``orientation`` branch above from having anything to reach into.
- **``export_flag`` gave up silently.** Two early returns with no message: one when the node's first
  shape is not a curve, one when there was nothing to serialize. A rigger exporting the wrong
  selection got no file and no reason.
- **The serializer version was written and never read.** It still is written, for the next person
  who changes the format, but nothing has ever checked it, and this says so rather than implying
  otherwise.
- ``Flag.create`` wrote the same four lines four times over for the four marker attributes, and
  named a temporary curve transform after the shape
  it was about to throw away. ``create_align_transform`` was reached through ``rig_utils``, so
  building a flag pulled in 1,752 lines of rig building - and everything in ``rig_utils`` needs
  flags. It is in ``utils.groups`` now, beside the function it wraps.
"""

# python imports
import os

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.common.textio import yamlio
from mca.common.utils import fileio
from mca.mya.modifiers import contexts
from mca.mya.rigging import joint_utils
from mca.mya.utils import attr_utils
from mca.mya.utils import dag
from mca.mya.utils import groups
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: Written into every ``.flag`` file. Nothing reads it - it is there so that a future change to the
#: format has something to branch on.
SERIALIZER_VERSION = '1.0'

#: The bool that says a node is a flag at all.
IS_FLAG_ATTR = 'isFlag'

#: The message attribute the display layer system connects to.
FLAG_LAYER_ATTR = 'flagLayer'

#: The four kinds of flag, each a bool on the control. A flag can be none of them, which is an
#: ordinary animation control.
FLAG_TYPES = ('isDetail', 'isSub', 'isContact', 'isUtil')

#: The extension a serialized flag shape is saved under.
FLAG_EXTENSION = '.flag'

#: Maya's ``drawStyle`` for "None", which hides a joint's bone and leaves only its shape.
JOINT_DRAW_STYLE_NONE = 2

#: Maya's periodic curve form.
PERIODIC_FORM = 3

#: The placeholder shape every flag is built with: one degree-1 curve tracing every edge of a cube,
#: seventeen points so it closes back on itself. Rig-specific shapes replace it through
#: :func:`swap_flags`.
PLACEHOLDER_CUBE_POINTS = ((7, 7, 7), (7, 7, -7), (7, -7, -7), (7, -7, 7), (7, 7, 7), (-7, 7, 7),
                           (-7, 7, -7), (7, 7, -7), (7, -7, -7), (-7, -7, -7), (-7, -7, 7),
                           (7, -7, 7), (7, 7, 7), (-7, 7, 7), (-7, -7, 7), (-7, -7, -7),
                           (-7, 7, -7))

#: The knots for the cube above: strictly increasing, one per point. A doubled knot here used to
#: make Maya complain about coincident knots on every flag built.
PLACEHOLDER_CUBE_KNOTS = tuple(range(len(PLACEHOLDER_CUBE_POINTS)))

#: Prefix on a flag's name, and the bind-joint prefix that is stripped off the name it is built
#: from - a flag for ``b_l_hand`` is ``f_l_hand``, not ``f_b_l_hand``.
FLAG_PREFIX = 'f_'
BIND_JOINT_PREFIX = 'b'


def is_flag_node(obj_node):
    """
    Whether a node is a flag.

    :param obj_node: The node to check.
    :return: True when it is a transform carrying the flag marker.
    :rtype: bool
    """

    if not isinstance(obj_node, pm.nt.Transform):
        return False
    return bool(obj_node.hasAttr(IS_FLAG_ATTR) and obj_node.attr(IS_FLAG_ATTR).get())


class Flag(object):
    """
    One animation control.

    Anything not defined here is forwarded to the wrapped PyNode, so a ``Flag`` can go anywhere a
    node can.
    """

    def __init__(self, node):
        """
        :param node: The flag transform to wrap, as a node or a name.
        """

        self.node = pm.PyNode(node)

    @classmethod
    def create(cls, object_to_match,
               shape=None,
               maintain_shape_offset=False,
               label=None,
               point=True,
               orient=True,
               scale=1.0,
               add_align_transform=True,
               orientation=None,
               is_detail=False,
               is_sub=False,
               is_contact=False,
               is_util=False,
               meta_connect=True):
        """
        Build a control for something, aligned to it.

        :param object_to_match: What the control drives, and where it is built.
        :param shape: Taken for compatibility with existing callers and unused - every flag is
            built with the placeholder cube and reshaped later by :func:`swap_flags`.
        :param bool maintain_shape_offset: Leave the shape where it is in the world rather than
            letting it move onto the control.
        :param str label: A name for the control. None takes one from ``object_to_match``.
        :param bool point: Match the position.
        :param bool orient: Match the orientation.
        :param float scale: How big to draw it.
        :param bool add_align_transform: Put a zeroed group above it, so its own channels start at
            zero.
        :param orientation: A rotation for the align group, so the control's zero pose is turned.
            Only used with ``add_align_transform``.
        :param bool is_detail: Mark it as a detail flag.
        :param bool is_sub: Mark it as a sub flag.
        :param bool is_contact: Mark it as a contact flag.
        :param bool is_util: Mark it as a utility flag.
        :param bool meta_connect: Wire the control to the thing it drives, both ways.
        :return: The control.
        :rtype: Flag
        """

        if not object_to_match or not pm.objExists(object_to_match):
            raise pm.MayaNodeError(
                'The object given to match, {0}, does not exist.'.format(object_to_match))
        object_to_match = pm.PyNode(object_to_match)

        # The whole build runs inside the selection context. A joint is made from the
        # selection so the selection has to be empty first, and every pm.curve, pm.parent and
        # makeIdentity below leaves its own node selected - so without this, building a flag
        # ended with the artist's selection replaced by the new flag.
        with contexts.maintained_selection_context():
            pm.select(clear=True)
            _flag = pm.joint()

            _flag.rotateOrder.set(object_to_match.rotateOrder.get())

            if meta_connect:
                attr_utils.connect_nodes_with_message_attrs(_flag, 'driven_transform',
                                                            object_to_match, 'driver_flag')

            _flag = pm.rename(_flag, FLAG_PREFIX + _flag_label(object_to_match, label))
            if isinstance(object_to_match, pm.nt.Joint):
                joint_utils.inherit_joint_labelling(object_to_match, _flag)

            shape_node = pm.curve(degree=1, point=PLACEHOLDER_CUBE_POINTS, knot=PLACEHOLDER_CUBE_KNOTS)
            shape_node.scale.set(scale, scale, scale)
            pm.makeIdentity(shape_node, apply=True, t=1, r=1, s=1, n=0)

            dag.parent_shape_node(shape_node, _flag, maintain_offset=maintain_shape_offset)
            _flag.drawStyle.set(JOINT_DRAW_STYLE_NONE)
            for index, flag_shape in enumerate(_flag.getShapes()):
                flag_shape.rename('{0}Shape{1}'.format(_flag.shortName(), index if index else ''))

            if point:
                pm.delete(pm.pointConstraint(object_to_match, _flag, maintainOffset=False, weight=1))
            if orient:
                pm.delete(pm.orientConstraint(object_to_match, _flag, maintainOffset=False, weight=1))
            # Rotation into jointOrient, so the control's own rotate channels read zero at rest.
            pm.makeIdentity(_flag, apply=True, t=0, r=1, s=0, n=0)

            if add_align_transform:
                _add_align_transform(_flag, orientation)

            _flag.addAttr(IS_FLAG_ATTR, at='bool', dv=True)
            _flag.addAttr(FLAG_LAYER_ATTR, at='message')
            _flag.radius.set(keyable=False, channelBox=False)

            # The four marker bools, written once rather than four times. Defaulting them to False and
            # setting the ones asked for is the same result the old four-times-over version reached by
            # defaulting them all to True and then switching three of them off.
            wanted = {'isDetail': is_detail, 'isSub': is_sub,
                      'isContact': is_contact, 'isUtil': is_util}
            for attr_name in FLAG_TYPES:
                _flag.addAttr(attr_name, at='bool', dv=False)
                _flag.attr(attr_name).set(bool(wanted[attr_name]))

            return cls(_flag)

    @staticmethod
    def create_ratio(object_to_match,
                     ratio=0.5,
                     label='',
                     point=True,
                     orient=True,
                     scale=1,
                     shape=None,
                     add_align_transform=True,
                     is_detail=False,
                     is_sub=False):
        """
        :func:`create` with the shape offset kept.

        :param object_to_match: What the control drives. Must already be a transform.
        :param float ratio: Taken for compatibility with existing callers and unused.
        :param str label: A name for the control.
        :param bool point: Match the position.
        :param bool orient: Match the orientation.
        :param float scale: How big to draw it.
        :param shape: Taken for compatibility with existing callers and unused.
        :param bool add_align_transform: Put a zeroed group above it.
        :param bool is_detail: Mark it as a detail flag.
        :param bool is_sub: Mark it as a sub flag.
        :return: The control.
        :rtype: Flag
        """

        if not isinstance(object_to_match, pm.nt.Transform):
            raise pm.MayaNodeError(
                'The object given to match, {0}, is not a transform.'.format(object_to_match))

        return Flag.create(object_to_match=object_to_match,
                           shape=shape,
                           maintain_shape_offset=True,
                           label=label,
                           point=point,
                           orient=orient,
                           scale=scale,
                           add_align_transform=add_align_transform,
                           is_detail=is_detail,
                           is_sub=is_sub)

    @property
    def name(self):
        """
        :return: The flag's name, without its namespace or its path.
        :rtype: str
        """

        return naming.get_basename(self.node)

    def set_as_detail(self):
        """Mark the flag as a detail flag, which is hidden on its own display layer."""

        self.node.isDetail.set(True)

    def set_as_sub(self):
        """Mark the flag as a sub flag."""

        self.node.isSub.set(True)

    def set_as_contact(self):
        """Mark the flag as a contact flag."""

        self.node.isContact.set(True)

    def set_as_util(self):
        """Mark the flag as a utility flag."""

        self.node.isUtil.set(True)

    def get_align_transform(self):
        """
        :return: The zeroed group above the flag, or None when it was built without one.
        :rtype: pm.nt.Transform or None
        """

        return groups.get_aligned_parent_group(self.node)

    def hide_align_transform(self):
        """
        Hide the flag by turning its align group off.

        :return: Whether there was an align group to hide - the version before raised when there
            was not.
        :rtype: bool
        """

        align_transform = self.get_align_transform()
        if align_transform is None:
            logger.warning('%s has no align transform, so it was not hidden.', self.node)
            return False
        align_transform.visibility.set(0)
        return True

    def lock_and_hide_attrs(self, attr_list):
        """
        Lock some of the flag's channels and take them out of the channel box.

        :param list attr_list: The attributes to lock, long or short names.
        """

        attr_utils.lock_and_hide_attrs(self.node, attr_list)

    def __getattr__(self, attrname):
        """
        Forward anything this class does not define to the wrapped node.

        :param str attrname: What was asked for.
        :return: Whatever the node answers.
        """

        # self.node goes through __getattribute__, so this cannot recurse - but it is reached
        # during unpickling before __init__ has run, hence the guard.
        if attrname == 'node':
            raise AttributeError(attrname)
        return getattr(self.node, attrname)


def _forward_to_node(method_name):
    """
    Build one method that calls the same method on the wrapped node.

    Python looks dunder methods up on the type and never goes through ``__getattr__``, so each one
    a ``Flag`` should answer has to exist on the class. They were written out by hand before -
    fourteen of them, a hundred and twenty lines.

    :param str method_name: The method to forward.
    :return: The method.
    :rtype: callable
    """

    def forwarded(self, *args, **kwargs):
        return getattr(self.node, method_name)(*args, **kwargs)

    forwarded.__name__ = method_name
    forwarded.__doc__ = 'Forwarded to the wrapped node\'s ``{0}``.'.format(method_name)
    return forwarded


#: The dunders a Flag has to answer itself, because Python does not route them through
#: ``__getattr__``. ``__bool__`` is separate: pymel's answer is not a plain bool.
for _method_name in ('__str__', '__melobject__', '__apimfn__', '__repr__', '__radd__',
                     '__reduce__', '__eq__', '__ne__', '__lt__', '__gt__', '__le__', '__ge__',
                     '__hash__'):
    setattr(Flag, _method_name, _forward_to_node(_method_name))
del _method_name

Flag.__bool__ = lambda self: bool(self.node)
Flag.__bool__.__doc__ = 'Whether the wrapped node is something.'


def _flag_label(object_to_match, label=None):
    """
    The name a flag takes from the thing it drives.

    A bind joint's ``b_`` prefix comes off, so ``b_l_hand`` gives ``l_hand`` and the flag ends up
    ``f_l_hand`` rather than ``f_b_l_hand``.

    :param object_to_match: What the control drives.
    :param str label: A name given by the caller, which wins.
    :return: The label, with no prefix and no namespace.
    :rtype: str
    """

    label = label or naming.get_basename(object_to_match)
    parts = str(label).split('_')
    if len(parts) > 1 and parts[0] == BIND_JOINT_PREFIX:
        return '_'.join(parts[1:])
    return label


def _add_align_transform(flag_node, orientation=None):
    """
    Put a zeroed group above a flag, optionally turned.

    :param pm.nt.Joint flag_node: The flag.
    :param orientation: A rotation for the group. None leaves it aligned to the flag.
    :return: The group.
    :rtype: pm.nt.Transform
    """

    align_transform = groups.create_align_transform(flag_node)
    if not orientation:
        return align_transform

    # The group is taken out to the world to be turned, so the rotation is read in world space,
    # then put back. A flag at the top of the scene has no parent to put it back under, and the
    # version before did pm.parent(None, w=True) on it.
    align_parent = align_transform.getParent()
    if align_parent is not None:
        pm.parent(align_parent, world=True)
    align_transform.rotate.set(orientation)
    if align_parent is not None:
        pm.parent(align_transform, align_parent)
    pm.parent(flag_node, align_transform)
    flag_node.jointOrient.set(0, 0, 0)
    return align_transform


def swap_flags(flags, flag_path):
    """
    Replace the placeholder shapes on a rig's controls with the shapes saved for that rig.

    :param list flags: The controls to reshape.
    :param str flag_path: The folder the ``.flag`` files are in.
    :return: The controls that were reshaped.
    :rtype: list
    """

    swapped = []
    for found_flag in flags:
        flag_name = naming.get_basename(found_flag)
        this_flag_path = os.path.join(flag_path, flag_name + FLAG_EXTENSION)
        if not os.path.exists(this_flag_path):
            logger.warning('There is no saved shape for %s, so it keeps the placeholder: %s',
                           flag_name, this_flag_path)
            continue

        new_curve = import_flag(this_flag_path)
        if not new_curve:
            continue

        pm.delete(pm.parentConstraint(found_flag, new_curve, weight=True, maintainOffset=False))
        dag.parent_shape_node(new_curve, found_flag, maintain_offset=True, freeze_transform=True)
        swapped.append(found_flag)
    return swapped


# --------------------------------------------------------------------------------------- #
# reading and writing a shape
# --------------------------------------------------------------------------------------- #
def _get_curve_data(shape_node):
    """
    One curve shape, as numbers.

    :param pm.nt.NurbsCurve shape_node: The shape to read.
    :return: Its knots, CVs, degree and form.
    :rtype: dict
    """

    return {'knots': tuple(shape_node.getKnots()),
            'cvs': tuple(map(tuple, shape_node.getCVs('world'))),
            'degree': shape_node.degree(),
            'form': int(shape_node.form())}


def serialize_flag(transform_node):
    """
    Every curve shape on a transform, as numbers.

    :param pm.nt.Transform transform_node: The control to read.
    :return: ``{shape name: curve data}``.
    :rtype: dict
    """

    data = {}
    for found_shape in (transform_node.getShapes() or []):
        if found_shape.isIntermediateObject():
            continue
        if not isinstance(found_shape, pm.nt.NurbsCurve):
            logger.warning('%s is not a NURBS curve, so it was not serialized.', found_shape)
            continue
        data[naming.get_basename(found_shape)] = _get_curve_data(found_shape)
    return data


def export_flag(transform_node, flag_path):
    """
    Write a control's shape out as a ``.flag`` file.

    The control is duplicated, taken out to the world and zeroed first, so what is written is the
    shape and not the control's pose.

    :param pm.nt.Transform transform_node: The control to export.
    :param str flag_path: Where to write it.
    :return: Whether a file was written.
    :rtype: bool
    """

    shape = transform_node.getShape() if transform_node else None
    if not isinstance(shape, pm.nt.NurbsCurve):
        # Both of this function's early exits used to be silent, so a rigger exporting the wrong
        # selection got no file and no reason.
        logger.warning('%s is not drawn with a NURBS curve, so there is no shape to export.',
                       transform_node)
        return False

    flag_to_export = pm.duplicate(transform_node)[0]
    try:
        flag_to_export.setParent(None)
        attr_utils.set_attr_state(flag_to_export, False)

        flag_to_export.rotate.set(0, 0, 0)
        flag_to_export.translate.set(0, 0, 0)
        flag_to_export.scale.set(1, 1, 1)
        if flag_to_export.hasAttr('jointOrient'):
            flag_to_export.jointOrient.set(0, 0, 0)

        flag_data = serialize_flag(flag_to_export)
    finally:
        pm.delete(flag_to_export)

    if not flag_data:
        logger.warning('Nothing on %s could be serialized, so no file was written.',
                       transform_node)
        return False

    fileio.touch_path(flag_path)
    yamlio.write_to_yaml_file({'version': SERIALIZER_VERSION, 'curve_data': flag_data}, flag_path)
    return True


def deserialize_flag(flag_data):
    """
    Rebuild a transform carrying the saved shapes.

    :param dict flag_data: What :func:`serialize_flag` wrote.
    :return: The rebuilt transform, or None when there was nothing to build.
    :rtype: pm.nt.Transform or None
    """

    new_curve = None
    for _shape_name, curve_data in (flag_data or {}).items():
        cvs = _cartesian_points(curve_data['cvs'])
        knots = curve_data['knots']
        degree = curve_data['degree']
        periodic = curve_data['form'] == PERIODIC_FORM

        built = pm.curve(point=cvs, knot=knots, degree=degree, periodic=periodic, append=False)
        if new_curve is None:
            # The first shape *is* the new transform. Building it and then building a second copy
            # to parent in alongside it is what gave every imported flag two identical shapes.
            new_curve = built
            continue
        dag.parent_shape_node(built, new_curve, maintain_offset=True, replace=False)

    if new_curve is None:
        logger.warning('There was no curve data to rebuild a flag from.')
    return new_curve


def _cartesian_points(cvs):
    """
    Control points as three numbers each.

    ``getCVs`` answers three components, so this is not for Maya's benefit - it is for a ``.flag``
    file written by something that stored four, which the comment here used to claim was the normal
    case.

    :param cvs: The stored control points.
    :return: The same points, three components each.
    :rtype: list(tuple)
    """

    points = []
    for cv in (cvs or []):
        if len(cv) == 4:
            x, y, z, w = cv
            points.append((x / w, y / w, z / w) if w else (x, y, z))
        else:
            points.append(tuple(cv[:3]))
    return points


def import_flag(flag_path):
    """
    Read a ``.flag`` file and build the transform it describes.

    :param str flag_path: The file to read.
    :return: The rebuilt transform, or None.
    :rtype: pm.nt.Transform or None
    """

    if not os.path.isfile(flag_path):
        logger.warning('There is no flag file at %s.', flag_path)
        return None

    flag_data = yamlio.read_yaml_file(flag_path) or {}
    return deserialize_flag(flag_data.get('curve_data', {}))
