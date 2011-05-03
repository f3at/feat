from twisted.python.failure import Failure

from zope.interface import implements

from feat.common import log, reflect, serialization, fiber, error_handler
from feat.agents.base import replay, protocol, message, recipient

from feat.interface.requester import *
from feat.interface.protocols import *


def say_goodbye(agent, recp, payload):
    origin = agent.get_own_address()
    return _notify_partner(agent, recp, 'goodbye', origin, payload)


def notify_died(agent, recp, origin, payload):
    return _notify_partner(agent, recp, 'died', origin, payload)


def notify_restarted(agent, recp, origin, new_address):
    return _notify_partner(agent, recp, 'restarted', origin, new_address)


def notify_burried(agent, recp, origin, payload):
    return _notify_partner(agent, recp, 'burried', origin, payload)


def ping(agent, recp):
    f = fiber.succeed(Ping)
    f.add_callback(agent.initiate_protocol, recp)
    f.add_callback(Ping.notify_finish)
    return f


### Private ###


class Meta(type(replay.Replayable)):
    implements(IRequesterFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        serialization.register(cls)
        super(Meta, cls).__init__(name, bases, dct)


class BaseRequester(log.Logger, protocol.InitiatorBase, replay.Replayable):

    __metaclass__ = Meta
    implements(IAgentRequester)

    log_category = "requester"
    timeout = 0
    protocol_id = None

    _error_handler = error_handler

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
        '''@see: L{IAgentRequester}'''

    def got_reply(self, reply):
        '''@see: L{IAgentRequester}'''

    def closed(self):
        '''@see: L{IAgentRequester}'''


class Ping(BaseRequester):

    timeout = 1
    protocol_id = 'ping'

    @replay.entry_point
    def initiate(self, state):
        msg = message.RequestMessage()
        state.medium.request(msg)


class PartnershipProtocol(BaseRequester):

    timeout = 3
    protocol_id = 'partner-notification'

    known_types = ['goodbye', 'died', 'restarted', 'burried']

    @replay.entry_point
    def initiate(self, state, notification_type, origin, blackbox=None):
        origin = recipient.IRecipient(origin)
        if notification_type not in type(self).known_types:
            raise AttributeError(
                'Expected notification type to be in %r, got %r' %\
                (type(self).known_types, notification_type, ))
        payload = {
            'type': notification_type,
            'blackbox': blackbox,
            'origin': origin}
        msg = message.RequestMessage(payload=payload)
        state.medium.request(msg)

    @replay.immutable
    def got_reply(self, state, reply):
        payload = reply.payload
        if isinstance(payload, Failure):
            self._error_handler(payload)
        return reply.payload


def _notify_partner(agent, recp, notification_type, origin, payload):

    def _ignore_initiator_failed(fail):
        if fail.check(InitiatorFailed):
            agent.log('Swallowing %r expection.', fail.value)
            return None
        else:
            agent.log('Reraising exception %r', fail)
            fail.raiseException()

    f = fiber.succeed(PartnershipProtocol)
    f.add_callback(agent.initiate_protocol, recp, notification_type,
                   origin, payload)
    f.add_callback(PartnershipProtocol.notify_finish)
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
            our_role = state.our_role or reply.payload['default_role']
            return state.agent.create_partner(
                reply.payload['desc'], reply.reply_to, state.allocation_id,
                our_role, substitute=state.substitute)
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
