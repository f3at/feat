from zope.interface import implements

from feat.common import log, reflect, serialization, fiber
from feat.interface import requester, protocols
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
    def initiate(self, state, payload=None):
        msg = message.RequestMessage(payload=payload)
        state.medium.request(msg)


def say_goodbye(agent, recp, payload):

    def _ignore_initiator_failed(fail):
        if fail.check(protocols.InitiatorFailed):
            agent.log('Swallowing %r expection.', fail.value)
            return None
        else:
            agent.log('Reraising exception %r', fail)
            fail.raiseException()

    f = fiber.succeed(GoodBye)
    f.add_callback(agent.initiate_protocol, recp, payload)
    f.add_callback(GoodBye.notify_finish)
    f.add_errback(_ignore_initiator_failed)
    return f


class Propose(BaseRequester):

    timeout = 3
    protocol_id = 'lets-pair-up'

    @replay.entry_point
    def initiate(self, state, our_alloc_id=None, partner_alloc_id=None,
                 partner_role=None, our_role=None, substitute=None):
        state.our_role = our_role
        state.allocation_id = our_alloc_id
        state.substitute = substitute
        msg = message.RequestMessage(
            payload=dict(
                partner_class=state.agent.descriptor_type,
                role=partner_role,
                allocation_id=partner_alloc_id))
        state.medium.request(msg)

    @replay.entry_point
    def got_reply(self, state, reply):
        if reply.payload['ok']:
            return state.agent.create_partner(
                reply.payload['desc'], reply.reply_to, state.allocation_id,
                state.our_role, substitute=state.substitute)
        else:
            self.info('Received error: %r', reply.payload['fail'])
            f = self._release_allocation()
            f.chain(fiber.fail(reply.payload['fail']))
            return f

    @replay.entry_point
    def closed(self, state):
        self.warning('Our proposal to agent %r has been ignored. How rude!',
                     state.medium.get_recipients())
        return self._release_allocation()

    @replay.mutable
    def _release_allocation(self, state):
        f = fiber.succeed()
        if state.allocation_id:
            return f.add_callback(fiber.drop_result,
                                  state.agent.release_resource,
                                  state.allocation_id)
        return f
