"""

One attribute driving another through a set driven key, written down so it can be found again.

A set driven key is a curve between two attributes: turn the driver and the driven attributes
follow the shape of the curve. Maya keeps the curve and nothing else, so a rig built out of them is
a rig nobody can read. This node records the relationship - which attribute drives, which
attributes are driven, and what they are set to at each end - so a tool can show it and a rebuild
can make it again.

What was wrong before:

- **It recorded the driving *node* and threw away which attribute it was.** ``driver`` is set to
  ``drive_attr.nodeName()``, and ``drive_attr`` is an attribute: so a component driven by
  ``f_jaw.openClose`` recorded ``f_jaw``, and nothing in the scene says which of that control's
  attributes the curve hangs off. That is the one thing the node exists to remember. It records the
  attribute.
- **The default driver values are ``(0, 0)``** - both ends of the relationship at the same driver
  value. The second key is then set on top of the first and the curve is flat, so a component built
  on the defaults does nothing at all and says nothing about it. Both ends have to be given now.
- **``driven_attrs`` defaults to None and is then indexed**, which is a ``TypeError`` rather than a
  word about the argument that is missing.
- **The node was renamed from its own current name rather than from its class**:
  ``node.pynode.rename('{0}_{1}_{2}'.format(node.pynode, side, region))``. The first one in a scene
  comes out right; the second is ``SingleSDKComponent1_left_jaw``, because Maya had uniquified the
  name the format string read.
- **The compound attributes were built by hand with ``addAttr(numberOfChildren=…)``**, which is a
  Maya error when the dictionary is empty, and each value was written as a *string*, so the numbers
  the node records come back as text. ``attr_utils.set_compound_attribute_groups`` does the whole
  block, keeps the types, and carries the channel-box workaround every other block in the pipeline
  has.
- **The curve it recorded was whatever was first on the driven attribute's connections.** A driven
  attribute with anything else wired to it - a constraint, a blend node, which is the normal case
  on a rig - put that node in ``animCurves`` instead. It asks for animation curves.
- ``ori_driven_value`` held the *driver*'s value, which the line below it puts back. The values
  were silently rounded to three places on the way in, with nothing saying so.
"""

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.modifiers import ma_decorators
from mca.mya.rigging.frag import frag_base
from mca.mya.utils import attr_utils
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: The two ends of the relationship, in the order the keys are set.
START = 'start'
END = 'end'
ENDS = (START, END)

#: What the component keeps its pieces on. One compound per end, each child holding the value that
#: end sets one driven attribute to.
DRIVEN_ATTRS_COMPOUND = 'driven{0}Attrs'
DRIVER_ATTR = 'driver'
DRIVEN_ATTR = 'driven'
ANIM_CURVES_ATTR = 'animCurves'

#: The attribute the driven object carries, pointing back at this component.
DRIVEN_PARENT_ATTR = 'SDK_Parent'

#: How many decimal places a driven value is stored to. The version before rounded silently.
VALUE_PLACES = 3


