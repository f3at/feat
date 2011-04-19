# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import sys

from twisted.internet import reactor

time_scale = 1


def _debugger_scale():
    if sys.gettrace() is None:
        return 0.25
    else:
        return 1


def callLater(timeout, method, *args, **kwargs):
    global time_scale
    return reactor.callLater(time_scale * timeout * _debugger_scale(),\
                                 method, *args, **kwargs)
