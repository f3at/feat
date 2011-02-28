import sys
import uuid

from twisted.internet import defer
from twisted.python import failure
from zope.interface import implements

from feat.interface.fiber import *
from feat.interface.serialization import *

from feat.common import reflect, decorator

SECTION_STATE_TAG = "__fiber_section_dict__"


def drop_result(result, method, *args, **kwargs):
    assert callable(method)
    return method(*args, **kwargs)


def bridge_result(result, method, *args, **kwargs):
    assert callable(method)
    method(*args, **kwargs)
    return result


def override_result(result, new_result):
    return new_result


def succeed(parma=None):
    return Fiber().succeed(parma)


def fail(failure=None):
    return Fiber().fail(failure)


def maybe_fiber(function, *args, **kwargs):

    try:
        result = function(*args, **kwargs)
    except:
        return defer.fail(failure.Failure())
    else:
        if IFiber.providedBy(result):
            return result.start()
        if isinstance(result, defer.Deferred):
            return result
        elif isinstance(result, failure.Failure):
            return defer.fail(result)
        else:
            return defer.succeed(result)


@decorator.simple_function
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
        state = locals.get(SECTION_STATE_TAG)
        if state:
            if level > 0:
                # Copy a reference of the fiber state in the base frame
                base_frame.f_locals[SECTION_STATE_TAG] = state
            return state
        frame = frame.f_back
        level += 1
    return None


def set_state(state, depth=0):
    base_frame = _get_base_frame(depth)
    if not base_frame:
        # Frame not found
        raise RuntimeError("Base frame not found")

    base_frame.f_locals[SECTION_STATE_TAG] = state


def del_state(depth=0):
    base_frame = _get_base_frame(depth)
    if not base_frame:
        # Frame not found
        raise RuntimeError("Base frame not found")

    locals = base_frame.f_locals
    if SECTION_STATE_TAG in locals:
        del locals[SECTION_STATE_TAG]


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
        self.descriptor = descriptor
        self.state = None
        self._is_root = True
        self._inside = False

    def enter(self):
        if self._inside:
            raise FiberError("Already inside a woven section")
        self._inside = True

        if self.descriptor is None:
            # Use a depth of 1 because we want the state to be
            # in the calling function not in the method.
            state = get_state(depth=1)
            if state is not None:
                # We are in a sub-section, just update the state
                self.state = state
                self.descriptor = state["descriptor"]
                self._is_root = False
                return
            # First woven section, we create an
            # and remember to start the fibers.
            self.descriptor = RootFiberDescriptor()

        state = {"descriptor": self.descriptor}
        set_state(state, depth=1)
        self.state = state

    def abort(self, result=None):
        self._cleanup()

    def exit(self, result=None):
        self._cleanup()

        if not self._is_root:
            # If not a root section just return the result as-is
            return result

        # We are a root sections
        if IFiber.providedBy(result):
            # If the result is a fiber, we initialize and start it
            fiber = IFiber(result)
            self.descriptor.attach(fiber)
            return fiber.start()

        if isinstance(result, defer.Deferred):
            return result
        elif isinstance(result, failure.Failure):
            return defer.fail(result)
        else:
            return defer.succeed(result)

    ### Private Methods ###

    def _cleanup(self):
        if not self._inside:
            raise FiberError("Not inside a woven section")
        self._inside = False
        self.state = None
        if self._is_root:
            del_state(depth=1)


class RootFiberDescriptor(object):
    '''Root fiber descriptor created when get_descriptor()returns None.'''

    implements(IFiberDescriptor)

    fiber_depth = 0

    def __init__(self):
        self.fiber_id = str(uuid.uuid4())

    ### IFiberDescriptor ###

    def attach(self, fiber):
        fiber = IFiber(fiber)
        fiber._bind(self, self.fiber_id, 1)


