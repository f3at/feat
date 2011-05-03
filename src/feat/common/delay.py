# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import sys

from twisted.internet import reactor

time_scale = 1


def _debugger_scale():
    # FIXME: This was nice idea but it breaks the way we are setting the
    # expiration time for Requester.
    # If expiration_time = c_time + 10 seconds
    # The request will expire after 2.5, but the message is still there in
    # a queue waiting to be consumed.
    return 1

    if sys.gettrace() is None:
        return 0.25
    else:
        return 1


def callLater(timeout, method, *args, **kwargs):
    return reactor.callLater(get_scale() * timeout, method, *args, **kwargs)


def get_scale():
    global time_scale
    return time_scale * _debugger_scale()
