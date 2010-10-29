import uuid

from zope.interface import implements

from feat.interface import journaling

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


class RecorderNamer(object):

    implements(journaling.IRecorderNamer)

    def __init__(self, parent):
        self._parent = journaling.IRecorderNamer(parent)
        self._ident = self._parent.gen_name(self)
        self._count = 0

    ### IRecorderNamer Methods ###

    def gen_name(self, recorder):
        self._count += 1
        return self._ident + (self._count,)


class Recorder(RecorderNamer):

    implements(journaling.IRecorder)

    def __init__(self, parent, journal_keeper):
        RecorderNamer.__init__(self, parent)
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



