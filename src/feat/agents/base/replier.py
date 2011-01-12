from zope.interface import implements

from feat.interface import replier, protocols
from feat.common import log, reflect, serialization, fiber
from feat.agents.base import message, replay


class Meta(type(replay.Replayable)):
    implements(replier.IReplierFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseReplier(log.Logger, replay.Replayable):

    __metaclass__ = Meta

    implements(replier.IAgentReplier)

    initiator = message.RequestMessage
    interest_type = protocols.InterestType.private

    log_category = "replier"
    protocol_type = "Request"
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

    def requested(self, request):
        '''@see: L{replier.IAgentReplier}'''


class GoodBye(BaseReplier):

    protocol_id = 'goodbye'

    @replay.journaled
    def requested(self, state, request):
        f = fiber.Fiber()
        f.add_callback(state.agent.partner_said_goodbye)
        f.add_callback(self._send_reply)
        return f.succeed(request.reply_to)

    @replay.immutable
    def _send_reply(self, state, payload):
        msg = message.ResponseMessage(payload=payload)
        state.medium.reply(msg)


class ProposalReceiver(BaseReplier):

    protocol_id = 'lets-pair-up'

    @replay.journaled
    def requested(self, state, request):
        msg = message.ResponseMessage(
            payload=state.agent.descriptor_type)
        f = fiber.Fiber()
        f.add_callback(state.agent.create_partner, request.reply_to,
                       role=request.payload['role'])
        f.add_callback(fiber.drop_result, state.medium.reply, msg)
        return f.succeed(request.payload['partner_class'])
