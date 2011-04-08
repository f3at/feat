from twisted.internet.defer import *
from twisted.internet.defer import returnValue


def drop_result(_result, _method, *args, **kwargs):
    assert callable(_method)
    return _method(*args, **kwargs)


def bridge_result(_result, _method, *args, **kwargs):
    assert callable(_method)
    _method(*args, **kwargs)
    return _result


def override_result(_result, _new_result):
    return _new_result


class Notifier(object):

    def __init__(self):
        self._notifications = {}

    def wait(self, notification):
        if notification not in self._notifications:
            self._notifications[notification] = []
        d = Deferred()
        self._notifications[notification].append(d)
        return d

    def callback(self, notification, result):
        if notification in self._notifications:
            notifications = self._notifications.pop(notification)
            for d in notifications:
                d.callback(result)

    def errback(self, notification, failure):
        if notification in self._notifications:
            notifications = self._notifications.pop(notification)
            for d in notifications:
                d.errback(failure)
