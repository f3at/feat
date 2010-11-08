from zope.interface import Interface

from . import serialization


class IFiber(serialization.ISnapshot):

    def proceed():
        '''Run the fiber.'''

    def succeed(param=None):
        '''Set the fiber to start on the callback path
        with the specified parameter'''

    def fail(param=None):
        '''Set the fiber to start on the errback path
        with the specified parameter'''

    def addCallbacks(callback, errback=None,
                     callbackArgs=None, callbackKeywords=None,
                     errbackArgs=None, errbackKeywords=None):
        pass

    def addCallback(callback, *args, **kwargs):
        pass

    def addErrback(errback, *args, **kwargs):
        pass

    def addBoth(callback, *args, **kwargs):
        pass
