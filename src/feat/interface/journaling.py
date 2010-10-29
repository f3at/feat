from zope.interface import Interface, Attribute

from . import serialization


class IRecordInput(serialization.ISerializable):
    pass


class IRecordOutput(serialization.ISerializable):
    pass


class IRecordingResult(Interface):

    output = Attribute("Recording output")

    def proceed():
        '''Continue with the stateless part of a recording.'''


class IJournalKeeper(Interface):
    '''Store journal entries'''

    def do_record(instance_id, entry_id, input, output):
        pass


class IJournalPlayer(Interface):

    def register(recorder):
        pass


class IRecorderNamer(Interface):

    def gen_name(recorder):
        pass


class IRecorder(IRecorderNamer):

    def record(entry_id, input, output):
        pass

    def replay(entry_id, input):
        pass


