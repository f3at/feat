from feat.common import (decorator, annotate, guard, journal, )

from feat.interface.journal import *


@decorator.simple_function
def mutable(function):
    '''Combined decorator of guarded.mutable and journal.recorded.

    When called from outside a recording context, it returns a Deferred.
    When called from inside a recording context, it returns a L{fiber.Fiber}
    or any synchronous value.

    Same as using::

      @journal.recorded()
      @guard.mutable
      def spam(self, state, some, args):
          pass
    '''

    guard_wrapper = guard.mutable(function)

    # Register the function
    annotate.injectClassCallback("recorded", 4,
                                 "_register_recorded_call", guard_wrapper)

    def wrapper(self, *args, **kwargs):
        recorder = IRecorder(self)
        return recorder.call(guard_wrapper, args, kwargs)

    return wrapper


@decorator.simple_function
def entry_point(function):
    '''Combined decorator of guarded.mutable and journal.recorded
    that ensure the call is not reentrant.

    If a function decorated with it is called from inside a recording
    context it will raise L{f.i.j.ReentrantCallError}.

    Because the function cannot be called from inside a recording context,
    it always returns a Deferred.

    Same as using::

      @journal.recorded(reentrant=False)
      @guard.mutable
      def spam(self, state, some, args):
          pass
    '''

    # Register the function
    annotate.injectClassCallback("recorded", 4,
                                 "_register_recorded_call", function)

    def wrapper(self, *args, **kwargs):
        state = self._get_state()
        recorder = IRecorder(self)
        return recorder.call(function, (state, ) + args,
                             kwargs, reentrant=False)

    return wrapper


# Copy immutable decorator as-is from guarded module
immutable = guard.immutable
journaled = mutable
side_effect = journal.side_effect
named_side_effect = journal.named_side_effect


# Copy the replay function for calling methods in replay context
replay = journal.replay


class Replayable(journal.Recorder, guard.Guarded):

    def __init__(self, parent, *args, **kwargs):
        journal.Recorder.__init__(self, parent)
        guard.Guarded.__init__(self, parent, *args, **kwargs)

    def snapshot(self):
        return journal.Recorder.snapshot(self), guard.Guarded.snapshot(self)

    def recover(self, snapshot):
        s1, s2 = snapshot
        journal.Recorder.recover(self, s1)
        guard.Guarded.recover(self, s2)
