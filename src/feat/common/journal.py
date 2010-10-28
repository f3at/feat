import uuid

from zope.interface import implements

from feat.interface import journaling


class RecordInput(object):

    implements(journaling.IRecordInput)

    def __init__(self, args, kwargs):
        self.args = args
        self.kwargs = kwargs

    ### ISerializable Methods ###

    type_name = "record-input"

    def __restore__(self, snapshot, context):
        self.args, self.kwargs = snapshot

    def snapshot(self, context):
        return self.args, self.kwargs


class RecordOutput(object):

    implements(journaling.IRecordOutput)

    def __init__(self, fields):
        self.fields = fields

    ### ISerializable Methods ###

    type_name = "record-output"

    def __restore__(self, snapshot, context):
        self.fields = snapshot

    def snapshot(self, context):
        return self.fields


class RecordingResult(object):

    implements(journaling.IRecordingResult)


    def __init__(self, output):
        self.output = journaling.IRecordOutput(output)

    ### IRecordingResult Methods ###

    def proceed(self):
        pass


class Recorder(object):

    implements(journaling.IRecorder)

    def __init__(self, journal_keeper):
        self._jkeeper = journaling.IJournalKeeper(journal_keeper)
        self.identify(str(uuid.uuid1()))

    ### IRecorder Methods ###

    def identify(self, instance_id):
        self._instance_id = instance_id

    def record(self, entry_id, input, output):
        self._jkeeper.do_record(self._instance_id, entry_id, input, output)

    def replay(self, entry_id, args, kwargs):
        pass


class FileJournalKeeper(object):

    implements(journaling.IJournalKeeper)

    ### IJournalKeeper Methods ###

    def do_record(self, instance_id, entry_id, args, kwargs, results):
        pass


class JournalProxy(object):

    implements(journaling.IJournalKeeper)

    ### IJournalKeeper Methods ###

    def do_record(self, instance_id, entry_id, args, kwargs, results):
        pass


class JournalPlayer(object):

    implements(journaling.IJournalPlayer)

    ### IJournalPlayer Methods ###

    def register(self, recorder):
        pass



