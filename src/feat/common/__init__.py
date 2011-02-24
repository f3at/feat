# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import traceback


def error_handler(self, f):
    self.error("Error processing: %s", f.getErrorMessage())
    frames = traceback.extract_tb(f.getTracebackObject())
    if len(frames) > 0:
        self.error('Last traceback frame: %r', frames[-1])
    # change to True below for debug
    if False:
        self.error("Full traceback below:\n%s",
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
