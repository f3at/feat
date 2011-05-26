import warnings

from twisted.internet.defer import *
from twisted.internet.defer import returnValue, passthru, setDebugging
from twisted.python import failure

from feat.common import log, decorator

from feat.interface.log import *
from feat.interface.fiber import *


def drop_result(_result, _method, *args, **kwargs):
    warnings.warn("defer.drop_result() is deprecated, "
                  "please use defer.drop_param()",
                  DeprecationWarning)
    assert callable(_method), "method %r is not callable" % (_method, )
    return _method(*args, **kwargs)


def bridge_result(_result, _method, *args, **kwargs):
    warnings.warn("defer.bridge_result() is deprecated, "
                  "please use defer.bridge_param()",
                  DeprecationWarning)
    assert callable(_method), "method %r is not callable" % (_method, )
    d = maybeDeferred(_method, *args, **kwargs)
    d.addCallback(override_result, _result)
    return d


def drop_param(_param, _method, *args, **kwargs):
    assert callable(_method), "method %r is not callable" % (_method, )
    return _method(*args, **kwargs)


def bridge_param(_param, _method, *args, **kwargs):
    assert callable(_method), "method %r is not callable" % (_method, )
    d = maybeDeferred(_method, *args, **kwargs)
    d.addCallback(override_result, _param)
    return d


def call_param(_param, _attr_name, *args, **kwargs):
    _method = getattr(_param, _attr_name, None)
    assert _method is not None, \
           "%r do not have attribute %s" % (_param, _attr_name, )
    assert callable(_method), "method %r is not callable" % (_method, )
    return _method(*args, **kwargs)


def inject_param(_param, _index, _method, *args, **kwargs):
    assert callable(_method), "method %r is not callable" % (_method, )
    args = args[:_index] + (_param, ) + args[_index:]
    return _method(*args, **kwargs)


def override_result(_param, _result):
    return _result


def print_debug(_param, _template="", *args):
    print _template % args
    return _param


def print_trace(_param, _template="", *args):
    prefix = _template % args
    prefix = prefix + ": " if prefix else prefix
    print "%s%r" % (prefix, _param)
    return _param


def debug(_param, _template="", *args):
    log.logex("defer", LogLevel.debug, _template, args, log_name="debug")
    return _param


def trace(_param, _template="", *args):
    prefix = _template % args
    prefix = prefix + ": " if prefix else prefix
    message = "%s%r" % (prefix, _param)
    log.logex("defer", LogLevel.debug, message, log_name="trace")
    return _param


def maybeDeferred(f, *args, **kw):
    """
    Copied from twsited.internet.defer and add a check to detect fibers.
    """
    try:
        result = f(*args, **kw)
    except Exception:
        return fail(failure.Failure())

    if IFiber.providedBy(result):
        import traceback
        frames = traceback.extract_stack()
        msg = "%s returned a fiber instead of a deferred" % (f, )
        if len(frames) > 1:
            msg += "; called from %s" % (frames[-2], )
        raise RuntimeError(msg)

    if isinstance(result, Deferred):
        return result
    elif isinstance(result, failure.Failure):
        return fail(result)
    else:
        return succeed(result)


@decorator.simple_function
def ensure_async(function_original):
    """
    A function decorated with this will always return a defer.Deferred
    even when returning synchronous result or raise an exception.
    """

    def wrapper(*args, **kwargs):
        try:
            result = function_original(*args, **kwargs)
            if isinstance(result, Deferred):
                return result
            d = Deferred()
            d.callback(result)
            return d
        except:
            return fail()

    return wrapper


class Notifier(object):

    def __init__(self):
        self._notifications = {}

    def wait(self, notification):
        d = Deferred()
        self._store(notification, d)
        return d

    def callback(self, notification, result):
        notifications = self._pop(notification)
        if notifications:
            for d in notifications:
                d.callback(result)

    def errback(self, notification, failure):
        notifications = self._pop(notification)
        if notifications:
            for d in notifications:
                d.errback(failure)

    def _store(self, notification, d):
        if notification not in self._notifications:
            self._notifications[notification] = []
        self._notifications[notification].append(d)

    def _pop(self, notification):
        if notification in self._notifications:
            return self._notifications.pop(notification)
