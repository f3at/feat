
from feat.common import decorator, annotate, serialization, guard, journal

from feat.interface.journal import *


@decorator.simple_function
def mutable(function):
    '''Combined decorator of guarded.mutable and journal.recorded.
    Same as using::

      @journal.recorded()
      @guard.mutable
      def spam(self, state, some, args):
          pass
    '''

    fun_id = function.__name__
    # Register the function
    annotate.injectClassCallback("recorded", 4,
                                 "_register_recorded_call",
                                 fun_id, function)

    def wrapper(self, *args, **kwargs):
        state = self._get_state()
        recorder = IRecorder(self)
        return recorder.call(fun_id, (state, ) + args, kwargs)

    return wrapper

# Copy immutable decorator from guarded
immutable = guard.immutable


# Fix the metaclass inheritance
MetaReplayable = type("MetaReplayable", (annotate.MetaAnnotable,
                                         serialization.MetaSerializable), {})


class Replayable(journal.Recorder, guard.Guarded):

#    __metaclass__ = MetaReplayable

    def __init__(self, parent, *args, **kwargs):
        journal.Recorder.__init__(self, parent)
        guard.Guarded.__init__(self, parent, *args, **kwargs)
