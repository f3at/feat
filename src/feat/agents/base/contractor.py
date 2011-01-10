from zope.interface import implements
from feat.interface import contractor
from feat.common import log, reflect, serialization
from feat.agents.base import message, replay


class Meta(type(replay.Replayable)):
    implements(contractor.IContractorFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseContractor(log.Logger, replay.Replayable):
    """
    I am a base class for contractors of contracts.

    @ivar protocol_type: the type of contract this contractor bids on.
                         Must match the type of the manager for this contract;
                         see L{feat.agents.manager.BaseManager}
    @type protocol_type: str
    """
    __metaclass__ = Meta

    implements(contractor.IAgentContractor)

    initiator = message.Announcement

    log_category = "contractor"
    protocol_type = "Contract"
    protocol_id = None

    bid_timeout = 10
    ack_timeout = 10

    def __init__(self, agent, medium):
        log.Logger.__init__(self, medium)
        replay.Replayable.__init__(self, agent, medium)

    def init_state(self, state, agent, medium):
        state.agent = agent
        state.medium = medium

    @replay.immutable
    def restored(self, state):
        replay.Replayable.restored(self)
        log.Logger.__init__(self, state.medium)

    def announced(self, announcement):
        '''@see: L{contractor.IAgentContractor}'''

    def announce_expired(self):
        '''@see: L{contractor.IAgentContractor}'''

    def rejected(self, rejection):
        '''@see: L{contractor.IAgentContractor}'''

    def granted(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def bid_expired(self):
        '''@see: L{contractor.IAgentContractor}'''

    def cancelled(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def acknowledged(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def aborted(self):
        '''@see: L{contractor.IAgentContractor}'''
