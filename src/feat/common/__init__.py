# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import traceback

from feat.common import log


def error_handler(self, f):

    def log_error(format, *args):
        self.logex(log.LogLevel.error, format, args, depth=3)

    log_error("Error processing: %s %s", type(f.value),
              f.getErrorMessage() or f)

    frames = traceback.extract_tb(f.getTracebackObject())
    if len(frames) > 0:
        log_error("Last traceback frame: %r", frames[-1])
    if log.verbose:
        log_error("Full traceback below:\n%s",
                  "".join(traceback.format_tb(f.getTracebackObject())))


def first(iterator):
    '''
    Returns first element from the operator or None.

    @param iterator: Iterable.
    '''
    try:
        return next(iterator)
    except StopIteration:
        return None
