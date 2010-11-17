import sys
import uuid

from twisted.internet import reactor, defer
from twisted.python import failure
from zope.interface import implements

from feat.interface.fiber import *

from . import reflect, decorator

FIBER_STATE_TAG = "__fiber_dict__"


class FiberError(Exception):
    pass


class FiberStartedError(FiberError):
    pass


class FiberTriggerError(FiberError):
    pass


class FiberChainError(FiberError):
    pass


@decorator.simple
def woven(fun):
    '''Decorator that will initialize and eventually start nested fibers.'''

    def wrapper(*args, **kwargs):
        section = WovenSection()
        section.enter()
        result = fun(*args, **kwargs)
        return section.exit(result)

    return wrapper


def get_state(depth=0):
    '''This function may fiddle with the locals of the calling function,
    to make it the root function of the fiber. If called from a short-lived
    function be sure to use a bigger frame depth.
    Returns the fiber state or None.'''

    base_frame = _get_base_frame(depth)
    if not base_frame:
        # Frame not found
        raise RuntimeError("Base frame not found")

    # Lookup up the frame stack starting at the base frame for the fiber state
    level = 0
    frame = base_frame
    while frame:
        locals = frame.f_locals
        state = locals.get(FIBER_STATE_TAG)
        if state:
            if level > 0:
                # Copy a reference of the fiber state in the base frame
                base_frame.f_locals[FIBER_STATE_TAG] = state
            return state
        frame = frame.f_back
        level += 1
    return None


def set_state(state, depth=0):
    base_frame = _get_base_frame(depth)
    if not base_frame:
        # Frame not found
        raise RuntimeError("Base frame not found")

    base_frame.f_locals[FIBER_STATE_TAG] = state


def _get_base_frame(depth):
    # Go up the frame stack to the base frame given it's deepness.
    # Go up one level more to account for this function own frame.
    if depth < 0:
        return None
    base_frame = sys._getframe().f_back
    while base_frame and depth >= 0:
        depth -= 1
        base_frame = base_frame.f_back
    return base_frame


class WovenSection(object):
    '''Handles fiber-aware sections.'''

    def __init__(self, descriptor=None):
        self._descriptor = descriptor
        self._inside = False
        self.state = None

    def enter(self):
        if self._inside:
            raise FiberError("Already inside a woven section")
        self._inside = True

        if self._descriptor:
            # If a descriptor was specified it's a root section
            # just set an empty state in the calling function
            # and remember to start the fibers.
            state = {"descriptor": self._descriptor}
            set_state(state, depth=1)
        else:
            # Use a depth of 1 because we want the state to be
            # in the calling function not in the method.
            state = get_state(depth=1)
            if state is None:
                # First woven section, we create an
                # and remember to start the fibers.
                self._descriptor = RootFiberDescriptor()
                state = {"descriptor": self._descriptor}
                set_state(state, depth=1)

        self.state = state

    def abort(self, result=None):
        if not self._inside:
            raise FiberError("Not inside a woven section")
        self._inside = False

    def exit(self, result=None):
        if not self._inside:
            raise FiberError("Not inside a woven section")
        self._inside = False

        if self._descriptor is None:
            # If not a root section just return the result as-is
            return result

        # We are a root sections
        if IFiber.providedBy(result):
            # If the result is a fiber, we initialize and start it
            fiber = IFiber(result)
            self._descriptor.attach(fiber)
            return fiber.start()

        if isinstance(result, defer.Deferred):
            return result
        elif isinstance(result, failure.Failure):
            return defer.fail(result)
        else:
            return defer.succeed(result)


class RootFiberDescriptor(object):
    '''Root fiber descriptor created when get_descriptor()returns None.'''

    implements(IFiberDescriptor)

    def __init__(self):
        self.fiber_id = str(uuid.uuid4())
        self._index = 0

    ### IFiberDescriptor ###

    def attach(self, fiber):
        fiber = IFiber(fiber)
        if fiber._bind(self, self.fiber_id, 0, self._index):
            self._index += 1


