"""
The small pieces of state Maya remembers between sessions: mca.mya.utils.optionvars.

    mayapy tests/test_optionvars.py
"""

# python imports
import os
import sys

# mca imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


def body(suite):
    harness.add_sibling_packages()

    import maya.cmds as cmds
    from mca.mya.utils import optionvars

    # Names of our own, removed at the end, so a test run leaves the user's preferences as
    # it found them.
    names = ['MCATestString', 'MCATestFlag', 'MCATestNumber', 'MCATestFloat', 'MCATestList',
             'MCATestRenamed', 'MCATestShared', 'MCATestChildOnly']
    for name in names:
        cmds.optionVar(remove=name)

    try:
        class TestOptions(optionvars.MCAOptionVars):
            """A set of option variables for the suite to push around."""

            MCATestString = {'default_value': 'hello', 'docstring': 'A string.'}
            MCATestFlag = {'default_value': True, 'docstring': 'A flag.'}
            MCATestNumber = {'default_value': 7, 'docstring': 'A whole number.'}
            MCATestFloat = {'default_value': 2.5, 'docstring': 'A number.'}
            MCATestList = {'default_value': [], 'docstring': 'A list of strings.'}
            renamed = {'name': 'MCATestRenamed', 'default_value': 'under another name',
                       'docstring': 'Stored under a different name than the attribute.'}
            not_an_option_var = 'just an attribute'

        options = TestOptions()

        # -- the declarations become properties ----------------------------------------- #
        suite.check('the declarations are properties on the class, not dicts',
                    isinstance(TestOptions.MCATestString, property))
        suite.check('a plain class attribute is left alone',
                    TestOptions.not_an_option_var == 'just an attribute')
        suite.check('the docstring is kept where help() will find it',
                    TestOptions.MCATestString.__doc__ == 'A string.')
        suite.check('every declaration is listed',
                    set(TestOptions._option_var_names) ==
                    {'MCATestString', 'MCATestFlag', 'MCATestNumber', 'MCATestFloat',
                     'MCATestList', 'renamed'},
                    str(TestOptions._option_var_names))

        # -- reading before anything has been written ----------------------------------- #
        suite.check('an unset option variable reads as its default',
                    options.MCATestString == 'hello')
        suite.check('and reading it wrote the default, so Maya has it now',
                    cmds.optionVar(exists='MCATestString'))
        suite.check('a number reads as its default', options.MCATestNumber == 7)
        suite.check('a float reads as its default', options.MCATestFloat == 2.5)
        suite.check('a list reads as its default', options.MCATestList == [])

        # The bug: Maya has no boolean option variable - it keeps True as 1 - so this used
        # to answer 1, which prints differently and fails `is True`.
        suite.check('a flag reads back as a bool, not as 1',
                    options.MCATestFlag is True, repr(options.MCATestFlag))

        # -- writing and reading back ---------------------------------------------------- #
        options.MCATestString = 'goodbye'
        suite.check('a string round-trips', options.MCATestString == 'goodbye')
        suite.check('and it really is in Maya',
                    cmds.optionVar(query='MCATestString') == 'goodbye')

        options.MCATestFlag = False
        suite.check('False round-trips as False, not as 0',
                    options.MCATestFlag is False, repr(options.MCATestFlag))
        options.MCATestFlag = True
        suite.check('and True as True', options.MCATestFlag is True)

        options.MCATestNumber = 42
        suite.check('a number round-trips', options.MCATestNumber == 42)
        options.MCATestFloat = 0.125
        suite.check('a float round-trips', options.MCATestFloat == 0.125)

        options.MCATestList = ['one', 'two']
        suite.check('a list round-trips', options.MCATestList == ['one', 'two'],
                    str(options.MCATestList))
        # Maya gives a one-entry string array back as a bare string.
        options.MCATestList = ['only']
        suite.check('a list of one comes back as a list, not as a bare string',
                    options.MCATestList == ['only'], repr(options.MCATestList))

        suite.check("the 'name' key decides where it is stored",
                    options.renamed == 'under another name' and
                    cmds.optionVar(exists='MCATestRenamed'))
        options.renamed = 'changed'
        suite.check('and reading and writing goes through the attribute name',
                    options.renamed == 'changed' and
                    cmds.optionVar(query='MCATestRenamed') == 'changed')

        # -- a second instance sees the same values -------------------------------------- #
        second = TestOptions()
        suite.check('a second instance reads what the first wrote',
                    second.MCATestString == 'goodbye')

        # -- reset ----------------------------------------------------------------------- #
        was_reset = options.reset('MCATestString')
        suite.check('resetting one puts it back to its default',
                    options.MCATestString == 'hello')
        suite.check('and says which it reset', was_reset == ['MCATestString'], str(was_reset))
        suite.check('and leaves the others alone', options.MCATestNumber == 42)

        options.reset()
        suite.check('resetting everything puts the number back', options.MCATestNumber == 7)
        suite.check('and the flag', options.MCATestFlag is True)
        suite.check('and the list', options.MCATestList == [])
        suite.check('and the renamed one', options.renamed == 'under another name')
        suite.check('resetting a name that is not there reports nothing reset',
                    options.reset('NoSuchOption') == [])

        # -- the shared-defaults bug ----------------------------------------------------- #
        # Two classes declaring an option variable of the same name used to write into one
        # dictionary on the base class, keyed by the bare name, so the second one's default
        # became the first one's too.
        class OptionsOne(optionvars.MCAOptionVars):
            MCATestShared = {'default_value': 'from one'}

        class OptionsTwo(optionvars.MCAOptionVars):
            MCATestShared = {'default_value': 'from two'}

        suite.check('two classes keep their own defaults',
                    OptionsOne._option_var_defaults['MCATestShared'] == 'from one' and
                    OptionsTwo._option_var_defaults['MCATestShared'] == 'from two',
                    '{} / {}'.format(OptionsOne._option_var_defaults,
                                     OptionsTwo._option_var_defaults))
        suite.check("one class does not see the other's declarations",
                    'MCATestString' not in OptionsOne._option_var_names,
                    str(OptionsOne._option_var_names))

        # -- a subclass of a subclass ---------------------------------------------------- #
        class ChildOptions(TestOptions):
            MCATestChildOnly = {'default_value': 'child'}

        child = ChildOptions()
        suite.check("a subclass inherits its parent's option variables",
                    'MCATestString' in ChildOptions._option_var_names,
                    str(ChildOptions._option_var_names))
        suite.check('and adds its own', child.MCATestChildOnly == 'child')
        suite.check('a reset on the subclass covers both',
                    set(child.reset()) >= {'MCATestString', 'MCATestChildOnly'},
                    str(child.reset()))

        # -- a declaration with no default ----------------------------------------------- #
        def declare_without_a_default():
            class Broken(optionvars.MCAOptionVars):
                MCAMissingDefault = {'docstring': 'no default here'}
            return Broken

        message = suite.raises('a declaration with no default_value is refused at class '
                               'definition, not at first read', declare_without_a_default)
        suite.check('and the message names the option variable',
                    'MCAMissingDefault' in message, message)

        # -- what was dropped ------------------------------------------------------------ #
        for name in ('OptionVarsHelper', 'OptionVarsHelperRegistry', 'option_var_wrapper'):
            suite.check('{} is gone'.format(name), not hasattr(optionvars, name))
        for name in ('save_to_file', 'load_from_file', 'inspect'):
            suite.check('{} is gone - it was Python 2, or never called'.format(name),
                        not hasattr(optionvars.MCAOptionVars, name))

    finally:
        for name in names:
            cmds.optionVar(remove=name)
        cmds.optionVar(remove='MCAMissingDefault')

    suite.check('the suite left the user\'s preferences as it found them',
                not any(cmds.optionVar(exists=name) for name in names))
    suite.note('maya', harness.maya_version())


sys.exit(harness.run_in_maya('optionvars', body))
