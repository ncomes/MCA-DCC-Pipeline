"""
Small pieces of state Maya remembers between sessions.

Maya's option variables are the right place for "which tab was open", "was symmetry on",
"what did they last type in that field" - anything a user would be annoyed to set twice.
They survive a restart, they are per user, and they cost nothing.

A tool declares the ones it wants as class attributes and then reads and writes them as
ordinary attributes:

.. code-block:: python

    class RiggingOptions(optionvars.MCAOptionVars):
        MCAContentPath = {'default_value': '', 'docstring': 'The last content folder used.'}
        MCATurnOnSymmetry = {'default_value': True, 'docstring': 'Whether symmetry is on.'}
        MCAUISettingsTab = {'default_value': 0, 'docstring': 'The tab the user left open.'}

    options = RiggingOptions()
    options.MCATurnOnSymmetry = False       # written to Maya's preferences straight away
    if options.MCATurnOnSymmetry:          # read back, in this session or the next one
        ...

The name the option variable is stored under is the attribute's name, so it wants to be
specific enough not to collide with another tool's - Maya has one flat namespace for these.

What was wrong before:

- **``load_from_file`` was Python 2.** It called ``json_data.iteritems()``, which does not
  exist in Python 3, so the function raised ``AttributeError`` on its first line of real
  work in every Maya the pipeline supports. Nothing called it. Gone, with
  ``save_to_file``.
- **The duplicate-name check could never find a duplicate.** ``inspect_all`` built its set
  with ``all_registered_variable_names.union(set(used_option_vars))`` and threw the result
  away - ``union`` returns a new set, it does not add to one. The set stayed empty, so the
  check that existed to catch two tools using one option variable name reported success
  every time. Nothing called it either.
- **The defaults were shared between subclasses.** ``_option_var_defaults`` and friends were
  mutable class attributes on the base class, so every subclass wrote its defaults into the
  same dictionary, keyed by the bare attribute name. Two tools with an option variable of
  the same name got each other's default. The properties are built per subclass now, when
  the subclass is created, rather than by rewriting the class on every instantiation.
- **The registry had no callers at all** - not ``reset_all``, not ``inspect_all``, not
  ``register_mca_option_var``. It was a singleton whose ``__getattr__`` read
  ``self._option_var_instances`` and so recursed without end if anything reached it before
  ``__init__`` had run. Gone, and with it the metaclass, the singleton import, and
  ``decorators.add_metaclass``, which no longer exists in ``mca-common``.
- **A bool came back as an int.** Maya stores ``True`` as ``1``, so ``options.SomeFlag``
  answered ``1`` rather than ``True`` - which is falsy in the same places but prints
  differently and compares ``is True`` as False. The value is now brought back to the type
  of the declared default.
- **A list came back wrapped in a tuple.** Writing through pymel's mapping -
  ``pm.optionVar[name] = ['one', 'two']`` - stores something that reads back as
  ``[('one', 'two')]``, one entry holding a tuple, so the second element of any list-valued
  option variable was unreachable. Maya's own command has a flag per type and an explicit
  way to write an array, which is what this uses now; pymel is not needed here at all.
"""

# python imports

# software specific imports
import maya.cmds as cmds

# mca imports
from mca.common import log


logger = log.MCA_LOGGER


def _write(name, value):
    """
    Put one value into Maya's preferences, with the right flag for its type.

    ``pm.optionVar[name] = value`` looks like the obvious way to do this and gets a list
    wrong: a list arrives back as a list holding one tuple, so ``['one', 'two']`` reads as
    ``[('one', 'two')]``. Maya's own command has a separate flag per type and an explicit
    way to write an array, which is what this uses.

    :param str name: The option variable's name.
    :param value: What to store. A list or tuple becomes an array; a bool becomes an
        integer, because Maya has no boolean option variable.
    """

    if isinstance(value, (list, tuple)):
        cmds.optionVar(clearArray=name)
        for item in value:
            if isinstance(item, bool):
                cmds.optionVar(intValueAppend=(name, int(item)))
            elif isinstance(item, int):
                cmds.optionVar(intValueAppend=(name, item))
            elif isinstance(item, float):
                cmds.optionVar(floatValueAppend=(name, item))
            else:
                cmds.optionVar(stringValueAppend=(name, str(item)))
        return

    if isinstance(value, bool):
        cmds.optionVar(intValue=(name, int(value)))
    elif isinstance(value, int):
        cmds.optionVar(intValue=(name, value))
    elif isinstance(value, float):
        cmds.optionVar(floatValue=(name, value))
    else:
        cmds.optionVar(stringValue=(name, '' if value is None else str(value)))


