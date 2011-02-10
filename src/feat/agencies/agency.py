# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import time
import weakref
import uuid
import copy

from twisted.internet import defer
from zope.interface import implements

from feat.common import log, manhole, journal, fiber, serialization, delay
from feat.agents.base import recipient, replay
from feat.agents.base.agent import registry_lookup
from feat.agents.host import host_agent
from feat.agencies import common
from feat.interface import agency, agent, protocols
from feat.common.serialization import pytree, Serializable

from interface import IListener, IAgencyInitiatorFactory,\
                      IAgencyInterestedFactory, IConnectionFactory

from . import contracts, requests


class Agency(manhole.Manhole, log.FluLogKeeper, log.Logger):

    log_category = 'agency'

    __metaclass__ = type('MetaAgency', (type(manhole.Manhole),
                                        type(log.FluLogKeeper)), {})

    implements(agency.IAgency, serialization.IExternalizer)

    def __init__(self, messaging, database):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self._agents = []

        self._messaging = IConnectionFactory(messaging)
        self._database = IConnectionFactory(database)
        self._journal_entries = list()
        self.serializer = pytree.Serializer(externalizer=self)
        self.registry = weakref.WeakValueDictionary()

    @manhole.expose()
    def start_agent(self, descriptor):
        factory = agent.IAgentFactory(
            registry_lookup(descriptor.document_type))
        self.log('I will start: %r agent', factory)
        medium = AgencyAgent(self, factory, descriptor)
        self._agents.append(medium)
        d = defer.maybeDeferred(medium.agent.initiate)
        d.addCallback(lambda _: medium)
        return d

    def unregister_agent(self, medium, agent_id):
        self._agents.remove(medium)
        self.journal_agent_deleted(agent_id)

    def get_time(self):
        return time.time()

    # journal specific stuff

    def journal_write_entry(self, agent_id, instance_id, entry_id,
                    fiber_id, fiber_depth, input, side_effects, output):
        snapshot_input = self.serializer.convert(input)
        snapshot_side_effects = self.serializer.convert(side_effects)
        snapshot_output = self.serializer.freeze(output)

        record = (agent_id, instance_id, entry_id, fiber_id, fiber_depth,
                  snapshot_input, snapshot_side_effects, snapshot_output)
        self._journal_entries.append(record)

    def journal_agency_entry(self, agent_id, entry_id, input):
        section = fiber.WovenSection()
        section.enter()
        self.journal_write_entry(
            agent_id=agent_id,
            instance_id='agency',
            entry_id=entry_id,
            fiber_id=section.descriptor.fiber_id,
            fiber_depth=section.descriptor.fiber_depth,
            input=input,
            side_effects=None,
            output=None)
        section.abort()

    def journal_protocol_created(self, agent_id, protocol_factory,
                                 medium, args=None, kwargs=None):
        input = (protocol_factory, medium, args, kwargs, )
        self.journal_agency_entry(agent_id, 'protocol_created', input)

    def journal_protocol_deleted(self, agent_id, protocol_instance, dummy_id):
        input = (protocol_instance.journal_id, dummy_id, )
        self.journal_agency_entry(agent_id, 'protocol_deleted', input)

    def journal_agent_created(self, agent_id, agent_factory, dummy_id):
        input = (agent_factory, dummy_id, )
        self.journal_agency_entry(agent_id, 'agent_created', input)

    def journal_agent_deleted(self, agent_id):
        input = tuple()
        self.journal_agency_entry(agent_id, 'agent_deleted', input)

    def journal_agent_snapshot(self, agent_id, snapshot):
        input = (snapshot, )
        self.journal_agency_entry(agent_id, 'snapshot', input)

    # registry

    def register(self, recorder):
        j_id = recorder.journal_id
        self.log('Registering recorder: %r, id: %r',
                 recorder.__class__.__name__, j_id)
        assert j_id not in self.registry
        self.registry[j_id] = recorder

    # IExternalizer

    def identify(self, instance):
        if (journal.IRecorder.providedBy(instance) and
            instance.journal_id in self.registry):
            return instance.journal_id

    def lookup(self, _):
        raise RuntimeError("OOPS, this should never be called "
                           "in production code!!")

    # Snapshot the agents

    @manhole.expose()
    def snapshot_agents(self):
        # reset the registry, so that snapshot contains
        # full objects not just the references
        self.registry = weakref.WeakValueDictionary()
        for agent in self._agents:
            agent.journal_snapshot()


