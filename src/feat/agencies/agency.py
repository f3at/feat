# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

# Import standard library modules
import copy
import uuid
import weakref

# Import external project modules
from zope.interface import implements

# Import feat modules
from feat.agencies import common, dependency
from feat.agents.base import recipient, replay, descriptor
from feat.agents.base.agent import registry_lookup
from feat.common import (log, defer, fiber, serialization, journal, time,
                         manhole, error_handler, text_helper, container, )

# Import interfaces
from interface import *
from feat.interface.agency import *
from feat.interface.agent import *
from feat.interface.generic import *
from feat.interface.journal import *
from feat.interface.protocols import *
from feat.interface.recipient import *
from feat.interface.serialization import *


class Agency(log.FluLogKeeper, log.Logger, manhole.Manhole,
             dependency.AgencyDependencyMixin):

    log_category = 'agency'

    __metaclass__ = type('MetaAgency', (type(manhole.Manhole),
                                        type(log.FluLogKeeper)), {})

    implements(IAgency, IExternalizer, ITimeProvider)

    _error_handler = error_handler

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)
        dependency.AgencyDependencyMixin.__init__(self, ExecMode.test)

        self._agents = []

        self.registry = weakref.WeakValueDictionary()
        self._journaler = None
        self._database = None
        self._messaging = None

    ### Public Methods ###

    def initiate(self, messaging, database, journaler):
        '''
        Asynchronous part of agency initialization. Needs to be called before
        agency is used for anything.
        '''
        self._database = IDbConnectionFactory(database)
        self._messaging = IConnectionFactory(messaging)
        self._journaler = IJournaler(journaler).get_connection(self)
        return defer.succeed(self)

    @manhole.expose()
    def start_agent(self, descriptor, *args, **kwargs):
        factory = IAgentFactory(registry_lookup(descriptor.document_type))
        self.log('I will start: %r agent. Args: %r, Kwargs: %r',
                 factory, args, kwargs)
        medium = AgencyAgent(self, factory, descriptor)
        self._agents.append(medium)
        run_startup = kwargs.pop('run_startup', True)
        d = defer.succeed(None)
        d.addCallback(defer.drop_param, medium.initiate,
                      *args, **kwargs)
        d.addCallback(defer.bridge_param, medium.call_next, medium.startup,
                      startup_agent=run_startup)
        return d

    def shutdown(self):
        '''Called when the agency is ordered to shutdown all the agents..'''
        d = defer.DeferredList([x._terminate() for x in self._agents])
        d.addCallback(lambda _: self._messaging.disconnect())
        return d

    def on_killed(self):
        '''Called when the agency process is terminating. (SIGTERM)'''
        d = defer.DeferredList([x.on_killed() for x in self._agents])
        d.addCallback(lambda _: self._messaging.disconnect())
        return d

    def unregister_agent(self, medium):
        agent_id = medium.get_descriptor().doc_id
        self.debug('Unregistering agent id: %r', agent_id)
        self._agents.remove(medium)

        # FIXME: This shouldn't be necessary! Here we are manually getting
        # rid of things which should just be garbage collected (self.registry
        # is a WeekRefDict). It doesn't happpen supposingly
        for key in self.registry.keys():
            if key[0] == agent_id:
                self.debug("Manualy removing recorder id %r, instance: %r",
                           key, self.registry[key])
                del(self.registry[key])

    ### Journaling Methods ###

    def register(self, recorder):
        j_id = recorder.journal_id
        self.log('Registering recorder: %r, id: %r',
                 recorder.__class__.__name__, j_id)
        if j_id in self.registry:
            raise RuntimeError(
                'Journal id %r already in registry, it points to %r object' %\
                (j_id, self.registry[j_id], ))
        self.registry[j_id] = recorder

    def journal_new_entry(self, agent_id, instance_id, journal_id,
                          function_id, *args, **kwargs):
        return self._journaler.new_entry(agent_id, instance_id, journal_id,
                                         function_id, *args, **kwargs)

    def journal_agency_entry(self, agent_id, instance_id, function_id,
                             *args, **kwargs):
        if journal.add_effect(function_id, *args, **kwargs):
            return

        section = fiber.WovenSection()
        section.enter()

        try:

            desc = section.descriptor
            entry = self.journal_new_entry(agent_id, instance_id, 'agency',
                                           function_id, *args, **kwargs)
            entry.set_fiber_context(desc.fiber_id, desc.fiber_depth)
            entry.set_result(None)
            entry.commit()

        finally:

            section.abort()

    def journal_protocol_created(self, agent_id, instance_id,
                                 protocol_factory, medium, *args, **kwargs):
        self.journal_agency_entry(agent_id, instance_id, 'protocol_created',
                                  protocol_factory, medium, *args, **kwargs)

    def journal_protocol_deleted(self, agent_id, instance_id,
                                 protocol_instance, dummy_id):
        self.journal_agency_entry(agent_id, instance_id, 'protocol_deleted',
                                  protocol_instance.journal_id, dummy_id)

    def journal_agent_created(self, agent_id, instance_id, agent_factory,
                              dummy_id):
        self.journal_agency_entry(agent_id, instance_id, 'agent_created',
                                  agent_factory, dummy_id)

    def journal_agent_deleted(self, agent_id, instance_id):
        self.journal_agency_entry(agent_id, instance_id, 'agent_deleted')

    def journal_agent_snapshot(self, agent_id, instance_id, snapshot):
        self.journal_agency_entry(agent_id, instance_id, 'snapshot', snapshot)

    ### IExternalizer Methods ###

    def identify(self, instance):
        if (IRecorder.providedBy(instance) and
            instance.journal_id in self.registry):
            return instance.journal_id

    def lookup(self, _):
        raise RuntimeError("OOPS, this should never be called "
                           "in production code!!")

    ### ITimeProvider Methods ###

    def get_time(self):
        return time.time()

    ### Introspection and Manhole Methods ###

    @manhole.expose()
    def find_agent(self, desc):
        agent_id = (desc.doc_id
                    if isinstance(desc, descriptor.Descriptor)
                    else desc)
        self.log("I'm trying to find the agent with id: %s", agent_id)
        try:
            return next(x for x in self._agents
                        if x._descriptor.doc_id == agent_id)
        except StopIteration:
            return None

    @manhole.expose()
    def snapshot_agents(self):
        # Reset the registry, so that snapshot contains
        # full objects not just the references
        self.registry = weakref.WeakValueDictionary()
        for agent in self._agents:
            agent.journal_snapshot()

    @manhole.expose()
    def list_agents(self):
        '''list_agents() -> List agents hosted by the agency.'''
        t = text_helper.Table(fields=("Agent ID", "Agent class", ),
                              lengths=(40, 25, ))

        return t.render((a._descriptor.doc_id, a.log_name, )\
                        for a in self._agents)

    @manhole.expose()
    def get_nth_agent(self, n):
        '''get_nth_agent(n) -> Get the agent by his index in the list.'''
        return self._agents[n]

    @manhole.expose()
    def get_agents(self):
        '''get_agents() -> Get the list of agents hosted by this agency.'''
        return self._agents