class SingleSDKComponent(frag_base.FRAGNode):
    """
    One driver attribute, one driven object, and the values its attributes take at each end.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, drive_attr, driven_obj, side, region, driven_attrs,
               drive_attr_values, **kwargs):
        """
        Set the keys and record what was set.

        :param FRAGNode frag_parent: The component this belongs to.
        :param pm.Attribute drive_attr: The attribute that drives.
        :param pm.nt.DependNode driven_obj: The object whose attributes follow it.
        :param str side: Which side of the body it is on.
        :param str region: What part of the body it is.
        :param dict driven_attrs: ``{'start': {attribute name: value}, 'end': {…}}`` - what the
            driven attributes are set to at each end of the driver's travel. Required; it used to
            default to None and then be indexed.
        :param drive_attr_values: The driver's value at each end, start first. Required; it used to
            default to ``(0, 0)``, which sets both keys at the same place and leaves the curve flat.
        :param dict kwargs: Taken and ignored, so a rebuild can hand over a component's whole
            argument list without having to know which of it this component uses.
        :return: The component, or None when the two ends are the same driver value or there is
            nothing to drive.
        :rtype: SingleSDKComponent or None
        """

        if not driven_attrs or not any(driven_attrs.get(end) for end in ENDS):
            logger.warning('No driven attributes were given, so no set driven key was built for '
                           '%s.', drive_attr)
            return None
        if drive_attr_values[0] == drive_attr_values[1]:
            logger.warning('%s drives from %s to %s, which is the same value at both ends - the '
                           'second key would land on the first and the curve would be flat.',
                           drive_attr, drive_attr_values[0], drive_attr_values[1])
            return None

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = frag_base.FRAGNode.create(frag_parent, SingleSDKComponent.__name__,
                                         SingleSDKComponent.VERSION)
        # From the class name, not from the node's own - which Maya may already have uniquified, so
        # the second component in a scene came out as SingleSDKComponent1_<side>_<region>.
        node.pynode.rename('{0}_{1}_{2}'.format(SingleSDKComponent.__name__, side, region))
        node.side = side
        node.region = region

        anim_curves = _set_driven_keys(drive_attr, driven_obj, driven_attrs, drive_attr_values)

        for end in ENDS:
            attr_utils.set_compound_attribute_groups(
                node.pynode, DRIVEN_ATTRS_COMPOUND.format(end.capitalize()),
                {attr_name: round(value, VALUE_PLACES)
                 for attr_name, value in (driven_attrs.get(end) or {}).items()})

        # The attribute, not just the node it is on. The version before recorded the node, which
        # leaves nothing in the scene saying which of its attributes the curve hangs off.
        attr_utils.set_attribute(node.pynode, {DRIVER_ATTR: str(drive_attr).split(':')[-1]})
        node.connect_node(driven_obj, DRIVEN_ATTR, parent_attr=DRIVEN_PARENT_ATTR)
        if anim_curves:
            node.connect_nodes(anim_curves, ANIM_CURVES_ATTR, frag_base.FRAG_PARENT_ATTR)

        attr_utils.set_compound_attribute_groups(
            node.pynode, frag_base.BUILD_KWARGS_ATTR,
            {'drive_attr_values': list(drive_attr_values)})

        return node

    @property
    def driver(self):
        """
        :return: The attribute that drives, as ``<node>.<attribute>``. The version before recorded
            only the node.
        :rtype: str
        """

        return self.pynode.attr(DRIVER_ATTR).get()

    @property
    def driven(self):
        """
        :return: The object whose attributes follow the driver.
        :rtype: pm.nt.DependNode
        """

        return self.pynode.attr(DRIVEN_ATTR).get()

    @property
    def anim_curves(self):
        """
        :return: The curves the relationship is made of.
        :rtype: list(pm.nt.AnimCurve)
        """

        if not self.pynode.hasAttr(ANIM_CURVES_ATTR):
            return []
        return self.pynode.attr(ANIM_CURVES_ATTR).get() or []

    def get_driven_values(self, end):
        """
        What the driven attributes are set to at one end of the driver's travel.

        :param str end: :data:`START` or :data:`END`.
        :return: ``{attribute name: value}``, empty when the component records nothing for that end.
        :rtype: dict
        """

        compound_name = DRIVEN_ATTRS_COMPOUND.format(end.capitalize())
        if not self.pynode.hasAttr(compound_name):
            logger.warning('%s records nothing for the %r end.', self.pynode, end)
            return {}

        prefix = '{0}_'.format(compound_name)
        values = {}
        for child in self.pynode.attr(compound_name).getChildren():
            child_name = child.attrName()
            # The hidden bool child every compound carries is deliberately not named with the
            # compound's prefix, which is what makes it skippable here.
            if child_name.startswith(prefix):
                values[child_name[len(prefix):]] = child.get()
        return values


def _set_driven_keys(drive_attr, driven_obj, driven_attrs, drive_attr_values):
    """
    Set a key on each driven attribute at each end of the driver's travel.

    The driver is put back where it was afterwards, so building the relationship does not leave the
    rig posed.

    :param pm.Attribute drive_attr: The attribute that drives.
    :param pm.nt.DependNode driven_obj: The object whose attributes follow it.
    :param dict driven_attrs: ``{'start': {attribute name: value}, 'end': {…}}``.
    :param drive_attr_values: The driver's value at each end, start first.
    :return: The curves that were made, each once.
    :rtype: list(pm.nt.AnimCurve)
    """

    original_value = drive_attr.get()
    anim_curves = []
    try:
        for index, end in enumerate(ENDS):
            drive_attr.set(drive_attr_values[index])
            for attr_name, value in (driven_attrs.get(end) or {}).items():
                driven_attr = driven_obj.attr(attr_name)
                driven_attr.set(round(value, VALUE_PLACES))
                pm.setDrivenKeyframe(driven_attr, currentDriver=drive_attr)
                # The curves, not whatever happens to be first on the attribute's connections - a
                # driven attribute on a rig usually has a constraint or a blend node on it too.
                for curve in driven_attr.listConnections(source=True, destination=False,
                                                         type='animCurve'):
                    if curve not in anim_curves:
                        anim_curves.append(curve)
    finally:
        drive_attr.set(original_value)
    return anim_curves
