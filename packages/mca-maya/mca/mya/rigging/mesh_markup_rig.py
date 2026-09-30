"""
Mesh markup: telling a rig builder what each mesh in a character is for.

A character arrives as a bag of meshes - a head, two eyes, teeth, lashes, a body, and a dozen
blend shape targets - and a builder has to know which is which. Names do not answer that across
two characters made by two people, so each mesh carries one string attribute, ``mcaMeshMarkup``,
holding a JSON dictionary: what kind of mesh it is, what category it belongs to, which side and
region it is on, what it was made from.

:class:`MeshMarkup` is one mesh's entry, as properties. :class:`RigMeshMarkup` gathers every
tagged mesh in a namespace and answers the questions a builder actually asks - every skin mesh,
every mesh in the head region, the blend shape meshes by region.

What was wrong before:

- **Asking an untagged mesh anything raised.** Every read goes through ``get_dict``, which reads
  ``self.mesh.attr(MCA_MESH_MARKUP)`` - and a mesh without the attribute has no such plug, so
  ``AttributeError``. There is no way to ask "is this mesh tagged?" other than checking the
  attribute by hand first, which is a thing a caller has to know to do. An untagged mesh answers
  an empty dictionary now, and :attr:`MeshMarkup.is_marked_up` asks the question directly.
- **Markup that was not valid JSON took the whole build down.** ``json.loads`` on a truncated or
  hand-edited string raises, from inside a property read, half way through a rig build. It is
  caught and reported against the mesh it came from now.
- **``set_dict`` could not clear the markup.** ``if mesh_dict:`` - so writing an empty dictionary
  did nothing at all, and the mesh kept whatever it had.
- **``get_mesh_markups()`` with no argument wrapped the wrappers.** Its default is
  ``self.mesh_list``, which is already a list of :class:`MeshMarkup`, so calling it that way built
  ``MeshMarkup(MeshMarkup(...))`` - every read on which would then go looking for a Maya attribute
  on a Python object. Nothing called it that way; the default is gone.
- **Two hundred lines of the module were the same ten lines twenty times over.** Each of the ten
  entries had a getter and a setter that did nothing but name the entry. They are built from
  :data:`MARKUP_ENTRIES` now, which is also the only description of the schema there has ever
  been.
- ``get_region_dict`` had no callers and ``get_blendshape_region_dict`` was the same function with
  one ``if`` in it. One function with a ``category`` argument now.
- ``RigMeshMarkup.create`` called ``hasAttr`` on the result of ``getParent()``, which is ``None``
  for a shape sitting at the scene root.
"""

# python imports
import json

# software specific imports
import pymel.core as pm

# mca imports
from mca.common import log
from mca.mya.utils import namespace


logger = log.MCA_LOGGER

#: The string attribute the markup lives in, as JSON.
MCA_MESH_MARKUP = 'mcaMeshMarkup'

#: The face pipeline's primary mesh. Everything else on a head is driven from it, so lookups put
#: it first.
HEAD_MESH_TYPE = 'head_mesh'

#: The category a blend shape target is filed under.
BLENDSHAPE_CATEGORY = 'blendshape_mesh'

#: Every entry the markup can hold, and what it is for. This table is the schema: the properties
#: on :class:`MeshMarkup` are built from it, so adding an entry here is all that adding an entry
#: takes.
MARKUP_ENTRIES = (
    ('type_name', 'What this mesh is, within its region. ``head_mesh``, ``left_eye_mesh``.'),
    ('category', 'What kind of mesh it is. ``skin_mesh``, ``blendshape_mesh``.'),
    ('side', 'Which side of the character it is on.'),
    ('region', 'The region it belongs to. ``head``, ``left_eye``.'),
    ('mirror_type', 'How it mirrors onto the other side of the character.'),
    ('race', 'The character race the mesh was built for.'),
    ('skeleton', 'The skeleton it is built against.'),
    ('skin_type', 'How the mesh is bound - which of the skinning setups it expects.'),
    ('source_mesh', 'The mesh this one was made from, for a target or a duplicate.'),
    ('joint_connection_type', 'How its joints are attached to it, when they are.'),
)


def _entry_property(entry, doc):
    """
    Build one property that reads and writes a single entry of the markup dictionary.

    :param str entry: The key in the dictionary.
    :param str doc: What that key is for, which becomes the property's docstring.
    :return: The property.
    :rtype: property
    """

    def getter(self):
        return self.get_mesh_entry(entry)

    def setter(self, value):
        self.update_entry(entry, value)

    return property(getter, setter, doc='{0}\n\n    Stored under ``{1}``.'.format(doc, entry))


