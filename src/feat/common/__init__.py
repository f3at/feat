# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import traceback

from feat.common import log, error


def error_handler(logger, f):
    error.handle_failure(logger, f, "Error processing")


def first(iterator):
    '''
    Returns first element from the operator or None.

    @param iterator: Iterable.
    '''
    try:
        return next(iterator)
    except StopIteration:
        return None
