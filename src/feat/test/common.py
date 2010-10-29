from feat.common import log
from feat.interface import logging
from twisted.trial import unittest
from twisted.internet import defer, reactor

log.FluLogKeeper.init('test.log')


class TestCase(unittest.TestCase, log.FluLogKeeper, log.Logger):

    log_category = "test"

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)


    def _cb_after(self, arg, obj, method):
        '''
        Returns defered fired after the call of method on object.
        Can be used in defered chain like this:

        d.addCallback(doSomeStuff)
        d.addCallback(self._cb_after, obj=something, method=some_method)
        d.addCallback(jobAfterCallOfSomeMethod)

        Parameter passed to the last callback is either return value of 
        doSomeStuff, or, if this is None, the return value of stubbed method.
        '''
        old_method = obj.__getattribute__(method)
        d = defer.Deferred()

        def new_method(*args, **kwargs):
            obj.__setattr__(method, old_method)
            ret = old_method(*args, **kwargs)
            reactor.callLater(0, d.callback, arg or ret)
            return ret

        obj.__setattr__(method, new_method)

        return d
