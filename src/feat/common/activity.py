import uuid

from zope.interface import implements

from feat.common import adapter, defer, time, error

from feat.interface.activity import IActivity, IActivityManager
from feat.interface.activity import IActivityComponent, AlreadyTerminatedError


@adapter.register(IActivityComponent, IActivityManager)
def extract_manager(component):
    return component.activity


class Custom(object):
    '''Custom activity. It can be used for various things.'''

    implements(IActivity)

    def __init__(self, description=None, started=True, busy=True, done=False):
        self.description = description
        self.started = started
        self.busy = busy
        self._done = done

        self._notifier = defer.Notifier()

    @property
    def done(self):
        return self._done

    def cancel(self):
        self._done = True
        self._notifier.callback('done', None)

    def notify_finish(self):
        if self._done:
            return defer.succeed(None)
        return self._notifier.wait('done')


class CallLater(object):

    implements(IActivity)

    def __init__(self, timeleft, method,
                 args=tuple(), kwargs=dict(), description=None,
                 busy=True):
        assert callable(method), type(method)

        self._busy = busy
        self._call = time.callLater(timeleft,
                                    self._wrap, method, *args, **kwargs)
        self._done = False
        self.description = description
        self._notifier = defer.Notifier()

        if not self.description:
            self.description = method.__name__

    ### IActivity ###

    @property
    def started(self):
        return not self._call.active()

    @property
    def done(self):
        return self._done

    @property
    def busy(self):
        return self._busy

    def cancel(self):
        if not self.started:
            self._call.cancel()
            self._done = True
        else:
            self._defer.cancel()

    def notify_finish(self):
        if self._done:
            return defer.succeed(None)
        return self._notifier.wait('done')

    ### private ###

    def _wrap(self, _method, *args, **kwargs):
        d = defer.maybeDeferred(_method, *args, **kwargs)
        d.addErrback(self._errback)
        d.addBoth(defer.bridge_param, self._callback)
        self._defer = d

    def _errback(self, fail):
        if not fail.check(defer.CancelledError):
            error.handle_failure('activity', fail,
                                 "Delayed called desc: %r failed with:",
                                 self.description)

    def _callback(self):
        self._done = True
        self._notifier.callback('done', None)


@adapter.register(defer.Deferred, IActivity)
class DeferredActivity(object):

    implements(IActivity)

    def __init__(self, d):
        self._defer = d

        self.description = None
        self._done = False

        self._notifier = defer.Notifier()
        d.addBoth(defer.bridge_param, self._callback)

    ### IActivity ###

    @property
    def started(self):
        return True

    @property
    def done(self):
        return self._done

    @property
    def busy(self):
        return True

    def cancel(self):
        self._defer.cancel()

    def notify_finish(self):
        if self._done:
            return defer.succeed(None)
        return self._notifier.wait('done')

    ### private ###

    def _callback(self):
        self._done = True
        self._notifier.callback('done', None)


class ActivityManager(object):

    implements(IActivityManager)

    def __init__(self, description):
        self._description = unicode(description)
        # uuid -> IActivity
        self._activity = dict()
        self._children = list()
        self._terminated = False
        self._notifier = defer.Notifier()

    ### IActivityManager ###

    @property
    def description(self):
        return self._description

    @property
    def terminated(self):
        return self._terminated

    @property
    def idle(self):
        if self._is_idle_without_children():
            children_idle = all(x.idle for x in self.iterchildren())
            return children_idle
        return False

    def track(self, activity, description=None):
        self._fail_if_terminated()
        activity = IActivity(activity)
        if description is not None:
            activity.description = description
        uid = unicode(uuid.uuid1())
        self._activity[uid] = activity
        d = activity.notify_finish()
        d.addBoth(self._activity_finished, uid)
        return uid

    def wait_for_idle(self):
        if self.idle:
            return defer.succeed(self)
        defers = list()
        if not self._is_idle_without_children():
            defers.append(self._notifier.wait('idle_without_children'))
        defers.extend([x.wait_for_idle() for x in self.iterchildren()])
        d = defer.DeferredList(defers, consumeErrors=True)
        d.addBoth(defer.drop_param, self.wait_for_idle)
        return d

    def register_child(self, child):
        self._fail_if_terminated()
        child = IActivityManager(child)
        self._children.append(child)

    def terminate(self):
        for child in self.iterchildren():
            d = child.terminate()
            desc = "Waiting for %s to terminate" % (child.description, )
            self.track(d, desc)
        self._terminate_nonbusy_calls()

        d = self.wait_for_idle()
        d.addBoth(defer.bridge_param, self._terminate_nonbusy_calls)
        d.addBoth(defer.bridge_param, self._set_terminated)
        return d

    def iteractivity(self):
        for x in self.iterownactivity():
            yield x
        for child in self.iterchildren():
            for x in child.iteractivity():
                yield x

    def iterownactivity(self):
        self._lazy_cleanup_activity()
        return self._activity.itervalues()

    def iterchildren(self):
        self._lazy_cleanup_children()
        return iter(self._children)

    def get(self, uid):
        return self._activity.get(uid, None)

    ### private ###

    def _fail_if_terminated(self):
        if self.terminated:
            raise AlreadyTerminatedError("Tried to add activicy on already "
                                         "terminated instance.")

    def _terminate_nonbusy_calls(self):
        for activity in list(self.iterownactivity()):
            if not activity.busy and not activity.started:
                activity.cancel()

    def _set_terminated(self):
        self._terminated = True

    def _activity_finished(self, result, uid):
        del self._activity[uid]
        if self._is_idle_without_children():
            self._notifier.callback('idle_without_children', None)

    def _lazy_cleanup_activity(self):
        for uid, activity in self._activity.items():
            if activity.done:
                del self._activity[uid]

    def _lazy_cleanup_children(self):
        for child in list(self._children):
            if child.terminated:
                self._children.remove(child)

    def _is_idle_without_children(self):
        return all(not x.busy for x in self.iterownactivity())