class Fiber(object):
    '''Fibers are used to specify a chain of asynchronous execution.

    Fibers can be nested to follow the string of execution.
    Nested fibers have the same fiber_id but sub-fibers
    have there fiber_depth incremented.

    When chaining fibers, the chained fiber cannot be started anymore.
    If a chained fiber is not triggered, it will start in function
    of the result and state of the master fiber at the point of chaining.

    Examples 1::

      def show(result, header):
          print header, result
          return result

      f1 = Fiber()
      f1.callback(show, "Fiber 1:")
      f1.succeed("F1")

      f2 = Fiber()
      f2.callback(show, "Fiber 2:")
      f2.succeed("F2") # f2 IS triggered

      f1.chain(f2)

      f1.start()

      >> Fiber 1: F1
      >> Fiber 2: F2

    Examples 2::

      def show(result, header):
          print header, result
          return result

      f1 = Fiber()
      f1.callback(show, "Fiber 1:")
      f1.succeed("F1")

      f2 = Fiber()
      f2.callback(show, "Fiber 2:")
      # f2 IS NOT triggered

      f1.chain(f2)

      f1.start()

      >> Fiber 1: F1
      >> Fiber 2: F1

    '''

    implements(IFiber, ISnapshotable)

    def __init__(self):
        self._descriptor = None
        self.fiber_depth = None
        self.fiber_id = None

        self._delegated_startup = False
        self._started = False
        self._trigger = None
        self._param = None

        # [(callable, tuple or None, dict or None,
        #   callable, tuple or None, dict or None)
        #  |Fiber]
        self._calls = []

    @property
    def trigger_type(self):
        return self._trigger

    @property
    def trigger_param(self):
        return self._param

    ### serialization.ISnapshotable Methods ###

    def snapshot(self):
        return self._trigger, self._param, self._snapshot_callbacks()

    ### IFiberDescriptor ###

    def attach(self, fiber):
        assert isinstance(fiber, Fiber)
        fiber._bind(self, self.fiber_id, self.fiber_depth + 1)

    ### IFiber Methods ###

    def start(self):
        # Check not started
        self._check_not_started()

        # More checks
        if self._delegated_startup:
            raise FiberStartupError("Fiber with delegated startup cannot "
                                    "be started directly")
        if self._trigger is None:
            raise FiberTriggerError("Cannot start a fiber without trigger")

        # Ensure there is a descriptor set
        self._ensure_descriptor()

        # Prepare the deferred calls
        d = self._prepare(defer.Deferred())

        # Trigger the deferred
        return self._fire(d, self._trigger, self._param)

    def trigger(self, trigger_type, param=None):
        self._check_not_started()

        if self._delegated_startup:
            raise FiberTriggerError("Fiber with delegated startup cannot "
                                    "change it's trigger anymore")
        if self._trigger is not None:
            raise FiberTriggerError("Fiber already triggered")

        self._trigger = TriggerType(trigger_type)
        if self._trigger == TriggerType.fail and param is None:
            self._param = failure.Failure()
        else:
            self._param = param
        return self

    def succeed(self, param=None):
        return self.trigger(TriggerType.succeed, param)

    def fail(self, failure=None):
        return self.trigger(TriggerType.fail, failure)

    def chain(self, fiber):
        self._check_not_started()

        assert isinstance(fiber, Fiber)
        fiber._make_delegated()
        self._calls.append(fiber)
        return self

    def add_callbacks(self, callback=None, errback=None,
                      cbargs=None, cbkws=None,
                      ebargs=None, ebkws=None):
        self._check_not_started()

        record = (callback, errback, cbargs, cbkws, ebargs, ebkws)

        self._calls.append(record)

        return self

    def add_callback(self, callback, *args, **kwargs):
        return self.add_callbacks(callback, cbargs=args, cbkws=kwargs)

    def add_errback(self, errback, *args, **kwargs):
        return self.add_callbacks(errback=errback, ebargs=args, ebkws=kwargs)

    def add_both(self, callback, *args, **kwargs):
        return self.add_callbacks(callback, callback,
                                  cbargs=args, cbkws=kwargs,
                                  ebargs=args, ebkws=kwargs)

    ### Protected Methods, called only by other instances of Fiber ###

    def _bind(self, desc, fiber_id, fiber_depth):
        if self._descriptor is not None:
            if self._descriptor == desc:
                # Already attached
                return False
            raise FiberError("Fiber already attached to another descriptor")

        self._descriptor = desc
        self.fiber_id = fiber_id
        self.fiber_depth = fiber_depth
        return True

    def _make_delegated(self):
        self._delegated_startup = True

    def _snapshot_callbacks(self):
        result = []
        for record in self._calls:
            if isinstance(record, tuple):
                cb, eb, cba, cbk, eba, ebk = record
                dump = self._serialize_callbacks(cb, eb, cba, cbk, eba, ebk)
                result.append(dump)
            else:
                result.extend(record._snapshot_callbacks())
        return result

    def _ensure_descriptor(self):
        descriptor = None
        if self.fiber_id is None:
            # If not attached, creates a root descriptor and attach it.
            # Useful to use fiber directly without decorators.
            descriptor = RootFiberDescriptor()
            descriptor.attach(self)

    def _check_not_started(self):
        if self._started:
            raise FiberStartupError("Fiber already started")

    def _prepare(self, d):
        self._started = True

        for record in self._calls:
            if isinstance(record, tuple):
                cb, eb, cba, cbk, eba, ebk = record
                # Wrap the callbacks
                cb, cba, cbk = self._wrap_callback(cb, cba, cbk)
                eb, eba, ebk = self._wrap_callback(eb, eba, ebk)
                # Add the callbacks
                d.addCallbacks(cb, eb, cba, cbk, eba, ebk)
            else:
                # If the chained fiber have been triggered, it will start
                # with the triggered type and param, otherwise it will
                # be started in function of the result of the parent fiber.
                ct = record.trigger_type
                cp = record.trigger_param
                # Prepare the deferred chain to be started
                # at the chaining point
                cd = record._prepare(defer.Deferred())
                d.addCallbacks(self._on_chain_cb, self._on_chain_cb,
                               callbackArgs=(ct, cp, cd, TriggerType.succeed),
                               errbackArgs=(ct, cp, cd, TriggerType.fail))

        return d

    def _fire(self, d, trigger, param=None,
              default_trigger=None, default_param=None):
        if trigger is None:
            trigger = default_trigger
            param = default_param

        if trigger == TriggerType.succeed:
            d.callback(param)
        elif trigger == TriggerType.fail:
            d.errback(param)

        return d

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
        try:
            result = callback(value, *args, **kwargs)
            return section.exit(result)
        except:
            section.abort()
            raise

    def _serialize_callbacks(self, cb, eb, cba, cbk, eba, ebk):
        # FIXME: Should we deep clone ?
        cbd = None
        ebd = None
        if cb is not None:
            cbd = (cb, cba or None, cbk or None)
        if eb is not None:
            ebd = (eb, eba or None, ebk or None)
        return (cbd, ebd)

    def _on_chain_cb(self, parent_param, trigger, param, d, default_trigger):
        return self._fire(d, trigger, param, default_trigger, parent_param)


