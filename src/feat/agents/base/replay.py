
from feat.common import decorator, annotate, serialization, guard, journal

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

    # Register the function
    annotate.injectClassCallback("recorded", 4,
                                 "_register_recorded_call", function)

    def wrapper(self, *args, **kwargs):
        state = self._get_state()
        recorder = IRecorder(self)
        return recorder.call(function, (state, ) + args, kwargs)

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


class Replayable(journal.Recorder, guard.Guarded):

    def __init__(self, parent, *args, **kwargs):
        journal.Recorder.__init__(self, parent)
        guard.Guarded.__init__(self, parent, *args, **kwargs)
