"""
The one answer shape, shared with the rest of the pipeline.

Every public call answers with the same three keys::

    {'ok': bool, 'result': <anything>, 'message': 'a sentence for a person'}

This is the same contract the Maya plug-in tools use, and it is what makes one
implementation serve the window, the command line and an MCP tool without a translation
layer in between. The message is not a log line: it is written for whoever has to act on
it, and it says what to do when something is wrong.
"""

# python imports
import functools
import logging


logger = logging.getLogger('mca-launcher')

#: The keys every response carries, and the only keys it carries.
RESPONSE_KEYS = ('ok', 'result', 'message')


def response(ok, result=None, message=''):
    """
    Build a response.

    :param bool ok: Did the thing happen.
    :param result: Whatever the caller asked for.
    :param str message: One or two sentences for a person.
    :return: The response.
    :rtype: dict
    """

    return {'ok': bool(ok), 'result': result, 'message': str(message)}


def failed(message, result=None):
    """
    Build a failed response.

    :param str message: What went wrong, and what to do about it.
    :param result: Anything worth handing back anyway - a path that was tried, say.
    :return: The response.
    :rtype: dict
    """

    return response(False, result, message)


def is_response(value):
    """
    :param value: Anything.
    :return: Whether it is already a response, and so should be passed through untouched.
    :rtype: bool
    """

    return isinstance(value, dict) and set(value) == set(RESPONSE_KEYS)


def safe(function):
    """
    Turn a function that raises into one that answers.

    The wrapped function returns either a ``(result, message)`` pair, a ready-made
    response, or a bare result - and raises for anything it cannot do. A raise is not a
    crash at this boundary: the sentence an exception carries is aimed at whoever has to
    fix it, so it becomes the message of a failed response, and the traceback goes to the
    log where it belongs.

    :param function: The function to wrap.
    :return: The wrapped function.
    """

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            outcome = function(*args, **kwargs)
        except Exception as error:
            logger.exception('%s failed', function.__name__)
            message = str(error).strip()
            if not message:
                # An exception with no message is still a fact worth reporting; naming the
                # type at least says which kind of wrong it was.
                message = '{} with no message. The log has the traceback.'.format(
                    type(error).__name__)
            return failed(message)

        if is_response(outcome):
            return outcome
        if isinstance(outcome, tuple) and len(outcome) == 2:
            result, message = outcome
            return response(True, result, message)
        return response(True, outcome, '')

    return wrapper
