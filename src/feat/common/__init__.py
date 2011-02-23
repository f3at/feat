# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import traceback


def error_handler(self, f):
    self.error("Error processing: %s", f.getErrorMessage())
    frames = traceback.extract_tb(f.getTracebackObject())
    if len(frames) > 0:
        self.error('Last traceback frame: %r', frames[-1])
