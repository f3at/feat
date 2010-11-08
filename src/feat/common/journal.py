from zope.interface import implements

from feat.interface import journaling
from feat.interface.journaling import JournalMode

from . import persistence, annotate


## Decorators ###

def recorded(entry_id=None):

    def decorator(method):
        fixed_id = entry_id or method.__name__

        # Register the method as recorded call
        annotate.injectClassCallback("recorded",
                                     "_register_recorded_call",
                                     fixed_id, method)

        def wrapper(self, *args, **kwargs):
            return self._call_recorded(fixed_id, method, *args, **kwargs)

        return wrapper

    return decorator


class RecordInput(persistence.Snapshot):

    implements(journaling.IRecordInput)

    def __init__(self, args, kwargs):
        self.args = args
        self.kwargs = kwargs


class RecordOutput(persistence.Snapshot):

    implements(journaling.IRecordOutput)

    def __init__(self, fields):
        self.fields = fields


class RecordingResult(object):

    implements(journaling.IRecordingResult)


    def __init__(self, output):
        self.output = journaling.IRecordOutput(output)

    ### IRecordingResult Methods ###

    def proceed(self):
        pass


class RecorderRoot(object):

    implements(journaling.IRecorderNode)

    journal_parent = None

    def __init__(self, keeper, mode=JournalMode.normal, base_id=None):
        self.journal_keeper = journaling.IJournalKeeper(keeper)
        self.journal_mode = mode
        self._base_id = base_id and (base_id,) or ()
        self._recorder_count = 0

    ### IRecorderNode Methods ###

    def generate_identifier(self, recorder):
        self._recorder_count += 1
        return self._base_id + (self._recorder_count,)


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
        return self.journal_id + (self._recorder_count,)


class Recorder(RecorderNode, annotate.Annotable):

    implements(journaling.IRecorder)

    def __init__(self, parent):
        RecorderNode.__init__(self, parent)
        # Bind the _call_recorded method depending on the journal mode
        if self.journal_mode == JournalMode.normal:
            self._call_recorded = self._record_call
        elif self.journal_mode == JournalMode.replay:
            self._call_recorded = self._replay_call
        else:
            raise RuntimeError("Unsupported journal mode")

    def register_playback(self):
        pass

    ### IRecorder Methods ###

    def record(self, entry_id, input, output):
        self.journal_keeper.do_record(self.journal_id, entry_id, input, output)

    def replay(self, entry_id, args, kwargs):
        pass

    ### Private Methods ###

    @classmethod
    def _register_recorded_call(cls, entry_id, method):
        pass

    def _record_call(self, method, entry_id, *args, **kwargs):
        input = RecordInput(args, kwargs)
        result = method(self, *args, **kwargs)
        recres = journaling.IRecordingResult(result)
        output = recres.output
        self.journal_keeper.record(self.journal_id, entry_id, input, output)
        return recres.proceed()

    def _replay_call(self, method, entry_id, *args, **kwargs):
        pass


class FileJournalKeeper(object):

    implements(journaling.IJournalKeeper)

    ### IJournalKeeper Methods ###

    def record(self, instance_id, entry_id, args, kwargs, results):
        pass


class JournalPlayer(object):

    implements(journaling.IJournalPlayer)

    ### IJournalPlayer Methods ###

    def register(self, recorder):
        pass