class Fiber(object):
    '''Fibers are used to specify a chain of asynchronous execution.

    Fibers can be nested to follow the string of execution.
    Nested fibers have the same fiber_id but sub-fibers
    have there fiber_depth incremented.
    '''

    implements(IFiber)

    def __init__(self):
        self._descriptor = None
        self.fiber_depth = None
        self.fiber_id = None
        self.fiber_index = None

        self._index = 0
        self._started = False
        self._trigger = None
        self._param = None
        self._deferred = defer.Deferred()
        self._calls = []

    ### serialization.ISnapshot Methods ###

    def snapshot(self, context={}):
        # FIXME: Should we deep clone ?
        return self._trigger, self._param, self._calls

    ### IFiberDescriptor ###

    def attach(self, fiber):
        fiber = IFiber(fiber)
        if fiber._bind(self, self.fiber_id, self.fiber_depth + 1, self._index):
            self._index += 1

    ### IFiber Methods ###

    def start(self):
        if self._trigger is None:
            raise FiberTriggerError("Cannot start a fiber without trigger")
        if self._trigger == TriggerType.chained:
            raise FiberChainError("Chained fiber cannot be started")
        if self._started:
            raise FiberStartedError("Fiber already started")

        self._started = True

        descriptor = None
        if self.fiber_id is None:
            # If not attached, creates a root descriptor and attach it.
            # Useful to use fiber directly without decorators.
            descriptor = RootFiberDescriptor()
            descriptor.attach(self)

        d = self._deferred

        if self._trigger == TriggerType.succeed:
            d.callback(self._param)
        else:
            d.errback(self._param)

        return d

    def succeed(self, param=None):
        if self._trigger is not None:
            raise FiberTriggerError("Fiber trigger already set")
        self._trigger = TriggerType.succeed
        self._param = param
        return self

    def fail(self, failure=None):
        if self._trigger is not None:
            raise FiberTriggerError("Fiber trigger already set")
        self._trigger = TriggerType.fail
        self._param = failure
        return self

    def chain(self, fiber):

        def chain_callback(value, d):
            d.callback(value)
            return d

        def chain_errback(value, d):
            d.errback(value)
            return d

        if self._trigger is not None:
            raise FiberChainError("Fiber trigger already set, "
                                  "cannot chain fibers")
        fiber = IFiber(fiber)
        d, calls = fiber._chain()
        self._calls.extend(calls)
        self._deferred.addCallbacks(chain_callback, chain_errback,
                                    (d, ), None, (d, ), None)
        return self

    def addCallbacks(self, callback=None, errback=None,
                     callbackArgs=None, callbackKeywords=None,
                     errbackArgs=None, errbackKeywords=None):
        if self._started:
            raise FiberStartedError("Fiber already started, "
                                    "cannot add callback anymore")
        if self._trigger is not None:
            raise FiberTriggerError("Fiber trigger already set, "
                                    "cannot add callback anymore")

        # Use shorter names for parameters
        cb = callback
        cba = callbackArgs
        cbk = callbackKeywords
        eb = errback
        eba = errbackArgs
        ebk = errbackKeywords

        # Serialize callbacks and arguments
        dump = self._serialize_callbacks(cb, eb, cba, cbk, eba, ebk)
        self._calls.append(dump)

        # Wrap the callbacks
        cb, cba, cbk = self._wrap_callback(cb, cba, cbk)
        eb, eba, ebk = self._wrap_callback(eb, eba, ebk)

        # Add the callbacks
        self._deferred.addCallbacks(cb, eb, cba, cbk, eba, ebk)

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

    def _bind(self, desc, fiber_id, fiber_depth, fiber_index):
        if self._descriptor is not None:
            if self._descriptor == desc:
                # Already attached
                return False
            raise FiberError("Fiber already attached to another descriptor")
        self._descriptor = desc
        self.fiber_id = fiber_id
        self.fiber_depth = fiber_depth
        self.fiber_index = fiber_index
        return True

    def _chain(self):
        if self._trigger is not None:
            raise FiberChainError("Fibers already triggered cannot be chained")
        self._trigger = TriggerType.chained
        result = self._deferred, self._calls
        self._deferred = None
        self._calls = None
        return result


    ### Private Methods ###

    def _wrap_callback(self, callback, args, kwargs):
        if callback:
            args = (self, callback, args or (), kwargs or {})
            return self._callback_wrapper, args, None
        # Deferred always need a callback, use pass through if not set
        return defer.passthru, None, None

    def _callback_wrapper(self, value, fiber, callback, args, kwargs):
        section = WovenSection(descriptor=fiber)
        section.enter()
        result = callback(value, *args, **kwargs)
        return section.exit(result)

    def _serialize_callbacks(self, cb, eb, cba, cbk, eba, ebk):
        cbd = None
        ebd = None
        if cb is not None:
            cbd = (reflect.canonical_name(cb), cba or None, cbk or None)
        if eb is not None:
            ebd = (reflect.canonical_name(eb), eba or None, ebk or None)
        return (cbd, ebd)
