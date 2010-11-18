# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from twisted.internet import reactor

time_scale = 1


def callLater(timeout, method, *args, **kwargs):
    global time_scale
    return reactor.callLater(time_scale * timeout,\
                                 method, *args, **kwargs)