class AgencyAgent(log.LogProxy, log.Logger, manhole.Manhole):
    implements(agent.IAgencyAgent, journal.IRecorderNode,
               journal.IJournalKeeper, serialization.ISerializable)

    log_category = "agency-agent"
    journal_parent = None
    type_name = "agent-medium" # this is used by ISerializable

    def __init__(self, aagency, factory, descriptor):
        log.LogProxy.__init__(self, aagency)
        log.Logger.__init__(self, self)

        self.journal_keeper = self

        self.agency = agency.IAgency(aagency)
        self._descriptor = descriptor
        self.agency.journal_agent_created(descriptor.doc_id, factory,
                                          self.snapshot())
        self.agent = factory(self)
        self.log_name = self.agent.__class__.__name__
        self.log('Instantiated the %r instance', self.agent)

        self._messaging = self.agency._messaging.get_connection(self)
        self._database = self.agency._database.get_connection(self)

        # instance_id -> IListener
        self._listeners = {}
        # protocol_type -> protocol_id -> protocols.IInterest
        self._interests = {}
        # retrying protocols
        self._retrying_protocols = list()

        self.join_shard(descriptor.shard)

    def snapshot_agent(self):
        '''Gives snapshot of everything related to the agent'''
        listeners = [i.get_agent_side() for i in self._listeners.values()]
        return (self.agent, listeners, )

    def journal_snapshot(self):
        self.agency.journal_agent_snapshot(self._descriptor.doc_id,
                                           self.snapshot_agent())

    @replay.named_side_effect('AgencyAgent.get_descriptor')
    def get_descriptor(self):
        return copy.deepcopy(self._descriptor)

    def update_descriptor(self, desc):

        def update(desc):
            self.log("Updating descriptor: %r", desc)
            self._descriptor = desc

        d = self.save_document(desc)
        d.addCallback(update)
        return d

    @replay.named_side_effect('AgencyAgent.join_shard')
    def join_shard(self, shard):
        self.log("Join shard called. Shard: %r", shard)
        self.create_binding(self._descriptor.doc_id, shard)

    @replay.named_side_effect('AgencyAgent.leave_shard')
    def leave_shard(self, shard):
        bindings = self._messaging.get_bindings(shard)
        map(lambda binding: binding.revoke(), bindings)

    def start_agent(self, desc):
        return self.agency.start_agent(desc)

    def on_message(self, message):
        self.log('Received message: %r', message)

        # check if it isn't expired message
        ctime = self.get_time()
        if message.expiration_time < ctime:
            self.log('Throwing away expired message.')
            return False

        # handle registered dialog
        if message.receiver_id is not None and\
           message.receiver_id in self._listeners:
            listener = self._listeners[message.receiver_id]
            listener.on_message(message)
            return True

        # handle new conversation comming in (interest)
        p_type = message.protocol_type
        p_id = message.protocol_id
        if p_type in self._interests and p_id in self._interests[p_type] and\
          isinstance(message, self._interests[p_type][p_id].factory.initiator):
            self.log('Looking for interest to instantiate.')
            factory = self._interests[message.protocol_type]\
                                     [message.protocol_id].factory
            medium_factory = IAgencyInterestedFactory(factory)
            medium = medium_factory(self, message)
            self.agency.journal_protocol_created(self._descriptor.doc_id,
                                                 factory, medium)
            interested = factory(self.agent, medium)
            medium.initiate(interested)
            listener = self.register_listener(medium)
            listener.on_message(message)
            return True

        self.error("Couldn't find appriopriate listener for message: %s.%s.%s",
                   message.protocol_type, message.protocol_id,
                   message.__class__.__name__)
        return False

    @replay.named_side_effect('AgencyAgent.initiate_protocol')
    def initiate_protocol(self, factory, recipients, *args, **kwargs):
        self.log('Initiating protocol for factory: %r, args: %r, kwargs: %r',
                 factory, args, kwargs)
        factory = protocols.IInitiatorFactory(factory)
        recipients = recipient.IRecipients(recipients)
        medium_factory = IAgencyInitiatorFactory(factory)
        medium = medium_factory(self, recipients, *args, **kwargs)

        self.agency.journal_protocol_created(
            self._descriptor.doc_id, factory, medium, args, kwargs)
        initiator = factory(self.agent, medium, *args, **kwargs)
        self.register_listener(medium)
        medium.initiate(initiator)
        return initiator

    @replay.named_side_effect('AgencyAgent.retrying_protocol')
    def retrying_protocol(self, factory, recipients, max_retries=None,
                          initial_delay=1, max_delay=None,
                          args=None, kwargs=None):

        args = args or tuple()
        kwargs = kwargs or dict()
        r = RetryingProtocol(self, factory, recipients, args, kwargs,
                             max_retries, initial_delay)
        self._retrying_protocols.append(r)
        r.notify_finish().addBoth(
            lambda _: self._retrying_protocols.remove(r))
        return r

    @replay.named_side_effect('AgencyAgent.register_interest')
    def register_interest(self, factory):
        factory = protocols.IInterest(factory)
        p_type = factory.protocol_type
        p_id = factory.protocol_id
        if p_type not in self._interests:
            self._interests[p_type] = dict()
        if p_id in self._interests[p_type]:
            self.error('Already interested in %s.%s protocol!', p_type, p_id)
            return False
        i = Interest(self, factory)
        self._interests[p_type][p_id] = i
        self.debug('Registered interest in %s.%s protocol.', p_type, p_id)
        return i

    @replay.named_side_effect('AgencyAgent.revoke_interest')
    def revoke_interest(self, factory):
        factory = protocols.IInterest(factory)
        p_type = factory.protocol_type
        p_id = factory.protocol_id
        if p_type not in self._interests or\
           p_id not in self._interests[p_type]:
            self.error('Requested to revoke interest we are not interested in!'
                      ' %s.%s', p_type, p_id)
            return False
        self._interests[p_type][p_id].revoke()
        del(self._interests[p_type][p_id])

        return True

    def register_listener(self, listener):
        listener = IListener(listener)
        session_id = listener.get_session_id()
        self.debug('Registering listener session_id: %r', session_id)
        assert session_id not in self._listeners
        self._listeners[session_id] = listener
        return listener

    def unregister_listener(self, session_id):
        if session_id in self._listeners:
            self.debug('Unregistering listener session_id: %r', session_id)
            listener = self._listeners[session_id]
            self.agency.journal_protocol_deleted(
                self._descriptor.doc_id, listener.get_agent_side(),
                listener.snapshot())
            del(self._listeners[session_id])
        else:
            self.error('Tried to unregister listener with session_id: %r, '
                        'but not found!', session_id)

    @replay.named_side_effect('AgencyAgent.get_time')
    def get_time(self):
        return self.agency.get_time()

    def send_msg(self, recipients, msg, handover=False):
        recipients = recipient.IRecipients(recipients)
        if not handover:
            msg.reply_to = recipient.IRecipient(self)
            msg.message_id = str(uuid.uuid1())
        assert msg.expiration_time is not None
        for recp in recipients:
            self.log('Sending message to %r', recp)
            self._messaging.publish(recp.key, recp.shard, msg)
        return msg

    def create_binding(self, key, shard=None):
        return self._messaging.personal_binding(key, shard)

    # Delegation of methods to IDatabaseClient

    @serialization.freeze_tag('AgencyAgency.save_document')
    def save_document(self, document):
        return self._database.save_document(document)

    @serialization.freeze_tag('AgencyAgency.reload_document')
    def reload_document(self, document):
        return self._database.reload_document(document)

    @serialization.freeze_tag('AgencyAgency.delete_document')
    def delete_document(self, document):
        return self._database.delete_document(document)

    @serialization.freeze_tag('AgencyAgency.get_document')
    def get_document(self, document_id):
        return self._database.get_document(document_id)

    @manhole.expose()
    @serialization.freeze_tag('AgencyAgency.terminate')
    def terminate(self):
        self.log("terminate() called")

        # revoke all interests
        for i_type in self._interests:
            [self.revoke_interest(x.factory) \
             for x in self._interests[i_type].values()]

        # kill all retrying protocols
        d = defer.DeferredList([x.give_up() for x in self._retrying_protocols])
        # kill all listeners
        d.addBoth(self._kill_all_listeners)
        # run IAgent.shutdown() and wait for the listeners to finish the job
        d.addBoth(self._run_and_wait, self.agent.shutdown)
        # run IAgent.unregister() and wait for the listeners to finish the job
        d.addBoth(self._run_and_wait, self.agent.unregister)
        # delete the descriptor
        d.addBoth(lambda _: self.delete_document(self._descriptor))
        # TODO: delete the queue

        # tell the agency we are no more
        d.addBoth(lambda doc: self.agency.unregister_agent(self, doc.doc_id))
        # close the messaging connection
        d.addBoth(lambda _: self._messaging.disconnect())
        return d

    def _run_and_wait(self, _, method, *args, **kwargs):
        '''
        Run a agent-side method and wait for all the listeners
        to finish processing.
        '''
        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addBoth(self.wait_for_listeners_finish)
        return d

    def wait_for_listeners_finish(self):

        def wait_for_listener(listener):
            d = listener.notify_finish()
            d.addErrback(self._ignore_initiator_failed)
            return d

        d = defer.DeferredList(
            [wait_for_listener(x) for x in self._listeners.values()])
        return d

    def _kill_all_listeners(self, *_):

        def expire_one(listener):
            d = listener.expire_now()
            d.addErrback(self._ignore_initiator_failed)
            return d

        d = defer.DeferredList(
            [expire_one(x) for x in self._listeners.values()])
        return d

    def _ignore_initiator_failed(self, fail):
        if fail.check(protocols.InitiatorFailed):
            self.log('Swallowing %r expection.', fail.value)
            return None
        else:
            self.log('Reraising exception %r', fail)
            fail.raiseException()

    # IRecorderNone

    def generate_identifier(self, recorder):
        assert not getattr(self, 'indentifier_generated', False)
        self._identifier_generated = True
        return (self._descriptor.doc_id, )

    # IJournalKeeper

    def register(self, recorder):
        self.agency.register(recorder)

    def write_entry(self, *args, **kwargs):
        self.agency.journal_write_entry(self._descriptor.doc_id,
                                        *args, **kwargs)
    # ISerializable

    def snapshot(self):
        return self._descriptor.doc_id

    # For manhole purpose:

    @manhole.expose()
    def get_agent(self):
        return self.agent


