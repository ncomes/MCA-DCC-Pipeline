"""
Namespaces: making them, finding what is in them, and getting rid of them.

Namespaces are how the pipeline keeps two copies of the same rig apart in one scene, so
every import, every reference and every temporary duplicate goes through here.

What was wrong before:

- **Every listing answered relative to wherever the caller was standing.**
  ``cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True)`` lists the namespaces under
  the *current* one, and answers ``None`` when there are none - so
  ``get_all_namespaces()`` and ``delete_empty_namespaces()`` gave a different answer
  depending on which namespace happened to be current when they were called.
  ``camera_utils`` asks ``'MCAUberCam' in namespace.get_all_namespaces()`` before cleaning
  up its temporary camera namespace, and that was False - so the clean-up was skipped - any
  time the scene was left standing inside a namespace. Both now ask the root explicitly,
  by absolute name.
- **``get_all_namespaces`` edited the caller's list.** Given an ``exclude_list`` it called
  ``exclude_list.extend(DEFAULT_NAMESPACES)`` - on the list the caller passed in. A caller
  that kept its exclusions in a constant and called this twice got a longer constant each
  time.
- **``get_namespace`` could not do what its arguments said.** It appended ``':'`` to the
  node name it was given and then asked whether *that* was an existing namespace, so
  ``check_node=True`` checked a namespace rather than a node, and for any real node name it
  answered ``''``. Every caller in the pipeline passes ``check_node=False`` - which is the
  only setting that worked. The check is gone; the function answers from the name, which is
  all a name can tell you.
- **Its ``if not name.count(':')`` branch could never run**, because the line above had just
  appended a ``':'``.
- **Three functions had a bare ``except:``** - ``get_all_nodes_in_namespace``,
  ``move_node_to_namespace`` and ``purge_namespace``. Between them they swallowed everything
  including ``KeyboardInterrupt``, and ``purge_namespace`` reported every failure as
  "namespace does not exist" whatever had actually gone wrong, which is a poor thing to read
  in a log at the end of a failed publish.
- ``move_node_to_namespace``'s ``except: pass`` meant a rename that failed - a locked node,
  a referenced node, a name clash - looked exactly like one that worked. Callers use it
  through ``map()`` over whole skeletons, so a partial move went unnoticed.
- ``DEFAULT_NAMESPACES`` was written ``["UI", "shared", ':' + "UI", ':' + "shared"]``.
- The module docstring said "Module that contains the mca decorators at a base python
  level".
"""

# python imports

# software specific imports
import pymel.core as pm
import maya.cmds as cmds

# mca imports
from mca.common import log
from mca.mya.utils import naming


logger = log.MCA_LOGGER

#: Maya's own namespaces, as absolute names. Never the pipeline's, and never worth showing
#: a user.
DEFAULT_NAMESPACES = (':UI', ':shared')


def all_namespaces():
    """
    Every namespace in the scene, as an absolute name, whatever namespace is current.

    ``cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True)`` - which is what the
    version this replaces called - answers *relative to the current namespace*, and answers
    ``None`` when the current namespace has no children. So every function built on it
    quietly returned a different answer depending on where the caller happened to be
    standing: ``'MCAUberCam' in get_all_namespaces()`` was False, and
    ``delete_empty_namespaces`` walked only the current subtree, any time a namespace was
    current. Asking the root explicitly, by absolute name, is the same answer every time.

    :return: The namespaces, sorted, deepest last.
    :rtype: list(str)
    """

    found = cmds.namespaceInfo(':', listOnlyNamespaces=True, recurse=True,
                               absoluteName=True) or []
    return sorted(found)


def _absolute(namespace):
    """
    :param str namespace: A namespace, with or without its leading colon.
    :return: The same namespace as an absolute name.
    :rtype: str
    """

    namespace = str(namespace or '').strip()
    if not namespace or namespace == ':':
        return ':'
    namespace = namespace.rstrip(':')
    return namespace if namespace.startswith(':') else ':{}'.format(namespace)


def set_namespace(namespace_name, check_existing=True):
    """
    Make a namespace current, creating it when it is not there.

    :param str namespace_name: The namespace to make current. ``':'`` or '' means the root.
    :param bool check_existing: When the namespace already exists, use the next free
        numbered one instead of joining it. That is what an import wants - two copies of a
        rig must not share a namespace - and what a tool putting things back into a known
        namespace does not, so it passes False.
    :return: The namespace that ended up current.
    :rtype: str
    """

    if namespace_name is not None and not isinstance(namespace_name, str):
        logger.warning('%r is not a name a namespace can have.', namespace_name)
        return cmds.namespaceInfo(currentNamespace=True, absoluteName=True)

    if not namespace_name or namespace_name == ':':
        cmds.namespace(setNamespace=':')
        return ':'

    cmds.namespace(setNamespace=':')
    if check_existing and cmds.namespace(exists=namespace_name):
        namespace_name = naming.make_maya_safe_name(find_unique_namespace(namespace_name))
    if not cmds.namespace(exists=namespace_name):
        cmds.namespace(addNamespace=namespace_name)
    cmds.namespace(setNamespace=namespace_name)
    return cmds.namespaceInfo(currentNamespace=True, absoluteName=True)


