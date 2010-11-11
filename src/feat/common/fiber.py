import types
import uuid

from twisted.internet import defer
from zope.interface import implements

from feat.interface.fiber import IFiber

from . import reflect

### Decorator ###


def nested(fun):
    '''Decorator that will start and nest fibers.'''

    def alt(result, fiber, original, *args, **kwargs):
        result = original(result, *args, **kwargs)
        if IFiber.providedBy(result):
            child_fiber = IFiber(result)
            child_fiber.nest(fiber)
            return child_fiber.start()
        return result

    return set_alternative(fun, alt)


def set_alternative(orig, alt):
    '''Set the fiber-aware alternative for a callable.
    When a fiber call a function with an alternative,
    it will call the alternative with itself as the second argument
    and the original function as the third argument.'''
    if not isinstance(alt, types.FunctionType):
        raise RuntimeError("Only functions are supported for "
                           "alternative: %r", alt)
    ns = _get_callable_namespace(orig)
    setattr(ns, "__fiber_call__", alt)
    return orig


def remove_alternative(orig):
    '''Remove the callable alternative if it has been set.'''
    ns = _get_callable_namespace(orig)
    if hasattr(ns, "__fiber_call__"):
        delattr(ns, "__fiber_call__")
    return orig


def has_alternative(orig):
    ns = _get_callable_namespace(orig)
    return hasattr(ns, "__fiber_call__")


def get_alternative(orig):
    ns = _get_callable_namespace(orig)
    return getattr(ns, "__fiber_call__", None)


class Fiber(object):
    '''Fibers are used to specify a chain of asynchronous execution.

    Fibers can be nested to follow the string of execution.
    Nested fibers have the same fiber identifier but sub-fibers
    have its depth incremented.

    If an alternate function or method has been set for a function
    or a method, the alternative will be called in place of the
    callback given to addCallback with the fiber as an extra parameter.
    This could be use to automatically chain the fibers.
    '''

    implements(IFiber)

    def __init__(self):
        self._succeed = None
        self._param = None
        self._deferred = defer.Deferred()
        self._state_calls = []
        self.fiber_depth = 0

    def __getattr__(self, attr):
        '''Lazily creates IFiber attribute if it has not been set before'''
        if attr == "fiber_id":
            fiber_id = str(uuid.uuid4())
            self.__dict__["fiber_id"] = fiber_id
            return fiber_id
        raise AttributeError("'%s' object has no attribute '%s'"
                             % (type(self).__name__, attr))


    ### serialization.ISnapshot Methods ###

    def snapshot(self, context={}):
        # FIXME: Should we deep clone ?
        return self._succeed, self._param, self._state_calls

    ### IFiber Methods ###

    def nest(self, parent):
        parent = IFiber(parent)
        self.fiber_id = parent.fiber_id
        self.fiber_depth = parent.fiber_depth + 1

    def start(self):
        if self._succeed:
            self._deferred.callback(self._param)
        else:
            self._deferred.errback(self._param)
        return self._deferred

    def succeed(self, param=None):
        if self._succeed is not None:
            raise RuntimeError("Fiber trigger already set")
        self._succeed = True
        self._param = param
        return self

    def fail(self, failure=None):
        if self._succeed is not None:
            raise RuntimeError("Fiber trigger already set")
        self._succeed = False
        self._param = failure
        return self

    def addCallbacks(self, callback=None, errback=None,
                     callbackArgs=None, callbackKeywords=None,
                     errbackArgs=None, errbackKeywords=None):
        callbackName = reflect.canonical_name(callback)
        errbackName = reflect.canonical_name(errback)
        call = (callbackName, callbackArgs or None, callbackKeywords or None,
                errbackName, errbackArgs or None, errbackKeywords or None)
        self._state_calls.append(call)

        ucb = self._update_call(callback, callbackArgs, callbackKeywords)
        ueb = self._update_call(errback, errbackArgs, errbackKeywords)

        cb, cba, cbk = ucb
        eb, eba, ebk = ueb

        # Deferred always need a callback
        cb = cb or defer.passthru

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

    ### Private Methods ###

    def _update_call(self, fun, args, kwargs):
        if fun is None:
            return None, None, None
        alt = get_alternative(fun)
        if alt is not None:
            return alt, (self, fun) + args, kwargs
        return fun, args, kwargs


### Private Functions ###


def _get_callable_namespace(callable):
    '''Returns a writable namespace unique for a callable.
    Only support functions and methods.'''
    if isinstance(callable, types.MethodType):
        return callable.im_func
    if isinstance(callable, types.FunctionType):
        return callable
    raise RuntimeError("Unsupported callable: %r" % callable)
