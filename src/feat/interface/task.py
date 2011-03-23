from zope.interface import Attribute, Interface

from feat.interface import protocols

__all__ = ["ITaskFactory", "IAgencyTask", "IAgentTask"]


class ITaskFactory(protocols.IInitiatorFactory):
    '''This class is used to create instances of a task
    implementing L{IAgentTask}. Used by the agency
    when initiating a task.'''


class IAgencyTask(Interface):
    '''Agency part of a task manager'''


class IAgentTask(protocols.IInitiator):
    '''Agent part of the task manager'''

    timeout = Attribute('Timeout')

    def initiate():
        pass

    def expired():
        '''Called when the task has been not done
        before time specified with the L{timeout} attribute.'''