def _read(name, default_value):
    """
    Get one value out of Maya's preferences, as the type the default says it should be.

    :param str name: The option variable's name.
    :param default_value: The declared default, which decides the type.
    :return: The stored value.
    """

    value = cmds.optionVar(query=name)
    wanted_type = type(default_value)

    if wanted_type is bool:
        # Maya keeps True as 1. Without this the attribute answers 1, which is falsy in the
        # same places but prints differently and fails `is True`.
        return bool(value)
    if wanted_type is list:
        if isinstance(value, list):
            return value
        # A one-entry string array comes back as a bare string, and an unset variable as 0.
        return [] if value in (None, '', 0) else [value]
    if wanted_type is tuple:
        return tuple(value) if isinstance(value, (list, tuple)) else ()
    return value


def _property_for(name, default_value, docstring):
    """
    Build the property that reads and writes one option variable.

    :param str name: The option variable's name, as Maya stores it.
    :param default_value: What it is worth before anybody has set it.
    :param str docstring: What it is for, for ``help()`` and the documentation build.
    :return: The property.
    :rtype: property
    """

    def getter(self):
        if not cmds.optionVar(exists=name):
            _write(name, default_value)
            return default_value
        return _read(name, default_value)

    def setter(self, value):
        _write(name, value)

    return property(fget=getter, fset=setter, doc=docstring)


class MCAOptionVars(object):
    """
    Base class for a set of option variables declared as class attributes.

    Each attribute is a dict with a ``default_value`` and, worth writing, a ``docstring``.
    The subclass is turned into a set of properties when it is *defined*, not when it is
    instantiated, so two subclasses cannot tread on each other's defaults and making an
    instance is free.
    """

    #: Attribute names to leave alone when working out which attributes are option
    #: variables.
    _NAMES_TO_SKIP = ('reset',)

    #: Filled in per subclass by ``__init_subclass__``. Declared here so the base class
    #: answers rather than raising AttributeError.
    _option_var_names = ()
    _option_var_defaults = {}
    _option_var_docs = {}

    def __init_subclass__(cls, **kwargs):
        """
        Turn this subclass's declarations into properties.

        :raises KeyError: When a declaration has no ``default_value``. Without one there is
            nothing to answer with before the user has set anything, and nothing to reset
            to.
        """

        super(MCAOptionVars, cls).__init_subclass__(**kwargs)

        # Start from whatever a parent declared - its properties are inherited, so its
        # names belong in the list a reset walks - then add this class's own.
        names = list(cls._option_var_names)
        defaults = dict(cls._option_var_defaults)
        docs = dict(cls._option_var_docs)
        declared = [name for name in vars(cls)
                    if not name.startswith('_') and name not in cls._NAMES_TO_SKIP]

        for attribute_name in sorted(declared):
            parameters = getattr(cls, attribute_name, None)
            if not isinstance(parameters, dict):
                continue

            name = parameters.get('name') or attribute_name
            if 'default_value' not in parameters:
                raise KeyError('{}.{} needs a default_value.'.format(cls.__name__, name))

            if attribute_name not in names:
                names.append(attribute_name)
            defaults[attribute_name] = parameters['default_value']
            docs[attribute_name] = parameters.get('docstring') or ''
            setattr(cls, attribute_name,
                    _property_for(name, defaults[attribute_name], docs[attribute_name]))

        # Its own dictionaries, not the base class's. This is the bug that let two tools
        # with a same-named option variable get each other's default.
        cls._option_var_names = tuple(names)
        cls._option_var_defaults = defaults
        cls._option_var_docs = docs

    def reset(self, name=''):
        """
        Put option variables back to their declared defaults.

        :param str name: One to reset. '' resets all of them.
        :return: The names that were reset.
        :rtype: list(str)
        """

        was_reset = []
        for attribute_name in self._option_var_names:
            if name and attribute_name != name:
                continue
            setattr(self, attribute_name, self._option_var_defaults[attribute_name])
            was_reset.append(attribute_name)
        if name and not was_reset:
            logger.warning('%s has no option variable called %s.',
                           self.__class__.__name__, name)
        return was_reset
