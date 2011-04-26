from zope.interface import Attribute, Interface

from feat.interface import protocols

__all__ = ["ITaskFactory", "IAgencyTask", "IAgentTask", "NOT_DONE_YET"]


NOT_DONE_YET = "___not yet___"


class ITaskFactory(protocols.IInitiatorFactory):
    '''This class is used to create instances of a task
    implementing L{IAgentTask}. Used by the agency
    when initiating a task.'''


class IAgencyTask(Interface):
    '''Agency part of a task manager'''

    def finish(arg):
        '''
        Close the task in case the initiate() returned NOT_DONE_YET.
        @param arg: Trigger value for the tasks deferred.
        '''

    def fail(failure):
        '''
        Close the task with the error state in case the initiate() returned
        NOT_DONE_YET.
        @param failure: failure to errback the tasks deferred.
        '''

    def finished():
        '''
        Returns boolean saying if the task is still working.
        '''


class IAgentTask(protocols.IInitiator):
    '''Agent part of the task manager'''

    timeout = Attribute('Timeout')

    def initiate():
        '''
        Called as the entry point for the task. This method should return
        a Fiber. If the result of the fiber is NOT_DONE_YET, it will not
        finish right away.
        '''

    def expired():
        '''Called when the task has been not done
        before time specified with the L{timeout} attribute.'''