def find_unique_namespace(namespace):
    """
    The given namespace if nothing has it, otherwise the same name with a number on the end.

    :param str namespace: The namespace to start from.
    :return: A namespace that does not exist yet.
    :rtype: str
    """

    if not cmds.namespace(exists=namespace):
        return namespace

    namespace = namespace[:-1] if namespace.endswith(':') else namespace
    index = 1
    while True:
        candidate = '{}{:02d}'.format(namespace, index)
        if not cmds.namespace(exists=candidate):
            return candidate
        index += 1


def get_all_namespaces(exclude_list=None):
    """
    Every namespace in the scene, Maya's own left out.

    :param exclude_list: Names to leave out as well as Maya's. Not modified - the version
        this replaces extended the list it was handed.
    :type exclude_list: list(str) or tuple(str) or None
    :return: The namespaces, sorted, spelled the way a caller from the root sees them -
        ``'char'``, ``'char:rig'`` - with no leading colon, because that is what every
        caller in the pipeline compares against.
    :rtype: list(str)
    """

    excluded = set(DEFAULT_NAMESPACES)
    excluded.update(_absolute(one) for one in (exclude_list or ()))
    return [one.lstrip(':') for one in all_namespaces() if one not in excluded]


def get_namespace(name, top_only=True):
    """
    The namespace part of a node name.

    Read from the name itself, which is the only thing a name can tell you. The version this
    replaced offered to check the scene first and got that check wrong, so every caller in
    the pipeline turned it off.

    :param str name: A node name, short or full.
    :param bool top_only: Just the outermost namespace. False gives the whole namespace
        path, so ``'char:rig:arm'`` answers ``'char:rig'`` rather than ``'char'``.
    :return: The namespace, or '' when the name has none.
    :rtype: str
    """

    _, namespace, _ = naming.get_node_name_parts(str(name))
    if not namespace:
        return ''
    return namespace.split(':')[0] if top_only else namespace


def get_all_nodes_in_namespace(namespace_name, recursive=False):
    """
    Every node in a namespace.

    :param namespace_name: The namespace, by name or as a ``pm.Namespace``.
    :param bool recursive: Include the namespaces below it.
    :return: The nodes.
    :rtype: list(pm.PyNode)
    """

    try:
        # Wrapping by name is the existence check and the lookup in one go.
        search_namespace = pm.Namespace(namespace_name)
    except (ValueError, RuntimeError, pm.MayaObjectError):
        logger.warning('Namespace "%s" does not exist.', namespace_name)
        return []

    found = list(search_namespace.ls())
    if recursive:
        for child in search_namespace.listNamespaces(recursive=True):
            found += list(child.ls())
    return found


def delete_empty_namespaces():
    """
    Remove every namespace in the scene that has nothing in it, deepest first.

    Deepest first because a namespace holding only empty namespaces is not empty until they
    are gone.

    :return: The namespaces that were removed, with no leading colon.
    :rtype: list(str)
    """

    removed = []
    namespaces = all_namespaces()
    for namespace in sorted(namespaces, key=lambda one: one.count(':'), reverse=True):
        if namespace in DEFAULT_NAMESPACES:
            continue
        try:
            cmds.namespace(removeNamespace=namespace)
            removed.append(namespace.lstrip(':'))
        except RuntimeError:
            # Not empty. That is the ordinary case, not a problem.
            continue

    if removed:
        logger.debug('Namespaces removed: %s', ', '.join(removed))
    return removed


def move_node_to_namespace(node, namespace_name):
    """
    Rename a node so it sits in a namespace.

    :param node: The node, as a PyNode or a name.
    :param str namespace_name: The namespace to move it into. '' or ``':'`` moves it to the
        root.
    :return: Whether it moved. The version this replaced swallowed every failure with a
        bare ``except: pass``, and callers use this through ``map()`` over whole skeletons,
        so a rename that failed looked exactly like one that worked.
    :rtype: bool
    """

    base_name = naming.get_basename(node)
    if not base_name:
        logger.warning('Could not work out a base name for %r.', node)
        return False

    wanted = base_name if namespace_name in ('', ':', None) else \
        ':{}:{}'.format(str(namespace_name).strip(':'), base_name)
    try:
        if hasattr(node, 'rename'):
            node.rename(wanted)
        else:
            cmds.rename(node, wanted)
    except RuntimeError as error:
        logger.warning('Could not move %s to %s: %s', base_name, namespace_name or ':', error)
        return False
    return True


def purge_namespace(namespace_name):
    """
    Delete a namespace and everything in it, including the namespaces below it.

    :param str namespace_name: The namespace to remove.
    :return: Whether it is gone.
    :rtype: bool
    """

    cmds.namespace(setNamespace=':')
    if not namespace_name or str(namespace_name) == ':':
        logger.warning('The root namespace cannot be purged.')
        return False

    try:
        search_namespace = pm.Namespace(namespace_name)
    except (ValueError, RuntimeError, pm.MayaObjectError):
        logger.warning('Namespace "%s" does not exist.', namespace_name)
        return False

    for child in search_namespace.listNamespaces():
        purge_namespace(child)

    try:
        search_namespace.clean()
        # Unlock first: one locked node in the namespace makes the whole delete fail, and
        # the namespace then refuses to be removed because something is still in it.
        nodes = get_all_nodes_in_namespace(search_namespace, recursive=True)
        for node in nodes:
            if pm.objExists(node):
                pm.lockNode(node, lock=False)
        if nodes:
            pm.delete(nodes)
        pm.namespace(force=True, removeNamespace=search_namespace)
    except RuntimeError as error:
        logger.warning('Could not purge namespace "%s": %s', namespace_name, error)
        return False
    return True
