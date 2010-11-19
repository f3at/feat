from zope.interface import Interface, Attribute

from feat.common import enum

__all__ = ["TriggerType", "FiberError",
           "FiberStartedError", "FiberTriggerError", "FiberChainError",
           "IFiberDescriptor", "IFiber"]


class TriggerType(enum.Enum):
    '''Type of fiber triggering:

     - succeed:   Execution starts by the callback part of the chain.
     - fail:      Execution starts by the errback part of the chain.
     - chained:   Execution is started by the master fiber it was chained to.
    '''

    succeed, fail, chained = range(3)


class FiberError(Exception):
    pass


class FiberStartedError(FiberError):
    pass


class FiberTriggerError(FiberError):
    pass


class FiberChainError(FiberError):
    pass


class WovenSection(Interface):

    state = Attribute("Fiber section state")

    def enter():
        '''Initializes a woven section that will allow all functions
        called from the caller to use fiber-aware functions.'''

    def abort(result=None):
        '''Exits a woven section without starting any fibers.
        Returns None.'''

    def exit(result=None):
        '''Exits a woven section. Root sections return a deferred
        called when all fibers have been executed, and sub-sections
        return the result as-is.'''


class IFiberDescriptor(Interface):

    fiber_id = Attribute("Fiber identifier, same for all nested fibers")
    fiber_depth = Attribute("Depth in the fiber chain")

    def attach(fiber):
        '''Attaches a fiber to the descriptor.
        It will call the fiber method bind().'''


class IFiber(IFiberDescriptor):
    '''Fibers are used to specify a chain of asynchronous execution.

    The use case is to specify a chain, return it and delegate
    the responsibility of starting it to the caller.

    Fibers can be nested to follow the string of execution.
    Nested fibers have the same fiber identifier but sub-fibers
    have its depth incremented.

    Fiber serialization format::

        (TRIGGER_TYPE, INITAL_PARAM, [((CB_IDENTIFIER, CB_ARGS, CALL_KWARGSS),
                                       (EB_IDENTIFIER, EB_ARGS, EB_KWARGSS))])

    Example::

        > f = Fiber()
        > f.addCallback(add, 5)
        > f.addErrback(resolve_error)
        > f.addCallbacks(success, failed,
                         callbackArgs=(42,),
                         callbackKeywords={"spam": "beans"},
                         errbackKeywords={"bacon", "eggs"})
        > f.suceed(0)

    Serialize to::

        (TriggerType.succeed, 0,
         [(("add", (5,), None), None),
          (None, ("resolve_error", None, None)),
          (("success", (42,), {"spam": "beans"}),
           ("failed", None, {"bacon", "eggs"}))])

    '''

    def start():
        '''Start the fiber asynchronous execution.
        Should theoretically not be called by the creator of the fiber,
        but by the parent fiber descriptor.
        Because parent fiber descriptor can be a fiber itself,
        '''

    def succeed(param=None):
        '''Set the fiber to start on the callback path
        with the specified parameter'''

    def fail(param=None):
        '''Set the fiber to start on the errback path
        with the specified parameter'''

    def chain(fiber):
        '''Chains the specified fiber.
        Like adding all the callback of the specified fiber.
        The Chained fiber will be considerred triggered.'''

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

    def _bind(descriptor, fiber_id, fiber_depth):
        '''Initializes the fiber as a nested sub-fiber
        of the specified fiber descriptor.
        Called by descriptor's attach method.
        Returns True if the fiber was bound, False if it was already bound
        to this descriptor, and raise an exception if already bound
        to another descriptor.
        Not to be called by anything but a IFiberDescriptor.'''

    def _chain():
        '''Freezes the fiber as chained and returns a deferred
        and serialized calls.
        Not to be called by anything but other IFiber.'''
