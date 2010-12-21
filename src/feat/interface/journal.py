from zope.interface import Interface, Attribute

from feat.common import enum

__all__ = ["JournalMode", "RecordingResultError", "SideEffectResultError",
           "ReentrantCallError", "ReplayError",
           "IJournalKeeper", "IRecorderNode", "IRecorder"]


class JournalMode(enum.Enum):
    recording, replay = range(1, 3)


class RecordingResultError(RuntimeError):
    pass


class SideEffectResultError(RuntimeError):
    pass


class ReentrantCallError(RuntimeError):
    pass


class ReplayError(RuntimeError):
    pass


class IJournalKeeper(Interface):
    '''Store journal entries'''

    def register(recorder):
        '''Adds the specified recorder to the journal keeper registry.
        Should be called by every recorder when created.
        Recorder will be automatically unregistered when they are deleted,
        The journal keeper do not keep strong reference to the recorders.'''

    def write_entry(instance_id, entry_id, fiber_id, fiber_depth,
                    input, side_effects, output):
        pass


class IRecorderNode(Interface):

    journal_parent = Attribute('Parent recorder node, L{IRecorderNode} or '
                               'None for the root node')
    journal_keeper = Attribute('Journal keeper to use, L{IJournalKeeper}')

    def generate_identifier(recorder):
        pass


class IRecorder(IRecorderNode):

    journal_id = Attribute('Journal recorder identifier, tuple of int')

    def call(function, args=None, kwargs=None, reentrant=True):
        '''Calls the specified function with arguments and keywords.
        The function have to be the exact registered one, and because
        the decorators are wrapping it inside another function
        calling this method with the instance function will not work.
        If reentrant is False and we already are inside
        a recorded call it will fail with a L{ReentrantCallError}.
        Returns the result of the called function as returned
        by the fiber section.'''

    def record(function, args=None, kwargs=None, reentrant=True):
        '''Calls the function with specified identifier, arguments
        and keywords. If reentrant is False and we already are inside
        a recorded call it will fail with a L{ReentrantCallError}.
        Returns the result of the called function as returned
        by the fiber section.'''

    def replay(fun_id, input):
        '''Calls the function with specified identifier with specified
        input. Input is what was given as a parameter when calling
        IJournalKeeper.record().
        Returns a tuple containing the side effects and the output
        of the function call but do NOT start any asynchronous operation.'''
