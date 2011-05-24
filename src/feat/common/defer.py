from twisted.internet.defer import *
from twisted.internet.defer import returnValue, passthru


def drop_result(_result, _method, *args, **kwargs):
    assert callable(_method)
    return _method(*args, **kwargs)


def bridge_result(_result, _method, *args, **kwargs):
    assert callable(_method)
    d = maybeDeferred(_method, *args, **kwargs)
    d.addCallback(override_result, _result)
    return d


def override_result(_result, _new_result):
    return _new_result


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