class AgencyAgent(log.LogProxy, log.Logger, manhole.Manhole,
                  dependency.AgencyAgentDependencyMixin,
                  common.StateMachineMixin):

    implements(IAgencyAgent, IAgencyAgentInternal, ITimeProvider,
               IRecorderNode, IJournalKeeper, ISerializable, IMessagingPeer)

    log_category = "agent-medium"
    type_name = "agent-medium" # this is used by ISerializable

    _error_handler = error_handler

    journal_parent = None

    def __init__(self, agency, factory, descriptor):
        log.LogProxy.__init__(self, agency)
        log.Logger.__init__(self, self)
        common.StateMachineMixin.__init__(self,
                AgencyAgentState.not_initiated)

        self.journal_keeper = self
        self.agency = IAgency(agency)
        self._descriptor = descriptor
        # Our instance id. It is used to tell the difference between the
        # journal entries comming from different agencies running the same
        # agent. Our value will be stored in descriptor before calling anything
        # on the agent side, although it needs to be set now to produce valid
        # identifiers.
        self._instance_id = descriptor.instance_id + 1

        self.agent = factory(self)
        self.log_name = self.agent.__class__.__name__
        self.log('Instantiated the %r instance', self.agent)

        self._listeners = {} # {instance_id: IListener}
        self._interests = {} # {protocol_type: {protocol_id: IInterest}}
        self._retrying_protocols = [] # Retrying protocols

        self._messaging = None
        self._database = None
        self._configuration = None

        self._updating = False
        self._update_queue = []
        self._delayed_calls = container.ExpDict(self)
        # Terminating flag, used to not to run
        # termination procedure more than once
        self._terminating = False

        # traversal_id -> True
        self._traversal_ids = container.ExpDict(self)


    ### Public Methods ###

    def initiate(self, *args, **kwargs):
        '''Establishes the connections to database and messaging platform,
        taking into account that it might meen performing asynchronous job.'''
        setter = lambda value, name: setattr(self, name, value)
        d = defer.Deferred()
        d.addCallback(defer.drop_param,
                      self.agency._messaging.get_connection, self)
        d.addCallback(setter, '_messaging')
        d.addCallback(defer.drop_param,
                      self.agency._database.get_connection)
        d.addCallback(setter, '_database')
        d.addCallback(defer.drop_param,
                      self._subscribe_for_descriptor_changes)
        d.addCallback(defer.drop_param, self._store_instance_id)
        d.addCallback(defer.drop_param, self._load_configuration)
        d.addCallback(setter, '_configuration')
        d.addCallback(defer.drop_param,
                      self.join_shard, self._descriptor.shard)
        d.addCallback(defer.drop_param,
                      self.journal_agent_created)
        d.addCallback(defer.drop_param,
                      self._call_initiate, *args, **kwargs)
        d.addCallback(defer.override_result, self)

        # Ensure the execution chain is broken
        self.call_next(d.callback, None)

        return d

    def startup(self, startup_agent=True):
        d = defer.succeed(None)
        if startup_agent:
            d.addCallback(defer.drop_param, self._call_startup)
        # Not calling agent startup, for testing purpose only
        d.addCallback(defer.drop_param, self._ready)
        return d

    def snapshot_agent(self):
        '''Gives snapshot of everything related to the agent'''
        listeners = [i.get_agent_side() for i in self._listeners.values()]
        return (self.agent, listeners, )

    def journal_agent_created(self):
        factory = type(self.agent)
        self.agency.journal_agent_created(
            self._descriptor.doc_id, self._instance_id,
            factory, self.snapshot())

    def journal_snapshot(self):
        self.agency.journal_agent_snapshot(self._descriptor.doc_id,
                                           self._instance_id,
                                           self.snapshot_agent())

    def journal_protocol_created(self, *args, **kwargs):
        self.agency.journal_protocol_created(self._descriptor.doc_id,
                                             self._instance_id,
                                             *args, **kwargs)

    @serialization.freeze_tag('AgencyAgent.start_agent')
    def start_agent(self, desc, *args, **kwargs):
        return self.agency.start_agent(desc, *args, **kwargs)

    def on_killed(self):
        '''called as part of SIGTERM handler.'''

        def generate_body():
            d = defer.succeed(None)
            # run IAgent.killed() and wait for the listeners to finish the job
            d.addBoth(self._run_and_wait, self.agent.killed)
            return d

        return self._terminate_procedure(generate_body)

    ### IAgencyAgent Methods ###

    @replay.named_side_effect('AgencyAgent.observe')
    def observe(self, _method, *args, **kwargs):
        res = common.Observer(_method, *args, **kwargs)
        self.call_next(res.initiate)
        return res

    @manhole.expose()
    @replay.named_side_effect('AgencyAgent.get_descriptor')
    def get_descriptor(self):
        return copy.deepcopy(self._descriptor)

    @manhole.expose()
    @replay.named_side_effect('AgencyAgent.get_configuration')
    def get_configuration(self):
        if self._configuration is None:
            raise RuntimeError(
                'Agent requested to get his configuration, but it was not '
                'found. The metadocument with ID %r is not in database. ' %\
                (self.agent.configuration_doc_id, ))

        return copy.deepcopy(self._configuration)

    @serialization.freeze_tag('AgencyAgent.update_descriptor')
    def update_descriptor(self, function, *args, **kwargs):
        d = defer.Deferred()
        self._update_queue.append((d, function, args, kwargs))
        self._next_update()
        return d

    @serialization.freeze_tag('AgencyAgent.join_shard')
    def join_shard(self, shard):
        self.log("Joining shard %r", shard)
        # Rebind agents queue
        binding = self.create_binding(self._descriptor.doc_id, shard)
        # Iterate over interest and create bindings
        bindings = [x.bind(shard) for x in self._iter_interests()]
        # Remove None elements (private interests)
        bindings = [x for x in bindings if x]
        bindings = [binding] + bindings
        return defer.DeferredList([x.created for x in bindings])

    @serialization.freeze_tag('AgencyAgent.leave_shard')
    def leave_shard(self, shard):
        self.log("Leaving shard %r", shard)
        bindings = self._messaging.get_bindings(shard)
        return defer.DeferredList([x.revoke() for x in bindings])

    @replay.named_side_effect('AgencyAgent.register_interest')
    def register_interest(self, factory, *args, **kwargs):
        factory = IInterest(factory)
        if not IFirstMessage.implementedBy(factory.initiator):
            raise TypeError(
                "%r.initiator expected to implemented IFirstMessage. Got %r" %\
                (factory, factory.initiator, ))
        p_type = factory.protocol_type
        p_id = factory.protocol_id
        if p_type not in self._interests:
            self._interests[p_type] = dict()
        if p_id in self._interests[p_type]:
            self.error('Already interested in %s.%s protocol', p_type, p_id)
            return False
        interest_factory = IAgencyInterestInternalFactory(factory)
        interest = interest_factory(self, *args, **kwargs)
        self._interests[p_type][p_id] = interest
        self.debug('Registered interest in %s.%s protocol', p_type, p_id)
        return interest

    @replay.named_side_effect('AgencyAgent.revoke_interest')
    def revoke_interest(self, factory):
        factory = IInterest(factory)
        p_type = factory.protocol_type
        p_id = factory.protocol_id
        if p_type not in self._interests or\
           p_id not in self._interests[p_type]:
            self.error('Requested to revoke interest we are not interested in'
                       ' %s.%s', p_type, p_id)
            return False
        self._interests[p_type][p_id].revoke()
        del(self._interests[p_type][p_id])

        return True

    @serialization.freeze_tag('AgencyAgent.initiate_protocol')
    @replay.named_side_effect('AgencyAgent.initiate_protocol')
    def initiate_protocol(self, factory, recipients, *args, **kwargs):
        self.log('Initiating protocol for factory: %r, args: %r, kwargs: %r',
                 factory, args, kwargs)
        factory = IInitiatorFactory(factory)
        recipients = IRecipients(recipients)
        medium_factory = IAgencyInitiatorFactory(factory)
        medium = medium_factory(self, recipients, *args, **kwargs)
        return medium.initiate()

    @serialization.freeze_tag('AgencyAgent.initiate_task')
    @replay.named_side_effect('AgencyAgent.initiate_task')
    def initiate_task(self, factory, *args, **kwargs):
        return self.initiate_protocol(factory, None, *args, **kwargs)

    @serialization.freeze_tag('AgencyAgent.retrying_protocol')
    @replay.named_side_effect('AgencyAgent.retrying_protocol')
    def retrying_protocol(self, factory, recipients, max_retries=None,
                          initial_delay=1, max_delay=None,
                          args=None, kwargs=None):
        args = args or tuple()
        kwargs = kwargs or dict()
        r = RetryingProtocol(self, factory, recipients, args, kwargs,
                             max_retries, initial_delay)
        self._retrying_protocols.append(r)
        r.notify_finish().addBoth(lambda _: self._retrying_protocols.remove(r))
        return r.initiate()

    @serialization.freeze_tag('AgencyAgent.retrying_task')
    @replay.named_side_effect('AgencyAgent.retrying_task')
    def retrying_task(self, factory, max_retries=None,
                          initial_delay=1, max_delay=None,
                          args=None, kwargs=None):
        return self.retrying_protocol(factory, None, max_retries,
                                      initial_delay, max_delay,
                                      args, kwargs)

    @serialization.freeze_tag('AgencyAgency.save_document')
    def save_document(self, document):
        return self._database.save_document(document)

    @serialization.freeze_tag('AgencyAgency.get_document')
    def get_document(self, document_id):
        return self._database.get_document(document_id)

    @serialization.freeze_tag('AgencyAgency.reload_document')
    def reload_document(self, document):
        return self._database.reload_document(document)

    @serialization.freeze_tag('AgencyAgency.delete_document')
    def delete_document(self, document):
        return self._database.delete_document(document)

    @manhole.expose()
    @serialization.freeze_tag('AgencyAgency.terminate')
    def terminate(self):
        self.call_next(self._terminate)

    # get_mode() comes from dependency.AgencyAgentDependencyMixin

    @replay.named_side_effect('AgencyAgency.call_next')
    def call_next(self, method, *args, **kwargs):
        return self.call_later(0, method, *args, **kwargs)

    @replay.named_side_effect('AgencyAgency.call_later')
    def call_later(self, time_left, method, *args, **kwargs):
        call = time.callLater(time_left, self._call, method,
                              *args, **kwargs)
        call_id = str(uuid.uuid1())
        self._store_delayed_call(call_id, call)
        return call_id

    @replay.named_side_effect('AgencyAgent.cancel_delayed_call')
    def cancel_delayed_call(self, call_id):
        try:
            call = self._delayed_calls.remove(call_id)
        except KeyError:
            self.warning('Tried to cancel nonexisting call id: %r', call_id)
            return

        if not call.active():
            self.warning('Tried to cancel nonactive call id: %r', call_id)
            return
        call.cancel()

    #StateMachineMixin

    def get_machine_state(self):
        return self._get_machine_state()

    ### ITimeProvider Methods ###

    @replay.named_side_effect('AgencyAgent.get_time')
    def get_time(self):
        return self.agency.get_time()

    ### IRecorderNode Methods ###

    def generate_identifier(self, recorder):
        assert not getattr(self, 'indentifier_generated', False)
        self._identifier_generated = True
        return (self._descriptor.doc_id, self._instance_id, )

    ### IJournalKeeper Methods ###

    def register(self, recorder):
        self.agency.register(recorder)

    def new_entry(self, journal_id, function_id, *args, **kwargs):
        return self.agency.journal_new_entry(self._descriptor.doc_id,
                                             self._instance_id,
                                             journal_id, function_id,
                                             *args, **kwargs)

    ### ISerializable Methods ###

    def snapshot(self):
        return (self._descriptor.doc_id, self._instance_id, )

    ### IAgencyAgentInternal Methods ###

    def create_binding(self, key, shard=None):
        '''Used by Interest instances.'''
        return self._messaging.personal_binding(key, shard)

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
                self._descriptor.doc_id, self._instance_id,
                listener.get_agent_side(), listener.snapshot())
            del(self._listeners[session_id])
        else:
            self.error('Tried to unregister listener with session_id: %r, '
                        'but not found!', session_id)

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

    ### IMessagingPeer Methods ###

    def on_message(self, msg):
        '''
        When a message with an already knwon traversal_id is received,
        we try to build a duplication message and send it in to a protocol
        dependent recipient. This is used in contracts traversing
        the graph, when the contract has rereached the same shard.
        This message is necessary, as silently ignoring the incoming bids
        adds a lot of latency to the nested contracts (it is waitng to receive
        message from all the recipients).
        '''
        self.log('Received message: %r', msg)

        # Check if it isn't expired message
        time_left = time.left(msg.expiration_time)
        if time_left < 0:
            self.log('Throwing away expired message. Time left: %s, '
                     'msg_class: %r', msg.get_msg_class(), time_left)
            return False

        # Check for known traversal ids:
        if IFirstMessage.providedBy(msg):
            t_id = msg.traversal_id
            if t_id is None:
                self.warning(
                    "Received corrupted message. The traversal_id is None ! "
                    "Message: %r", msg)
                return False
            if t_id in self._traversal_ids:
                self.log('Throwing away already known traversal id %r, '
                         'msg_class: %r', msg.get_msg_class(), t_id)
                recp = msg.duplication_recipient()
                if recp:
                    resp = msg.duplication_message()
                    self.send_msg(recp, resp)
                return False
            else:
                self._traversal_ids.set(t_id, True, msg.expiration_time)

        # Handle registered dialog
        if IDialogMessage.providedBy(msg):
            recv_id = msg.receiver_id
            if recv_id is not None and recv_id in self._listeners:
                listener = self._listeners[recv_id]
                listener.on_message(msg)
                return True

        # Handle new conversation coming in (interest)
        p_type = msg.protocol_type
        if p_type in self._interests:
            p_id = msg.protocol_id
            interest = self._interests[p_type].get(p_id)
            if interest and isinstance(msg, interest.factory.initiator):
                if interest.schedule_message(msg):
                    return True

        self.warning("Couldn't find appropriate listener for message: "
                     "%s", msg.get_msg_class())
        return False

    def get_queue_name(self):
        return self._descriptor.doc_id

    def get_shard_name(self):
        return self._descriptor.shard

    ### Introspection Methods ###

    @manhole.expose()
    def get_agent(self):
        '''get_agent() -> Returns the agent side instance.'''
        return self.agent

    @manhole.expose()
    def list_partners(self):
        t = text_helper.Table(fields=["Partner", "Id", "Shard", "Role"],
                  lengths = [20, 35, 35, 10])

        partners = self.agent.query_partners('all')
        return t.render(
            (type(p).__name__, p.recipient.key, p.recipient.shard, p.role, )\
            for p in partners)

    @manhole.expose()
    def list_resource(self):
        t = text_helper.Table(fields=["Name", "Totals", "Allocated"],
                  lengths = [20, 20, 20])
        totals, allocated = self.agent.list_resource()

        def iter(totals, allocated):
            for x in totals:
                yield x, totals[x], allocated[x]

        return t.render(iter(totals, allocated))

    ### Protected Methods ###

    def wait_for_listeners_finish(self):
        '''Used by tests.'''

        def wait_for_listener(listener):
            d = listener.notify_finish()
            d.addErrback(self._ignore_initiator_failed)
            return d

        a = [interest.wait_finished() for interest in self._iter_interests()]
        b = [wait_for_listener(l) for l in self._listeners.itervalues()]
        return defer.DeferredList(a + b)

    def is_idle(self):
        return self.has_empty_listeners() and \
               self.has_all_interests_idle() and \
               not self.has_pending_calls() and \
               self.is_ready()

    def is_ready(self):
        return self._cmp_state(AgencyAgentState.ready)

    def has_empty_listeners(self):
        return (len(list(self._listeners.itervalues())) == 0)

    def has_pending_calls(self):
        return not all(
            not call.active() for call in self._delayed_calls.itervalues())

    def has_all_interests_idle(self):
        return all(i.is_idle() for i in self._iter_interests())

    @manhole.expose()
    def show_activity(self):
        if self.is_idle():
            return None
        resp = "\n%r id: %r\n state: %r" % \
               (self.agent.__class__.__name__, self.get_descriptor().doc_id,
                self._get_machine_state().name)
        if not self.has_empty_listeners():
            resp += '\nListeners: \n'
            t = text_helper.Table(fields=["Class"], lengths = [60])
            resp += t.render((i.get_agent_side().__class__.__name__, ) \
                             for i in self._listeners.itervalues())
        if self.has_pending_calls():
            resp += "\nPending calls: \n"
            t = text_helper.Table(fields=["Call"], lengths = [60])
            resp += t.render((str(call), ) \
                             for call in self._delayed_calls.itervalues())

        if not self.has_all_interests_idle():
            resp += "\nInterests not idle: \n"
            t = text_helper.Table(fields=["Factory"], lengths = [60])
            resp += t.render((str(call.factory), ) \
                             for call in self._iter_interests())
        resp += "#" * 60
        return resp

    ### Private Methods ###

    def _subscribe_for_descriptor_changes(self):
        return self._database.changes_listener(
            (self._descriptor.doc_id, ), self._descriptor_changed)

    def _descriptor_changed(self, doc_id, rev):
        self.warning('Received the notification about other database session '
                     'changing our descriptor. This means that I got '
                     'restarted on some other machine and need to commit '
                     'suacide :(. Or you have a bug ;).')
        return self.terminate_hard()

    def _store_instance_id(self):
        '''
        Run at the initialization before calling any code at agent-side.
        Ensures that descriptor holds our value, this effectively creates a
        lock on the descriptor - if other instance is running somewhere out
        there it would get the notification update and suacide.
        '''

        def do_set(desc):
            desc.instance_id = self._instance_id

        return self.update_descriptor(do_set)

    def _load_configuration(self):

        def not_found(fail, doc_id):
            fail.trap(NotFoundError)
            self.warning('Agents configuration not found in database. '
                         'Expected doc_id: %r', doc_id)
            return

        d_id = self.agent.configuration_doc_id
        d = self.get_document(d_id)
        d.addErrback(not_found, d_id)
        return d

    def _next_update(self):

        def saved(desc, result, d):
            self.log("Updating descriptor: %r", desc)
            self._descriptor = desc
            d.callback(result)

        def error(failure, d):
            if failure.check(ConflictError):
                self.warning('Descriptor update conflict, killing the agent.')
                self.call_next(self.terminate_hard)
            else:
                self.error("Failed updating descriptor: %s",
                           failure.getErrorMessage())
            d.errback(failure)

        def next_update(any=None):
            self._updating = False
            self.call_next(self._next_update)
            return any

        if self._updating:
            # Currently updating descriptor
            return

        if not self._update_queue:
            # No more pending updates
            return

        d, fun, args, kwargs = self._update_queue.pop(0)
        self._updating = True
        try:
            desc = self.get_descriptor()
            result = fun(desc, *args, **kwargs)
            assert not isinstance(result, (defer.Deferred, fiber.Fiber))
            save_d = self.save_document(desc)
            save_d.addCallbacks(callback=saved, callbackArgs=(result, d),
                                errback=error, errbackArgs=(d, ))
            save_d.addBoth(next_update)
        except:
            d.errback()
            next_update()

    def _terminate_procedure(self, body):
        self.log("in _terminate_procedure()")
        assert callable(body)

        if self._terminating:
            # Already terminating
            return
        self._terminating = True

        # Revoke all queued protocols
        [i.clear_queue() for i in self._iter_interests()]

        # Revoke all interests
        [self.revoke_interest(i.factory) for i in list(self._iter_interests())]

        # Kill all retrying protocols
        d = defer.DeferredList([x.give_up() for x in self._retrying_protocols])
        # Kill all listeners
        d.addBoth(self._kill_all_listeners)
        # Run code specific to the given shutdown
        d.addBoth(lambda _: body())
        # Tell the agency we are no more
        d.addBoth(lambda _: self._unregister_from_agency())
        # Close the messaging connection
        d.addBoth(lambda _: self._messaging.disconnect())
        # Close the database connection
        d.addBoth(lambda _: self._database.disconnect())
        return d

    def _unregister_from_agency(self):
        self.agency.journal_agent_deleted(self._descriptor.doc_id,
                                          self._instance_id)
        self.agency.unregister_agent(self)

    @manhole.expose()
    def terminate_hard(self):
        '''Kill the agent without notifying anybody.'''

        def generate_body():
            '''nothing to do'''

        return self._terminate_procedure(generate_body)

    def _terminate(self):
        '''terminate() -> Shutdown agent gently removing the descriptor and
        notifying partners.'''

        def generate_body():
            d = defer.succeed(None)
            # Run IAgent.shutdown() and wait for
            # the listeners to finish the job
            d.addBoth(self._run_and_wait, self.agent.shutdown)
            # Delete the descriptor
            d.addBoth(lambda _: self.delete_document(self._descriptor))
            # TODO: delete the queue
            return d

        return self._terminate_procedure(generate_body)

    def _run_and_wait(self, _, method, *args, **kwargs):
        '''
        Run a agent-side method and wait for all the listeners
        to finish processing.
        '''
        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addBoth(self.wait_for_listeners_finish)
        return d

    def _iter_interests(self):
        return (interest
                for interests in self._interests.itervalues()
                for interest in interests.itervalues())

    def _kill_all_listeners(self, *_):

        def expire_one(listener):
            d = listener.expire_now()
            d.addErrback(self._ignore_initiator_failed)
            return d

        d = defer.DeferredList([expire_one(x)
                                for x in self._listeners.values()])
        return d

    def _ignore_initiator_failed(self, fail):
        if fail.check(InitiatorFailed):
            self.log('Swallowing %r expection', fail.value)
            return None
        else:
            self.log('Reraising exception %r', fail)
            fail.raiseException()

    def _call_initiate(self, *args, **kwargs):
        self._set_state(AgencyAgentState.initiating)
        d = defer.maybeDeferred(self.agent.initiate, *args, **kwargs)
        d.addCallback(fiber.drop_param, self._set_state,
                      AgencyAgentState.initiated)
        return d

    def _call_startup(self):
        self._set_state(AgencyAgentState.starting_up)
        d = defer.maybeDeferred(self.agent.startup)
        d.addCallback(fiber.drop_param, self._ready)
        d.addCallback(fiber.override_result, self)
        d.addErrback(self._error_handler)
        return d

    def _ready(self):
        self._set_state(AgencyAgentState.ready)

    def _error_handler(self, e):
        self._set_state(AgencyAgentState.error)
        error_handler(self, e)

    def _store_delayed_call(self, call_id, call):
        if call.active():
            self.log('Storing delayed call with id %r', call_id)
            self._delayed_calls.set(call_id, call, call.getTime() + 1)

    def _call(self, method, *args, **kwargs):

        def raise_on_fiber(res):
            if isinstance(d.result, fiber.Fiber):
                raise RuntimeError("We don't are not expecting %r method to "
                                   "return a Fiber, which it did!")

        self.log('Calling method %r, with args: %r, kwargs: %r', method,
                 args, kwargs)
        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addCallback(raise_on_fiber)
        d.addErrback(self._error_handler)
        return d