@serialization.register
class Interest(Serializable):
    '''Represents the interest from the point of view of agency.
    Manages the binding and stores factory reference'''

    type_name = 'agency-interest'

    factory = None
    binding = None

    def __init__(self, medium, factory):
        self.factory = factory
        self.medium = medium
        self._lobby_binding = None

        if factory.interest_type == protocols.InterestType.public:
            self.binding = self.medium.create_binding(self.factory.protocol_id)

    @replay.named_side_effect('Interest.revoke')
    def revoke(self):
        if self.factory.interest_type == protocols.InterestType.public:
            self.binding.revoke()

    @replay.named_side_effect('Interest.bind_to_lobby')
    def bind_to_lobby(self):
        assert self._lobby_binding is None
        self._lobby_binding = self.medium._messaging.personal_binding(
            self.factory.protocol_id, 'lobby')

    @replay.named_side_effect('Interest.unbind_from_lobby')
    def unbind_from_lobby(self):
        self._lobby_binding.revoke()
        self._lobby_binding = None

    # ISerializable

    def snapshot(self):
        return dict(factory=self.factory)


class RetryingProtocol(common.InitiatorMediumBase, log.Logger):

    implements(serialization.ISerializable)

    log_category="retrying-protocol"
    type_name="retrying-protocol"

    def __init__(self, medium, factory, recipients, args, kwargs,
                 max_retries=None, initial_delay=1, max_delay=None):
        common.InitiatorMediumBase.__init__(self)
        log.Logger.__init__(self, medium)

        self.medium = medium
        self.factory = factory
        self.recipients = recipients
        self.args = args
        self.kwargs = kwargs

        self.max_retries = max_retries
        self.max_delay = max_delay
        self.attempt = 0
        self.delay = initial_delay

        self._delayed_call = None
        self._initiator = None

        self._bind()

    # public interface

    @serialization.freeze_tag('RetryingProtocol.notify_finish')
    def notify_finish(self):
        return common.InitiatorMediumBase.notify_finish(self)

    @serialization.freeze_tag('RetryingProtocol.give_up')
    def give_up(self):
        self.max_retries = self.attempt - 1
        if self._delayed_call and not self._delayed_call.called:
            self._delayed_call.cancel()
            return defer.succeed(None)
        if self._initiator:
            d = self._initiator._get_state().medium.expire_now()
            d.addErrback(self.medium._ignore_initiator_failed)
            return d

    # private section

    def _bind(self):
        d = self._fire()
        d.addCallbacks(self._finalize, self._wait_and_retry)

    def _fire(self):
        self.attempt += 1
        self._initiator = self.medium.initiate_protocol(
            self.factory, self.recipients, *self.args, **self.kwargs)
        d = self._initiator.notify_finish()
        return d

    def _finalize(self, result):
        self.finish_deferred.callback(result)

    def _wait_and_retry(self, failure):
        self.info('Retrying protocol for factory: %r failed for the %d time. ',
                  self.factory, self.attempt)

        self._initiator = None

        # check if we are done
        if self.max_retries is not None and self.attempt > self.max_retries:
            self.info("Will not try to restart.")
            return self.finish_deferred.errback(failure)

        # do retry
        self.info('Will retry in %d seconds', self.delay)
        self._delayed_call = delay.callLater(self.delay, self._bind)

        # adjust the delay
        if self.max_delay is None:
            self.delay *= 2
        elif self.delay < self.max_delay:
            self.delay = min((2 * self.delay, self.max_delay, ))

    # ISerializable

    def snapshot(self):
        return id(self)
