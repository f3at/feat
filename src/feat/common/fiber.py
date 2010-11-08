from twisted.internet import defer
from zope.interface import implements

from feat.interface import async

from . import reflect

class Fiber(object):

    implements(async.IFiber)

    def __init__(self):
        self._trigger = None
        self._param = None
        self._deferred = defer.Deferred()
        self._state_trigger = None
        self._state_calls = []

    ### serialization.ISnapshot Methods ###

    def snapshot(self, context={}):
        # FIXME: Should we deep clone ?
        return self._state_trigger, self._param, self._state_calls

    ### async.IFiber Methods ###

    def proceed(self):
        return self._trigger(self._param)

    def succeed(self, param=None):
        if self._trigger is not None:
            raise RuntimeError("Fiber trigger already set")
        self._param = param
        self._trigger = self._deferred.callback
        self._state_trigger = True

    def fail(self, param=None):
        if self._trigger is not None:
            raise RuntimeError("Fiber trigger already set")
        self._param = param
        self._trigger = self._deferred.errback
        self._state_trigger = False

    def addCallbacks(self, callback=None, errback=None,
                     callbackArgs=None, callbackKeywords=None,
                     errbackArgs=None, errbackKeywords=None):
        callbackName = reflect.canonical_name(callback)
        errbackName = reflect.canonical_name(errback)
        call = (callbackName, callbackArgs or None, callbackKeywords or None,
                errbackName, errbackArgs or None, errbackKeywords or None)
        self._state_calls.append(call)

        callback = callback or defer.passthru
        self._deferred.addCallbacks(callback, errback,
                                    callbackArgs, callbackKeywords,
                                    errbackArgs, errbackKeywords)
        return self

    def addCallback(self, callback, *args, **kwargs):
        return self.addCallbacks(callback,
                                 callbackArgs=args,
                                 callbackKeywords=kwargs)

    def addErrback(self, errback, *args, **kwargs):
        return self.addCallbacks(errback=errback,
                                 errbackArgs=args,
                                 errbackKeywords=kwargs)

    def addBoth(self, callback, *args, **kwargs):
        return self.addCallbacks(callback, callback,
                                 callbackArgs=args,
                                 callbackKeywords=kwargs,
                                 errbackArgs=args,
                                 errbackKeywords=kwargs)