class FiberList(Fiber):
    '''List of fiber.
    Created with an iterator over instances implementing L{IFiber}.

    By default, the result passed to the first callback is a list of tuple
    (SUCCESS, VALUE) where SUCCESS is a bool anv VALUE is a fiber result
    if SUCCESS is True or a Failure instance if SUCCESS is False.

    Constructor parameters can alter this behaviour:

        if fireOnOneCallback is True, the first fiber returning a value
        will fire the FiberList execution with parameter a tuple with
        the value and the index of the fiber the result comes from.

        if fireOnOneErrback is True, the first fiber returning a failure
        will fire the FiberList errback with a L{defer.FirstError}.

    If sub-fibers are not triggered, they will be started in function
    of the state and result of the master fiber.

    Example:

          def show(result, header):
          print header, result
          return result

          f1 = Fiber()
          f1.addCallback(show, "Fiber 1:")
          f1.succeed("F1") # f1 IS triggered

          f2 = Fiber()
          f2.addCallback(show, "Fiber 2:")
          # f2 IS NOT triggered

          fl = FiberList([f1, f2])
          fl.succeed("FL")

          >> Fiber 1: F1
          >> Fiber 2: FL
    '''

    implements(IFiber, ISnapshotable)

    def __init__(self, fibers, fireOnOneCallback=False,
                 fireOnOneErrback=False, consumeErrors=False):
        """Initialize a FiberList.

        @param fibers: an iterator over a collection of L{IFiber}.
        @type fibers:  iterable
        @param fireOnOneCallback: a flag indicating that only one callback
                                  needs to be fired for me to call my callback
        @param fireOnOneErrback: a flag indicating that only one errback needs
                                 to be fired for me to call my errback
        @param consumeErrors: a flag indicating that any errors raised
                              in the original fibers should be consumed
                              by this FiberList.  This is useful to prevent
                              spurious warnings being logged.
        """
        Fiber.__init__(self)
        self._fibers = list(fibers)
        self._fire_on_first_cb = fireOnOneCallback
        self._fire_on_first_eb = fireOnOneErrback
        self._consume_errors = consumeErrors

    ### serialization.ISnapshotable Methods ###

    def snapshot(self):
        return (self.trigger_type, self.trigger_param,
                [f.snapshot() for f in self._fibers])

    ### Protected Methods, called only by other instances of Fiber ###

    def _bind(self, desc, fiber_id, fiber_depth):
        # Bind sub fibers
        if Fiber._bind(self, desc, fiber_id, fiber_depth):
            for f in self._fibers:
                f._bind(desc, fiber_id, fiber_depth)
            return True
        return False

    def _prepare(self, d):
        self._started = True

        items = []

        # Start all fibers with there own Deferred and
        for fiber in self._fibers:
            # Check the fiber is not started
            fiber._check_not_started()
            # Prepare the deferred chain to be started when
            # the deferred specified as parameter is started
            fd = fiber._prepare(defer.Deferred())
            item = (fiber.trigger_type, fiber.trigger_param, fd)
            items.append(item)

        fld = Fiber._prepare(self, defer.Deferred())

        return d.addCallbacks(self._on_callback, self._on_callback,
                              callbackArgs=(items, fld, TriggerType.succeed),
                              errbackArgs=(items, fld, TriggerType.fail))

    ### Private Methods ###

    def _on_callback(self, parent_param, items, fld, default_trigger):
        deferreds= []

        for trigger, param, d in items:
            deferreds.append(d)
            self._fire(d, trigger, param, default_trigger, parent_param)

        dl = defer.DeferredList(deferreds,
                                fireOnOneCallback=self._fire_on_first_cb,
                                fireOnOneErrback=self._fire_on_first_eb,
                                consumeErrors=self._consume_errors)

        def chain_callback(r, d):
            d.callback(r)
            return d

        def chain_errback(r, d):
            d.errback(r)
            return d

        args = (fld, )
        dl.addCallbacks(chain_callback, chain_errback,
                        callbackArgs=args, errbackArgs=args)

        return dl
