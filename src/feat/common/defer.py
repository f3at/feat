from twisted.internet.defer import *
from twisted.internet.defer import returnValue


def drop_result(result, method, *args, **kwargs):
    assert callable(method)
    return method(*args, **kwargs)


def bridge_result(result, method, *args, **kwargs):
    assert callable(method)
    method(*args, **kwargs)
    return result


def override_result(result, new_result):
    return new_result


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
