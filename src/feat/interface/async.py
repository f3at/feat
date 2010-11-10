from zope.interface import Attribute

from . import serialization


class IFiber(serialization.ISnapshot):
    '''Fibers are used to specify a chain of asynchronous execution.

    The use case is to specify a chain, return it and delegate
    the responsibility of starting it to the caller.

    Fibers can be nested to follow the string of execution.
    Nested fibers have the same fiber identifier but sub-fibers
    have its depth incremented.
    '''

    fiber_id = Attribute("Fiber identifier, same for all nested fibers")
    fiber_depth = Attribute("Depth in the fiber chain")

    def nest(parent):
        '''Set the fiber as a nested sub-fiber of the specified one.'''

    def start():
        '''Start the fiber asynchronous execution.
        Should theoretically not be called by the creator of the fiber.
        '''

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
