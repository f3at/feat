from zope.interface import implements

from feat.common import log, reflect, serialization
from feat.interface import requester
from feat.agents.base import replay, protocol, message


class Meta(type(replay.Replayable)):
    implements(requester.IRequesterFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseRequester(log.Logger, protocol.InitiatorBase, replay.Replayable):

    __metaclass__ = Meta
    implements(requester.IAgentRequester)

    log_category = "requester"
    timeout = 0
    protocol_id = None

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
        '''@see: L{requester.IAgentRequester}'''

    def got_reply(self, reply):
        '''@see: L{requester.IAgentRequester}'''

    def closed(self):
        '''@see: L{requester.IAgentRequester}'''


class GoodBye(BaseRequester):

    timeout = 1
    protocol_id = 'goodbye'

    @replay.immutable
    def initiate(self, state):
        msg = message.RequestMessage()
        state.medium.request(msg)


class Propose(BaseRequester):

    timeout = 3
    protocol_id = 'lets-pair-up'

    @replay.mutable
    def initiate(self, state, allocation=None, our_role=None,
                 partner_role=None):
        state.our_role = our_role
        state.allocation = allocation
        msg = message.RequestMessage(
            payload=dict(
                partner_class=state.agent.descriptor_type,
                role=partner_role))
        state.medium.request(msg)

    @replay.immutable
    def got_reply(self, state, reply):
        return state.agent.create_partner(reply.payload, reply.reply_to,
                                          state.allocation, state.our_role)

    @replay.immutable
    def closed(self, state):
        self.warning('Our proposal to agent %r has been ignored. How rude!',
                     state.medium.recipients)
        if state.allocation:
            state.agent.release_resource(state.allocation)
