from zope.interface import implements
from feat.interface import manager
from feat.common import log, serialization, reflect
from feat.agents.base import protocol, replay, message


class Meta(type(replay.Replayable)):

    implements(manager.IManagerFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseManager(log.Logger, protocol.InitiatorBase, replay.Replayable):
    """
    I am a base class for managers of contracts.

    @ivar protocol_type: the type of contract this manager manages.
                         Must match the type of the contractor for this
                         contract; see L{feat.agents.contractor.BaseContractor}
    @type protocol_type: str
    """
    __metaclass__ = Meta

    implements(manager.IAgentManager)

    announce = None
    grant = None
    report = None
    agent = None

    log_category = "manager"
    protocol_type = "Contract"
    protocol_id = None

    initiate_timeout = 10
    announce_timeout = 10
    grant_timeout = 10

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

    def initiate(self):
        '''@see: L{manager.IAgentManager}'''

    def bid(self, bid):
        '''@see: L{manager.IAgentManager}'''

    def closed(self):
        '''@see: L{manager.IAgentManager}'''

    def expired(self):
        '''@see: L{manager.IAgentManager}'''

    def cancelled(self, grant, cancellation):
        '''@see: L{manager.IAgentManager}'''

    def completed(self, grant, report):
        '''@see: L{manager.IAgentManager}'''

    def aborted(self):
        '''@see: L{manager.IAgentManager}'''


@serialization.register
class DiscoverService(serialization.Serializable):
    implements(manager.IManagerFactory)

    def __init__(self, factory, timeout):
        factory = manager.IManagerFactory(factory)
        self.protocol_type = factory.protocol_type
        self.protocol_id = 'discover-' + factory.protocol_id
        self.timeout = timeout

    def __call__(self, agent, medium):
        instance = ServiceDiscoveryManager(agent, medium)
        instance.protocol_id = self.protocol_id
        instance.announce_timeout = self.timeout
        return instance


class ServiceDiscoveryManager(BaseManager):

    @replay.journaled
    def initiate(self, state):
        state.providers = list()
        state.medium.announce(message.Announcement())

    @replay.mutable
    def bid(self, state, bid):
        state.providers.append(bid.reply_to)
        state.medium.reject(bid, message.Rejection())

    @replay.immutable
    def expired(self, state):
        return state.providers
