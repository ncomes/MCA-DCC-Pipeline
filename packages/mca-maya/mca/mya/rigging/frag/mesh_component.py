"""
The node that records which of a character's meshes is which.

A rig is built over a skeleton, but a character is a pile of meshes - the body that gets skinned,
the head that carries the blendshapes, the source mesh those shapes were sculpted from, eye cards,
teeth. Tools downstream need to ask for one of them by name rather than by guessing at a naming
convention, so this node holds one compound attribute per *category* (``skin_mesh``,
``blendshape_mesh``, ``source_mesh``, whatever the caller passes) whose children are message
attributes wired to the meshes. A child can hold one mesh or a list of them, which is how "the left
eye's cards" fits beside "the head".

It hangs under the :class:`~skeletal_mesh.SkeletalMesh` node, and on create it moves anything in
the blendshape category under the rig's blendshape group, because that group is what gets hidden
and excluded from the export.

The shape the categories go in is the shape they come back out in:
:meth:`MeshComponent.get_connections_as_dict` answers the same ``{category: {name: mesh}}``
dictionary :meth:`MeshComponent.create` takes.

What was wrong before:

- **``get_connections_as_dict`` has never once answered correctly.** It builds two lists - the
  meshes wired to a category, and the category's child attributes - and pairs them **by position**,
  with the attribute list offset by one. They do not line up, for three separate reasons. The
  offset of one lands on the hidden bool child that ``set_compound_attribute_groups`` adds to every
  compound as a channel-box workaround, so the first mesh of every category came back under the key
  ``_hidden``. The mesh list is de-duplicated and skips children with nothing on the end of them,
  while the attribute list skips nothing, so one unconnected child shifts everything after it. And
  a child holding a *list* of meshes contributes one entry to the attribute list and several to the
  mesh list. Checked in a real Maya: three meshes under ``skin_mesh`` came back as ``{'_hidden':
  mesh_a, 'head_mesh': mesh_b, 'mouth_mesh': mesh_c}`` - every mesh under the wrong name, and the
  last attribute dropped off the end. It is built from the attribute side, by name, now, which
  cannot drift. This is the same fault, with the same fix, as ``animated_curves`` pairing curves
  with channels by position.
- **``get_mesh`` and ``reconnect_mesh`` raised on a node that does not have the category**, from
  inside the guard that is there to stop exactly that: ``pm.hasAttr(self.pynode.attr(category),
  ...)`` evaluates ``self.pynode.attr(category)`` first, which is a ``MayaAttributeError`` when the
  category is not there. ``get_mesh_list``, the same function with a different answer, checks for
  the compound first - so two methods beside each other disagreed about whether a missing category
  is an error. All three go through one lookup that checks both.
- **``reconnect_mesh`` only half reconnected a mesh to a category that holds a list.** It connects
  to the array attribute itself rather than to an element of it. Maya allows that: checked in a
  real Maya, the mesh then appears in the attribute's connections but under **no index** - the
  array's indices are unchanged - so anything walking the list by index does not see it, and
  rewriting the category drops it. It takes the next free element now.
- ``get_mesh`` and ``get_mesh_list`` are the same lookup with two different answers, and each gave
  the other's answer for the wrong kind of child: ``get_mesh`` on a list-holding child answered a
  list, and ``get_mesh_list`` on a single-mesh child answered a one-item list. They share a body,
  and each says what it does with the other kind.
- ``get_mesh_list`` promised a list and answered None when it found nothing, which is the shape
  that makes a caller write ``or []``. Both lookups answer None for "no such thing" and the list
  lookup answers an empty list for "nothing wired to it", which are different questions.
- ``create`` asked its parent for the blendshape group without checking that the parent is a thing
  with one, and the category name was a bare string in the one place that cares about it.
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

#: The category whose meshes are moved under the rig's blendshape group as the node is built. These
#: meshes drive a face and are never exported, which is what that group is for. It is the same
#: string as ``skeletal_mesh.BLENDSHAPE_MESH_REGION``, and for the same set of meshes - that one is
#: the name the *mesh markup* calls them, this one the name a category is stored under.
BLENDSHAPE_CATEGORY = 'blendshape_mesh'


class MeshComponent(frag_base.FRAGNode):
    """
    One compound attribute per mesh category, each child wired to a mesh or a list of them.
    """

    VERSION = 1

    @staticmethod
    @ma_decorators.keep_namespace_decorator
    def create(frag_parent, meshes_dict):
        """
        Build the node and wire up every mesh in the dictionary.

        :param SkeletalMesh frag_parent: The skeletal mesh node this hangs under.
        :param dict meshes_dict: ``{category: {name: mesh or list of meshes}}``. Exactly what
            :meth:`get_connections_as_dict` answers, so a node can be rebuilt from one that exists.
        :return: The component.
        :rtype: MeshComponent
        """

        root_namespace = frag_parent.pynode.namespace().split(':')[0]
        namespace.set_namespace(root_namespace, check_existing=False)

        node = frag_base.FRAGNode.create(frag_parent=frag_parent,
                                         frag_type=MeshComponent.__name__,
                                         version=MeshComponent.VERSION)
        node.set_categories(meshes_dict)
        node.move_blendshape_meshes()
        return node

    def set_categories(self, meshes_dict):
        """
        Write a whole dictionary of categories onto the node, replacing any that are already there.

        :param dict meshes_dict: ``{category: {name: mesh or list of meshes}}``.
        """

        for category, meshes in meshes_dict.items():
            attr_utils.set_compound_attribute_groups(self.pynode, category, meshes)

    def move_blendshape_meshes(self):
        """
        Put the meshes in the blendshape category under the rig's blendshape group.

        That group is hidden and left out of the export, so the meshes that drive a face belong in
        it rather than beside the ones that get skinned.

        :return: The meshes that were moved.
        :rtype: list(pm.nt.Transform)
        """

        meshes = self.get_all_category_meshes(BLENDSHAPE_CATEGORY)
        if not meshes:
            return []

        frag_parent = self.get_frag_parent()
        # The version before called this on whatever its parent was. Only a SkeletalMesh has one.
        if frag_parent is None or not hasattr(frag_parent, 'get_grp_blendshapes'):
            logger.warning('%s is under %s, which has no blendshape group, so its %s meshes are '
                           'left where they are.', self.pynode, frag_parent, BLENDSHAPE_CATEGORY)
            return []

        blendshape_grp = frag_parent.get_grp_blendshapes()
        if not blendshape_grp:
            # A rig built with no blendshapes has this group deleted, so the attribute can be there
            # with nothing on the end of it.
            logger.warning('%s has no blendshape group in the scene, so %s\'s %s meshes are left '
                           'where they are.', frag_parent.pynode, self.pynode, BLENDSHAPE_CATEGORY)
            return []

        pm.parent(meshes, blendshape_grp)
        return meshes

    # ----------------------------------------------------------------------------------- #
    # the categories
    # ----------------------------------------------------------------------------------- #
    def get_all_categories(self):
        """
        :return: The name of every category on this node.
        :rtype: list(str)
        """

        return attr_utils.get_compound_attr_names(self.pynode)

    def get_all_category_meshes(self, category):
        """
        :param str category: The category to look in.
        :return: Every mesh wired to any of that category's children, each once. None when the node
            has no such category.
        :rtype: list(pm.nt.Transform) or None
        """

        return attr_utils.get_compound_attr_connections(self.pynode, compound_attr_name=category)

    def get_all_attrs_from_category(self, category):
        """
        :param str category: The category to look in.
        :return: That category's child attributes, including the hidden bool one that
            ``set_compound_attribute_groups`` adds to every compound. None when the node has no such
            category.
        :rtype: list(pm.Attribute) or None
        """

        return attr_utils.get_all_attributes_from_compound_attr(self.pynode,
                                                                compound_attr_name=category)

    def remove_category(self, category):
        """
        Unwire a category and take the attribute off the node.

        :param str category: The category to remove.
        :return: Whether it is gone.
        :rtype: bool
        """

        return attr_utils.disconnect_and_delete_compound_attr(self.pynode, category)

    def get_connections_as_dict(self):
        """
        Every category on this node, in the shape :meth:`create` takes one.

        This is the round trip: hand what this answers back to ``create`` or
        :meth:`set_categories` and the same node comes out. A child holding a list of meshes answers
        a list; one holding a single mesh answers the mesh. A child with nothing wired to it is left
        out, so the dictionary describes what is there rather than what the attributes allow for.

        :return: ``{category: {name: mesh or list of meshes}}``.
        :rtype: dict
        """

        found = {}
        for category in self.get_all_categories():
            prefix = '{0}_'.format(category)
            for child in self.pynode.attr(category).getChildren():
                child_name = child.attrName()
                # The hidden bool child is deliberately not named '<category>_something', which is
                # what makes it skippable here - and what the version before tripped over by
                # counting positions instead of reading names.
                if not child_name.startswith(prefix):
                    continue
                meshes = child.listConnections()
                if not meshes:
                    continue
                found.setdefault(category, {})
                found[category][child_name[len(prefix):]] = (meshes if child.isMulti()
                                                             else meshes[0])
        return found

    # ----------------------------------------------------------------------------------- #
    # one mesh at a time
    # ----------------------------------------------------------------------------------- #
    def _child_attribute(self, attr_name, compound_attr_name):
        """
        One category's child attribute, by the short name it was stored under.

        :param str attr_name: The name within the category, as it went into ``create``.
        :param str compound_attr_name: The category.
        :return: The attribute, or None when either the category or the child is not there. The
            three methods that used to do this each did it slightly differently, and two of them
            raised rather than answering when the category was missing.
        :rtype: pm.Attribute or None
        """

        if not self.pynode.hasAttr(compound_attr_name):
            logger.warning('%s has no %r category on it.', self.pynode, compound_attr_name)
            return None

        child_name = '{0}_{1}'.format(compound_attr_name, attr_name)
        if not self.pynode.hasAttr(child_name):
            logger.warning('%s\'s %r category has nothing called %r in it.', self.pynode,
                           compound_attr_name, attr_name)
            return None
        return self.pynode.attr(child_name)

    def get_mesh(self, attr_name, compound_attr_name):
        """
        One mesh out of a category.

        :param str attr_name: The name within the category.
        :param str compound_attr_name: The category.
        :return: The mesh, None when the category or the name is not there, and None when nothing is
            wired to it. A name holding a *list* of meshes answers the first of them - ask
            :meth:`get_mesh_list` for all of them.
        :rtype: pm.nt.Transform or None
        """

        child = self._child_attribute(attr_name, compound_attr_name)
        if child is None:
            return None
        meshes = child.listConnections()
        return meshes[0] if meshes else None

    def get_mesh_list(self, attr_name, compound_attr_name):
        """
        Every mesh under one name in a category.

        :param str attr_name: The name within the category.
        :param str compound_attr_name: The category.
        :return: The meshes - an empty list when nothing is wired to the name, and None when the
            category or the name is not there at all, which is a different question. A name holding
            a single mesh answers a list of one.
        :rtype: list(pm.nt.Transform) or None
        """

        child = self._child_attribute(attr_name, compound_attr_name)
        if child is None:
            return None
        return child.listConnections()

    def reconnect_mesh(self, mesh, attr_name, compound_attr_name):
        """
        Wire a mesh back to a name in a category it has come off.

        :param pm.nt.Transform mesh: The mesh.
        :param str attr_name: The name within the category.
        :param str compound_attr_name: The category.
        :return: Whether it was wired up.
        :rtype: bool
        """

        child = self._child_attribute(attr_name, compound_attr_name)
        if child is None:
            return False

        if child.isMulti():
            # The next free element, not the array attribute itself. Connecting to the array is
            # something Maya allows and the version before did: the mesh then shows up in the
            # attribute's connections but sits at no index, so anything walking the list by index
            # misses it and rewriting the category throws it away.
            indices = child.getArrayIndices()
            target = child[max(indices) + 1 if indices else 0]
        else:
            target = child

        mesh.message >> target
        return True
