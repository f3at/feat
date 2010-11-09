from zope.interface import Interface, Attribute

from feat.common import enum

from . import serialization


class JournalMode(enum.Enum):
    recording, replay = range(1, 3)


class IRecordInput(serialization.ISnapshot):
    pass


class IRecordOutput(serialization.ISnapshot):
    pass


class IRecordingResult(Interface):

    output = Attribute("Recording output")

    def proceed():
        '''Continue with the stateless part of a recording.'''


class IJournalKeeper(Interface):
    '''Store journal entries'''

    def register(recorder):
        '''Register a recorder.
        Should be called by every recorder when created.'''

    def record(instance_id, entry_id, input, output):
        pass


class IRecorderNode(Interface):

    journal_parent = Attribute('Parent recorder node, L{IRecorderNode} or '
                               'None for the root node')
    journal_keeper = Attribute('Journal keeper to use, L{IJournalKeeper}')
    journal_mode = Attribute('Journaling mode, L{JournalMode}')

    def generate_identifier(recorder):
        pass


class IRecorder(IRecorderNode):

    journal_id = Attribute('Journal recorder identifier, tuple of int')

    def replay(entry_id, input):
        pass


