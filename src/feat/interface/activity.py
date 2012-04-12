from feat.common import error

from zope.interface import Interface, Attribute


class IActivity(Interface):

    description = Attribute("C{unicode} Explanation of the activity")
    started = Attribute("C{bool} flag saying if the activity is already "
                        "started")
    done = Attribute("C{bool} flag saying if the activity is "
                     "finished and can be removed")
    busy = Attribute("C{bool} flag saying if this activity should count "
                     "towards not being idle. Nonbusy calls are also "
                     "cancelled during the terminate() call.")

    def cancel():
        '''Stops/cancels the activity.'''

    def notify_finish():
        '''Returns a Deferred which will fire after this activity finished.'''


class IActivityManager(Interface):
    """
    Interface implemented by the classes tracking their activity.
    """

    description = Attribute("C{unicode} description of the component this "
                            "manager tracks the activity for.")
    terminated = Attribute("C{bool} flag saying that the manager is already "
                           "terminated and can be removed from tracking by "
                           "his activity parent")
    idle = Attribute("C{bool} flag saying if we have any activity scheduled")

    def track(activity, description=None):
        """
        Tracks the activity.
        @param description: optional description to override
        @type activity: L{IActivity}
        @return: uid which later can be used to retrieve the activity
        @rtype: C{unicode}
        """

    def wait_for_idle():
        """
        Returns a Deferred which will fire when the component gets idle.
        @rtype: C{Deferred}
        """

    def register_child(child, description=None):
        """
        Adds a activity child. Activity of children makes the parent not idle.
        @param description: optional description to override
        @type child: L{IActivityManager}
        """

    def terminate():
        """
        Calls terminate on all the children and waits to become idle.
        Finally it sets the terminated flag to True.
        @rtype: C{Deferred} which will fire when we are done
        """

    def iteractivity():
        """
        Returns a generator yielding IActivity of the manager and its children.
        """

    def iterownactivity():
        """
        Returns a generator yielding IActivity of the manager
        (without children).
        """

    def iterchildren():
        """
        Returns a generator yielding IActivityManager of the children.
        """

    def get(uid):
        """
        Get IActivity by its uid.
        """


class IActivityComponent(Interface):
    """
    Interface implemented by components tracking their activity.
    """

    activity = Attribute("L{IActivityManager}")


class AlreadyTerminatedError(error.FeatError):
    """
    Error raised when someone tries to add the activity of child on already
    terminated element.
    """
