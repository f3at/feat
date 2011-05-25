# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import sys

from zope.interface import implements
from twisted.internet import reactor

from feat import hacks
from feat.common import defer

from twisted.internet.interfaces import IDelayedCall


def scale(factor):
    '''
    Scale time by the factor.
    @param factor: Factor to scale.
                   Values greater than 1 makes time pass slower.
                   Values from range 0:1 makes time pass faster.
    @type factor: C{float}
    '''
    assert 0 < factor, "%d is not greater than 0" % (factor, )
    global _time_scale
    _time_scale = float(factor) * _debugger_scale()


def time():
    '''
    Get current time.
    @return: Currect time in seconds from Epoch taking into acount the
             time scaling mechanism.
    @rtype: float
    '''
    real_time = _python_time.time()
    return real_time / _get_scale()


def future(seconds):
    '''
    Get time in future being aware of time scalling mechanism.
    @param seconds: How many seconds from now
    @type seconds: C{float}
    @return: Time in seconds from Epoch seconds from now.
    @rtype: C{float}
    '''
    return time() + seconds


def left(moment):
    '''
    How much time is left to specified time in future taking into account
    time scalling.
    @param moment: Time in number of scaled seconds since Epoc
    @rtype moment: C{float}
    @return: Time in real seconds left.
    @rtype: C{float}
    '''
    return (moment - time())


def callLater(_seconds, _f, *args, **kwargs):
    '''
    Wrapper for reactor.callLater() aware the time scalling.
    This method should always be used instead directly touching the reactor.
    See: L{twisted.internet.interfaces.IDelayedCall.callLater}.
    '''
    cur_scale = _get_scale()
    if cur_scale == 1:
        return reactor.callLater(_seconds, _f, *args, **kwargs)
    else:
        _seconds = _seconds * cur_scale
        call = reactor.callLater(_seconds, _f, *args, **kwargs)
        return ScaledDelayedCall(cur_scale, call)


def reset():
    '''
    Reset any manipulations done by the module.
    '''
    global _time_scale
    _time_scale = 1


@defer.inlineCallbacks
def wait_for(logger, check, timeout, freq=0.5):
    assert callable(check)
    waiting = 0

    while True:
        if check():
            logger.info('Check %r positive, continuing with the test.',
                      check.__name__)
            break
        logger.info('Check %r still negative, sleeping %r seconds.',
                  check.__name__, freq)
        waiting += freq
        if waiting > timeout:
            raise RuntimeError('Timeout error waiting for check %r.'
                               % check.__name__)
        d = defer.Deferred()
        callLater(freq, d.callback, None)
        yield d


### private ###

_time_scale = None
_python_time = hacks.import_time()
clock = _python_time.clock


def _get_scale():
    global _time_scale
    return _time_scale


class ScaledDelayedCall(object):
    implements(IDelayedCall)

    def __init__(self, scale, call):
        self._scale = scale
        self._call = call

    ### IDelayedCall ###

    def getTime(self):
        return self._call.getTime() / self._scale

    def cancel(self):
        return self._call.cancel()

    def delay(self, secondsLater):
        return self._call.delay(secondsLater * self._scale)

    def reset(self, secondsFromNow):
        return self._call.reset(secondsFromNow * self._scale)

    def active(self):
        return self._call.active()


def _debugger_scale():
    if sys.gettrace() is None:
        return 1
    else:
        return 4


reset()
