"""
Node names: taking them apart, and making a string into one Maya will accept.

Maya node names are three things joined together - a DAG path, a namespace and a base name
- and most of the pipeline's bugs with names come from a function that handles one of the
three and is handed all three. These functions say which part they answer for.

What was wrong before:

- **``remove_illegal_characters`` returned an empty string** for any name with a leading or
  trailing space. It recursed to strip the space and then threw the recursion's result away,
  falling through to a bare ``return ''`` at the end of the function. Since
  ``make_maya_safe_name`` is built on it, ``' head_geo'`` became ``''``, and the caller
  named a node after nothing.
- **It also removed no illegal characters.** Despite the name and the docstring - "converts
  a given string to match Maya's naming conventions" - it only ever handled the space. A
  name with a dash, a dot or a slash in it went through untouched and Maya rejected it, or
  silently renamed it.
- **``get_node_name_parts`` joined the DAG path with nothing at all.** ``'|'.join`` was
  written ``''.join``, so ``'grpA|grpB|pSphere1'`` came back with a long prefix of
  ``'grpAgrpB'`` - which is not a path to anything. Its own docstring showed the right
  answer directly above the line that got it wrong.
- The module docstring said "Parameter data for working with the facial rigs", which it has
  never been.
"""

# python imports
import re

# software specific imports
import maya.cmds as cmds


#: Everything Maya will not take in a node name. Letters, digits and the underscore are
#: what is left; the DAG separator and the namespace separator are handled separately,
#: because a function that is given a whole path should say so rather than mangling it.
ILLEGAL_CHARACTERS = re.compile(r'[^A-Za-z0-9_]+')

#: Trailing digits, kept apart from the rest so a name can be incremented without losing
#: the padding somebody chose - ``arm_01`` goes to ``arm_02``, not ``arm_2``.
TRAILING_DIGITS = re.compile(r'^(.*?)(\d+)$')


def get_basename(node, remove_namespace=True, remove_attribute=False):
    """
    The last part of a node name: ``a|b|c`` gives ``c``.

    :param node: A name, a PyNode, or a FRAG node wrapper.
    :param bool remove_namespace: Drop the namespace as well, so ``rig:arm`` gives ``arm``.
    :param bool remove_attribute: Drop an attribute, so ``arm.tx`` gives ``arm``.
    :return: The base name.
    :rtype: str
    """

    # Strings, raw PyNodes and FRAG wrappers all arrive here. A FRAG wrapper does not have
    # longName() itself - its Maya node is on .pynode - so unwrap rather than failing with
    # AttributeError, which is what callers used to hit.
    if isinstance(node, str):
        node_name = node
    elif hasattr(node, 'longName'):
        node_name = node.longName()
    elif hasattr(node, 'pynode'):
        node_name = node.pynode.longName()
    else:
        node_name = str(node)

    base_name = node_name.split('|')[-1]
    if remove_attribute:
        base_name = base_name.split('.')[0]
    if remove_namespace:
        base_name = base_name.split(':')[-1]
    return base_name


def get_node_name_parts(node_name):
    """
    Split a node name into its DAG path, its namespace and its base name.

    ``'a:a:grpA|a:a:grpB|a:b:pSphere1'`` gives
    ``('a:a:grpA|a:a:grpB', 'a:b', 'pSphere1')``.

    :param str node_name: The name to split.
    :return: The long prefix, the namespace, and the base name. Each is '' when the name
        does not have that part.
    :rtype: tuple(str, str, str)
    """

    node_name = str(node_name)
    if '|' in node_name:
        parts = node_name.split('|')
        # '|'.join, not ''.join. The version this replaces used the latter, so the prefix
        # it handed back was the path with its separators deleted.
        long_prefix = '|'.join(parts[:-1])
        short_name = parts[-1]
    else:
        long_prefix = ''
        short_name = node_name

    if ':' in short_name:
        namespace_parts = short_name.split(':')
        namespace = ':'.join(namespace_parts[:-1])
        base_name = namespace_parts[-1]
    else:
        namespace = ''
        base_name = short_name

    return long_prefix, namespace, base_name


def remove_illegal_characters(node_name, replacement='_'):
    """
    Turn a string into something Maya will accept as the base name of a node.

    Everything that is not a letter, a digit or an underscore becomes one underscore - a run
    of them becomes a single underscore rather than one each, so ``'head - geo'`` is
    ``'head_geo'`` and not ``'head___geo'``. Leading and trailing whitespace goes first, so
    it does not become underscores of its own.

    This does not touch ``|`` or ``:`` in any special way: they are illegal in a base name
    and are replaced like anything else. A caller holding a whole path should take it apart
    with :func:`get_node_name_parts` first.

    :param str node_name: The string to make safe.
    :param str replacement: What to put in place of each run of illegal characters.
    :return: A name Maya will take, or '' when there was nothing left to work with.
    :rtype: str
    """

    if not node_name:
        return ''

    cleaned = ILLEGAL_CHARACTERS.sub(replacement, str(node_name).strip())
    # A string of nothing but illegal characters collapses to the replacement itself, which
    # is not a name anybody meant.
    return '' if cleaned.strip(replacement) == '' and replacement else cleaned


def make_maya_safe_name(node_name, make_unique=False):
    """
    A name Maya will take for a new node.

    :param str node_name: What the caller wants it called.
    :param bool make_unique: Add a number until nothing in the scene has the name already.
    :return: The safe name, or '' when nothing usable was given.
    :rtype: str
    """

    node_name = remove_illegal_characters(node_name)
    if not node_name:
        return ''

    # Maya will not take a name that starts with a digit. A letter in front is the least
    # surprising fix: it keeps the number the caller chose visible in the name.
    if node_name[0].isdigit():
        node_name = 'a{}'.format(node_name)

    if make_unique:
        node_name = get_unique_dagname(node_name)
    return node_name


def get_unique_dagname(node_name):
    """
    The given name if nothing in the scene has it, otherwise the same name numbered up.

    Padding is kept: ``arm_01`` becomes ``arm_02``, not ``arm_2``. The version this replaces
    stripped every trailing digit and appended the count, which lost the padding and, for a
    name like ``spine_02_ctrl``, was not what anyone meant either.

    :param str node_name: The name to start from.
    :return: A name no node currently has.
    :rtype: str
    :raises ValueError: When given nothing.
    """

    if not node_name:
        raise ValueError('A node name is needed; got {!r}.'.format(node_name))
    if not cmds.objExists(node_name):
        return node_name

    match = TRAILING_DIGITS.match(node_name)
    if match:
        stem, digits = match.group(1), match.group(2)
        width = len(digits)
        counter = int(digits)
    else:
        # No trailing digits, so the first candidate is the name with a 1 on the end.
        stem = node_name
        width = 1
        counter = 0

    candidate = node_name
    while cmds.objExists(candidate):
        counter += 1
        candidate = '{}{}'.format(stem, str(counter).zfill(width))
    return candidate
