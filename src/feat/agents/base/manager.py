from zope.interface import implements

from feat.agents.base import protocols, replay, message
from feat.common import serialization, reflect

from feat.interface.manager import *
from feat.interface.protocols import *


class MetaManager(type(replay.Replayable)):

    implements(IManagerFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(MetaManager, cls).__init__(name, bases, dct)


class BaseManager(protocols.BaseInitiator):
    """
    I am a base class for managers of contracts.

    @ivar protocol_type: the type of contract this manager manages.
                         Must match the type of the contractor for this
                         contract; see L{feat.agents.contractor.BaseContractor}
    @type protocol_type: str
    """

    __metaclass__ = MetaManager

    implements(IAgentManager)

    protocol_type = "Contract"
    protocol_id = None

    initiate_timeout = 10
    announce_timeout = 10
    grant_timeout = 10

    def bid(self, bid):
        '''@see: L{manager.IAgentManager}'''

    def closed(self):
        '''@see: L{manager.IAgentManager}'''

    def expired(self):
        '''@see: L{manager.IAgentManager}'''

    def cancelled(self, cancellation):
        '''@see: L{manager.IAgentManager}'''

    def completed(self, report):
        '''@see: L{manager.IAgentManager}'''

    def aborted(self):
        '''@see: L{manager.IAgentManager}'''


@serialization.register
class DiscoverService(serialization.Serializable):

    implements(IManagerFactory)

    protocol_type = "Contract"

    def __init__(self, identifier, timeout):
        if not isinstance(identifier, str):
            identifier = IInitiatorFactory(identifier).protocol_id

        self.protocol_id = 'discover-' + identifier
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
