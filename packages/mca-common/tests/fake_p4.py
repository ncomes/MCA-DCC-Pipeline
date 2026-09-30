"""
A stand-in for the ``p4`` command line client, for the source control suite.

It records every invocation - as a JSON line per call, so the suite can check *exactly* what
arguments p4 was handed, which is the only way to prove a path with a space in it arrived as
one argument - and answers the handful of commands the framework runs.

    MCA_FAKE_P4_LOG   where to record calls
    MCA_FAKE_P4_ROOT  the workspace root to report for 'ws_project'
    MCA_FAKE_P4_FAIL  a word that makes any call mentioning it fail
"""

# python imports
import json
import os
import sys


CLIENTS = ("Client ws_other 2026/01/01 root {other} 'Somebody else's'\n"
           "Client ws_project 2026/01/02 root {root} 'The one with the config in it'\n")

TAGGED_CHANGES = ('... change 4011\n'
                  '... desc rig: hero, arm fixes\n'
                  '... status pending\n'
                  '\n'
                  '... change 4012\n'
                  '... desc mca: auto-submit\n'
                  '... status pending\n'
                  '\n')

FORM = ('Change:\tnew\n'
        '\n'
        'Client:\tws_project\n'
        '\n'
        'Description:\n'
        '\t{description}\n')


def verb_and_arguments(arguments):
    """
    :param list[str] arguments: Everything after ``p4``.
    :return: The command word and what followed it.
    :rtype: (str, list[str])
    """

    rest = list(arguments)
    while rest:
        item = rest.pop(0)
        if item in ('-p', '-c', '--field'):
            if rest:
                rest.pop(0)
            continue
        if item.startswith('-'):
            continue
        return item, rest

    return '', []


def main():
    arguments = sys.argv[1:]

    log = os.environ.get('MCA_FAKE_P4_LOG', '')
    if log:
        with open(log, 'a', encoding='utf-8') as opened:
            opened.write(json.dumps(arguments) + '\n')

    fail_on = os.environ.get('MCA_FAKE_P4_FAIL', '')
    if fail_on and any(fail_on in argument for argument in arguments):
        sys.stdout.write('{0} - no such file(s).\n'.format(fail_on))
        return 1

    verb, rest = verb_and_arguments(arguments)

    if verb == 'clients':
        root = os.environ.get('MCA_FAKE_P4_ROOT', os.getcwd())
        sys.stdout.write(CLIENTS.format(root=root, other=os.path.join(root, 'nowhere')))
    elif verb == 'changes':
        sys.stdout.write(TAGGED_CHANGES)
    elif verb == 'change' and '-o' in arguments:
        description = ''
        for index, item in enumerate(arguments):
            if item == '--field' and index + 1 < len(arguments):
                value = arguments[index + 1]
                if value.startswith('Description='):
                    description = value.split('=', 1)[1]
        sys.stdout.write(FORM.format(description=description))
    elif verb == 'change' and '-i' in arguments:
        sys.stdout.write('Change 4099 created.\n')
    elif verb == 'submit':
        sys.stdout.write('Change 4099 submitted.\n')
    else:
        sys.stdout.write('{0} - opened for {0}\n'.format(verb or 'nothing'))

    return 0


if __name__ == '__main__':
    sys.exit(main())