class RetryingProtocol(common.TransientInitiatorMediumBase, log.Logger):

    implements(ISerializable)

    log_category="retrying-protocol"
    type_name="retrying-protocol"

    def __init__(self, medium, factory, recipients, args, kwargs,
                 max_retries=None, initial_delay=1, max_delay=None):
        common.TransientInitiatorMediumBase.__init__(self)
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

    def initiate(self):
        self.call_next(self._bind)
        return self

    ### Public Methods ###

    @serialization.freeze_tag('RetryingProtocol.notify_finish')
    def notify_finish(self):
        return common.TransientInitiatorMediumBase.notify_finish(self)

    @serialization.freeze_tag('RetryingProtocol.give_up')
    def give_up(self):
        self.max_retries = self.attempt - 1
        if self._delayed_call and self._delayed_call.active():
            self._delayed_call.cancel()
            return defer.succeed(None)
        if self._initiator:
            d = self._initiator._get_state().medium.expire_now()
            d.addErrback(self.medium._ignore_initiator_failed)
            return d

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Required by TransientInitiatorMediumbase ###

    def call_next(self, _method, *args, **kwargs):
        return self.medium.call_next(_method, *args, **kwargs)

    ### Private Methods ###

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
        common.TransientInitiatorMediumBase._terminate(self, result)

    def _wait_and_retry(self, failure):
        self.info('Retrying protocol for factory: %r failed for the %d time. ',
                  self.factory, self.attempt)

        self._initiator = None

        # check if we are done
        if self.max_retries is not None and self.attempt > self.max_retries:
            self.info("Will not try to restart.")
            common.TransientInitiatorMediumBase._terminate(self, failure)
            return

        # do retry
        self.info('Will retry in %d seconds', self.delay)
        self._delayed_call = time.callLater(self.delay, self._bind)

        # adjust the delay
        if self.max_delay is None:
            self.delay *= 2
        elif self.delay < self.max_delay:
            self.delay = min((2 * self.delay, self.max_delay, ))
