from zope.interface import Interface, Attribute

from feat.common import enum

__all__ = ["JournalMode", "RecordingResultError", "SideEffectResultError",
           "ReentrantCallError", "ReplayError",
           "IJournalKeeper", "IJournalEntry", "IJournalReplayEntry",
           "IJournalSideEffect", "IEffectHandler",
           "IRecorderNode", "IRecorder"]


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


class IJournalSideEffect(Interface):
    '''Represent a side-effect description in a journal entry.'''

    def add_effect(effect_id, *args, **kwargs):
        pass

    def set_result(result):
        pass

    def commit():
        pass


class IJournalReplayEntry(Interface):

    journal_id = Attribute("Instance journal identifier. Read only.")
    function_id = Attribute("Function identifier. Read only.")
    fiber_id = Attribute("Fiber unique identifier. Read only.")
    fiber_depth = Attribute("Fiber depth. Read only.")
    frozen_result = Attribute("Frozen result. Read only.")

    def get_arguments():
        pass

    def get_result():
        pass

    def rewind_side_effects():
        pass

    def next_side_effect(function_id, *args, **kwargs):
        '''Returns the next side-effect result. Used during replay.
        If the parameter do not match the expected ones it could fail.'''


class IJournalEntry(Interface):
    '''Represent an entry in the journal. Every set_* method must be called
    before calling commit().'''

    def set_fiber_context(self, fiber_id, fiber_depth):
        pass

    def new_side_effect(function_id, *args, **kwargs):
        '''Returns a L{IJournalSideEffect} on witch the set_result()
        method should be called, and then commit().'''

    def set_result(result):
        pass

    def commit():
        '''Commit the entry to the journal. The order of the entries
        is not determined by the commit order but by the creation order.'''


class IEffectHandler(Interface):
    '''Used for journal keeper to delegate side-effects effect.'''

    def apply_effect(self, effect_id, *args, **kwargs):
        pass


class IJournalKeeper(Interface):
    '''Store journal entries'''

    def register(recorder):
        '''Adds the specified recorder to the journal keeper registry.
        Should be called by every recorder when created.
        Recorder will be automatically unregistered when they are deleted,
        The journal keeper do not keep strong reference to the recorders.'''

    def new_entry(journal_id, function_id, *args, **kwargs):
        '''Creates a new journal entry. Returns a L{IJournalEntry} that should
        be committed for the entry to be recorded.
        The order of journal entry is determined when calling new_entry()
        and the content is determined when committing it.'''


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