class MeshMarkup(object):
    """
    One mesh's markup, as properties.

    Every write rewrites the whole JSON string, because that is what a string attribute is. Reads
    never change the scene, and reading a mesh that has no markup on it answers None rather than
    raising.
    """

    def __init__(self, mesh):
        """
        :param pm.nt.Transform mesh: The mesh transform the markup is on, or is about to be on.
        """

        self._mesh = mesh

    def __repr__(self):
        return '{0}({1})'.format(type(self).__name__, self._mesh)

    @classmethod
    def create(cls, mesh, type_name, category, side, **kwargs):
        """
        Tag a mesh, replacing any markup it already had.

        :param pm.nt.Transform mesh: The mesh to tag.
        :param str type_name: What this mesh is, within its region.
        :param str category: What kind of mesh it is.
        :param str side: Which side it is on.
        :param dict kwargs: Any other entry from :data:`MARKUP_ENTRIES`.
        :return: The markup.
        :rtype: MeshMarkup
        """

        if not mesh.hasAttr(MCA_MESH_MARKUP):
            mesh.addAttr(MCA_MESH_MARKUP, dt='string')

        mesh_dict = {'type_name': type_name, 'category': category, 'side': side}
        mesh_dict.update(kwargs)

        markup = cls(mesh)
        # Replaces rather than merges: the old version cleared the attribute first, which only
        # worked because set_dict then wrote over it.
        markup.set_dict(mesh_dict)
        return markup

    @property
    def mesh(self):
        """
        :return: The mesh transform.
        :rtype: pm.nt.Transform
        """

        return self._mesh

    @property
    def is_marked_up(self):
        """
        :return: Whether the mesh carries the markup attribute at all.
        :rtype: bool
        """

        return bool(self._mesh) and self._mesh.hasAttr(MCA_MESH_MARKUP)

    # ----------------------------------------------------------------------------------- #
    # the dictionary behind the properties
    # ----------------------------------------------------------------------------------- #
    def get_dict(self):
        """
        The whole markup dictionary.

        An untagged mesh answers an empty dictionary rather than raising, and so does one whose
        markup is not valid JSON - which is reported, because it means a tagged mesh is about to
        be treated as an untagged one.

        :return: The markup.
        :rtype: dict
        """

        if not self.is_marked_up:
            return {}

        raw = self._mesh.attr(MCA_MESH_MARKUP).get() or '{}'
        try:
            return json.loads(raw)
        except ValueError:
            logger.warning('The markup on %s is not valid JSON, so it reads as untagged: %r',
                           self._mesh, raw)
            return {}

    def set_dict(self, mesh_dict):
        """
        Replace the whole markup dictionary.

        :param dict mesh_dict: The markup. An empty one clears it, which the version before could
            not do.
        :return: Whether it was written - a mesh with no markup attribute cannot take one.
        :rtype: bool
        """

        if not self.is_marked_up:
            logger.warning('%s has no %s attribute, so nothing was written to it. Use create().',
                           self._mesh, MCA_MESH_MARKUP)
            return False

        self._mesh.attr(MCA_MESH_MARKUP).set(json.dumps(mesh_dict or {}))
        return True

    def get_mesh_entry(self, entry):
        """
        :param str entry: The key to read.
        :return: Its value, or None when the mesh does not carry it.
        :rtype: str or None
        """

        return self.get_dict().get(entry, None)

    def update_entry(self, entry, value):
        """
        Set one key, leaving the rest of the markup alone.

        :param str entry: The key to write.
        :param value: What to write.
        :return: Whether it was written.
        :rtype: bool
        """

        mesh_dict = self.get_dict()
        mesh_dict[entry] = value
        return self.set_dict(mesh_dict)

    def remove_markup(self):
        """
        Take the markup attribute off the mesh entirely.

        :return: Whether there was one to take off.
        :rtype: bool
        """

        if not self.is_marked_up:
            return False
        self._mesh.deleteAttr(MCA_MESH_MARKUP)
        return True

    def clear_markup(self):
        """
        Empty the markup but leave the attribute, so the mesh is still recognisably one of ours.

        :return: Whether there was one to clear.
        :rtype: bool
        """

        if not self.is_marked_up:
            return False
        self._mesh.attr(MCA_MESH_MARKUP).set('')
        return True


