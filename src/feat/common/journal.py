from zope.interface import implements

from feat.interface import journaling
from feat.interface.journaling import JournalMode

from . import persistence


class RecordInput(persistence.Serializable):

    implements(journaling.IRecordInput)

    def __init__(self, args, kwargs):
        self.args = args
        self.kwargs = kwargs


class RecordOutput(persistence.Serializable):

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


class Recorder(RecorderNode):

    implements(journaling.IRecorder)

    def __init__(self, parent):
        RecorderNode.__init__(self, parent)

    ### IRecorder Methods ###

    def record(self, entry_id, input, output):
        self.journal_keeper.do_record(self.journal_id, entry_id, input, output)

    def replay(self, entry_id, args, kwargs):
        pass


class FileJournalKeeper(object):

    implements(journaling.IJournalKeeper)

    ### IJournalKeeper Methods ###

    def do_record(self, instance_id, entry_id, args, kwargs, results):
        pass


class JournalPlayer(object):

    implements(journaling.IJournalPlayer)

    ### IJournalPlayer Methods ###

    def register(self, recorder):
        pass
