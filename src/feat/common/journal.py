from twisted.internet import defer
from twisted.python import components
from zope.interface import implements

from feat.interface import journaling, async
from feat.interface.journaling import JournalMode

from . import decorator, fiber


class RecordResultError(Exception):
    pass


@decorator.parametrized
def recorded(function, entry_id=None):
    fixed_id = entry_id or function.__name__

    def fiber_wrapper(self, result, fiber, _original, *args, **kwargs):
        return self._call_recorded(fiber, fixed_id, function,
                                   result, *args, **kwargs)

    def direct_wrapper(self, *args, **kwargs):
        return self._call_recorded(None, fixed_id, function, *args, **kwargs)

    fiber.set_alternative(direct_wrapper, fiber_wrapper)

    return direct_wrapper


class RecordInput(object):

    implements(journaling.IRecordInput)

    def __init__(self, args, kwargs):
        self.args = args
        self.kwargs = kwargs

    ### serialization.ISnapshot ###

    def snapshot(self, context={}):
        return self.args, self.kwargs


class RecordAsyncOutput(object):

    implements(journaling.IRecordOutput)

    def __init__(self, fiber):
        self._fiber = fiber

    ### serialization.ISnapshot ###

    def snapshot(self, context={}):
        return "async", self._fiber.snapshot()


class RecordSyncOutput(object):

    implements(journaling.IRecordOutput)

    def __init__(self, output):
        self._output = output

    ### serialization.ISnapshot ###

    def snapshot(self, context={}):
        return "sync", self._output


class InvalidResult(object):

    implements(journaling.IRecordingResult)

    def __init__(self, result):
        raise RecordResultError("Recorded function result invalid: %r" %\
                                result)

components.registerAdapter(InvalidResult,
                           defer.Deferred,
                           journaling.IRecordingResult)


class RecordingAsyncResult(object):

    implements(journaling.IRecordingResult)

    def __init__(self, fiber):
        self.output = RecordAsyncOutput(fiber)
        self._fiber = fiber

    ### IRecordingResult Methods ###

    def nest(self, fiber):
        return self._fiber.nest(fiber)

    def proceed(self):
        return self._fiber.run()

components.registerAdapter(RecordingAsyncResult,
                           async.IFiber,
                           journaling.IRecordingResult)


class RecordingSyncResult(object):

    implements(journaling.IRecordingResult)

    def __init__(self, value):
        self._value = value
        self.output = RecordSyncOutput(value)

    ### IRecordingResult Methods ###

    def nest(self, fiber):
        pass

    def proceed(self):
        return self._value

components.registerAdapter(RecordingSyncResult,
                           object,
                           journaling.IRecordingResult)


class RecorderRoot(object):

    implements(journaling.IRecorderNode)

    journal_parent = None

    def __init__(self, keeper, mode=JournalMode.recording, base_id=None):
        self.journal_keeper = journaling.IJournalKeeper(keeper)
        self.journal_mode = mode
        self._base_id = base_id and (base_id, ) or ()
        self._recorder_count = 0

    ### IRecorderNode Methods ###

    def generate_identifier(self, recorder):
        self._recorder_count += 1
        return self._base_id + (self._recorder_count, )


class RecorderNode(object):

    implements(journaling.IRecorderNode)

    def __init__(self, parent):
        node = journaling.IRecorderNode(parent)
        identifier = node.generate_identifier(self)
        self.journal_parent = node
        self.journal_id = identifier
        self.journal_keeper = node.journal_keeper
        self.journal_mode = node.journal_mode
        self._recorder_count = 0

    ### IRecorderNode Methods ###

    def generate_identifier(self, recorder):
        self._recorder_count += 1
        return self.journal_id + (self._recorder_count, )


class Recorder(RecorderNode):

    implements(journaling.IRecorder)

    def __init__(self, parent):
        RecorderNode.__init__(self, parent)
        # Bind the _call_recorded method depending on the journal mode
        if self.journal_mode == JournalMode.recording:
            self._call_recorded = self._record_call
        elif self.journal_mode == JournalMode.replay:
            self._call_recorded = self._replay_call
        else:
            raise RuntimeError("Unsupported journal mode")
        # Register the recorder
        self.journal_keeper.register(self)

    ### IRecorder Methods ###

    def replay(self, entry_id, args, kwargs):
        pass

    ### Private Methods ###

    def _record_call(self, fiber, entry_id, method, *args, **kwargs):
        input = RecordInput(args, kwargs)

        result = method(self, *args, **kwargs)
        recres = journaling.IRecordingResult(result)
        recres.nest(fiber)

        output = recres.output
        self.journal_keeper.record(self.journal_id, entry_id,
                                   None, None, input, output)

        return recres.proceed()

    def _replay_call(self, entry_id, method, *args, **kwargs):
        pass


class FileJournalRecorder(object):

    implements(journaling.IJournalKeeper)

    ### IJournalKeeper Methods ###

    def register(self, recorder):
        '''No registration needed for recording.'''

    def record(self, instance_id, entry_id,
               fiber_id, fiber_depth, input, output):
        pass