# The ten entry properties, built from the table rather than written out twenty times.
for _entry_name, _entry_doc in MARKUP_ENTRIES:
    setattr(MeshMarkup, _entry_name, _entry_property(_entry_name, _entry_doc))
del _entry_name, _entry_doc


class RigMeshMarkup(object):
    """
    Every tagged mesh in a rig, and the lookups a builder asks of them.

    Holds no Maya state of its own - it is a list of :class:`MeshMarkup` and some ways of
    filtering it.
    """

    def __init__(self, mesh_list):
        """
        :param list mesh_list: Mesh transforms carrying the markup attribute.
        """

        self.mesh_list = self.get_mesh_markups(mesh_list) if mesh_list else []

    def __repr__(self):
        return '{0}({1} meshes)'.format(type(self).__name__, len(self.mesh_list))

    @classmethod
    def create(cls, ns=''):
        """
        Every tagged mesh in a namespace.

        :param str ns: The namespace to look in. Empty means the root.
        :return: The markup for all of them.
        :rtype: RigMeshMarkup
        """

        mesh_shapes = pm.ls(namespace.get_all_nodes_in_namespace(ns), geometry=True)

        mesh_list = []
        for shape in mesh_shapes:
            transform = shape.getParent()
            # A shape can sit at the scene root with no transform above it, and the old version
            # called hasAttr on that None.
            if transform is None or not transform.hasAttr(MCA_MESH_MARKUP):
                continue
            if transform not in mesh_list:
                mesh_list.append(transform)
        return cls(mesh_list)

    @staticmethod
    def get_mesh_markups(mesh_list):
        """
        Wrap a list of mesh transforms.

        :param list mesh_list: The meshes. This used to default to ``self.mesh_list``, which is
            already wrapped, so calling it with no argument wrapped the wrappers.
        :return: The markup for each.
        :rtype: list(MeshMarkup)
        """

        return [MeshMarkup(mesh) for mesh in mesh_list]

    # ----------------------------------------------------------------------------------- #
    # lookups
    # ----------------------------------------------------------------------------------- #
    def get_dict(self):
        """
        :return: ``{category: {type_name: mesh}}``.
        :rtype: dict
        """

        mesh_dict = {}
        for markup in self.mesh_list:
            mesh_dict.setdefault(markup.category, {})[markup.type_name] = markup.mesh
        return mesh_dict

    def get_region_dict(self, category=None):
        """
        :param str category: Only include meshes of this category. None includes all of them -
            which is what the two functions this replaces were, one with an ``if`` in it.
        :return: ``{region: {type_name: category}}``.
        :rtype: dict
        """

        mesh_dict = {}
        for markup in self.mesh_list:
            if category is not None and markup.category != category:
                continue
            mesh_dict.setdefault(markup.region, {})[markup.type_name] = markup.category
        return mesh_dict

    def get_mesh_list_in_region(self, mesh_region, as_string=False):
        """
        :param str mesh_region: The region to look for.
        :param bool as_string: Answer with names rather than nodes.
        :return: The meshes in that region.
        :rtype: list
        """

        meshes = [markup.mesh for markup in self.mesh_list if markup.region == mesh_region]
        return [str(mesh) for mesh in meshes] if as_string else meshes

    def get_mesh_dict_list_in_region(self, mesh_region, as_string=False):
        """
        The meshes in a region, against their markup.

        :param str mesh_region: The region to look for.
        :param bool as_string: Answer with a list of names instead of the dictionary. The shape
            of the answer changes with the flag, which is how the one caller uses it.
        :return: ``{mesh: markup}``, or a list of names.
        :rtype: dict or list
        """

        meshes = {markup.mesh: markup for markup in self.mesh_list
                  if markup.region == mesh_region}
        return [str(mesh) for mesh in meshes] if as_string else meshes

    def get_mesh_list_in_category(self, category, as_string=False):
        """
        The meshes of one category, head mesh first.

        The face tools treat the first mesh as the primary one that the others - eyes, teeth,
        lashes - are driven from, so the head is held back and put at the front.

        :param str category: The category to look for.
        :param bool as_string: Answer with names rather than nodes.
        :return: The meshes in that category.
        :rtype: list
        """

        meshes = []
        head_mesh = None
        for markup in self.mesh_list:
            if markup.category != category:
                continue
            if markup.type_name == HEAD_MESH_TYPE:
                head_mesh = markup.mesh
            else:
                meshes.append(markup.mesh)

        if head_mesh is not None:
            meshes.insert(0, head_mesh)
        return [str(mesh) for mesh in meshes] if as_string else meshes
