from twisted.internet.defer import *


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
