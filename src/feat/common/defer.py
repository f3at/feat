import warnings

from twisted.internet.defer import *
from twisted.internet.defer import returnValue, passthru, setDebugging

from feat.common import log

from feat.interface.log import *


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


def debug(_param, _template="", *args):
    log.logex("defer", LogLevel.debug, _template, args, log_name="debug")
    return _param


def trace(_param, _template="", *args):
    prefix = _template % args
    prefix = prefix + ": " if prefix else prefix
    message = "%s%r" % (prefix, _param)
    log.logex("defer", LogLevel.debug, message, log_name="trace")
    return _param


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
