# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

# Import standard library modules
import copy
import uuid
import weakref
import warnings
import socket

# Import external project modules
from twisted.python.failure import Failure
from zope.interface import implements

# Import feat modules
from feat.agencies import common, dependency, retrying, periodic
from feat.agents.base import recipient, replay, descriptor
from feat.agents.base.agent import registry_lookup
from feat.common import (log, defer, fiber, serialization, journal, time,
                         manhole, error_handler, text_helper, container,
                         first, )

# Import interfaces
from interface import *
from feat.interface.agency import *
from feat.interface.agent import *
from feat.interface.generic import *
from feat.interface.journal import *
from feat.interface.protocols import *
from feat.interface.recipient import *
from feat.interface.serialization import *


# How many entries should be between two snapshot at minimum
MIN_ENTRIES_PER_SNAPSHOT = 1000


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

        self._protocols = {} # {puid: IAgencyProtocolInternal}
        self._interests = {} # {protocol_type: {protocol_id: IInterest}}
        self._long_running_protocols = [] # Long running protocols

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

        self._entries_since_snapshot = 0

    ### Public Methods ###

    def initiate(self, **kwargs):
        '''Establishes the connections to database and messaging platform,
        taking into account that it might meen performing asynchronous job.'''
        run_startup = kwargs.pop('run_startup', True)

        setter = lambda value, name: setattr(self, name, value)

        d = defer.Deferred()
        d.addCallback(defer.drop_param,
                      self.agency._messaging.get_connection, self)
        d.addCallback(setter, '_messaging')
        d.addCallback(defer.drop_param,
                      self.agency._database.get_connection)
        d.addCallback(setter, '_database')
        d.addCallback(defer.drop_param,
                      self._reload_descriptor)
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
                      self._call_initiate, **kwargs)
        d.addCallback(defer.drop_param, self.call_next, self._call_startup,
                      call_startup=run_startup)
        d.addCallback(defer.override_result, self)
        d.addErrback(self._startup_error)

        # Ensure the execution chain is broken
        self.call_next(d.callback, None)

        return d

    @manhole.expose()
    def get_agent_id(self):
        return self._descriptor.doc_id

    def get_full_id(self):
        desc = self._descriptor
        return desc.doc_id + u"/" + unicode(desc.instance_id)

    def snapshot_agent(self):
        '''Gives snapshot of everything related to the agent'''
        protocols = [i.get_agent_side() for i in self._protocols.values()]
        return (self.agent, protocols, )

    def journal_agent_created(self):
        factory = type(self.agent)
        self.agency.journal_agent_created(
            self._descriptor.doc_id, self._instance_id,
            factory, self.snapshot())

    def check_if_should_snapshot(self, force=False):
        if force or self._entries_since_snapshot > MIN_ENTRIES_PER_SNAPSHOT:
            self.journal_snapshot()
        else:
            self.log('Skipping snapshot, number of entries %d < %d',
                     self._entries_since_snapshot, MIN_ENTRIES_PER_SNAPSHOT)

    def journal_snapshot(self):
        # Remove all the entries for the agent from  the registry,
        # so that snapshot contains full objects not just the references
        agent_id = self._descriptor.doc_id
        self.agency.remove_agent_recorders(agent_id)
        self._entries_since_snapshot = 0
        self.agency.journal_agent_snapshot(
            agent_id, self._instance_id, self.snapshot_agent())

    def journal_protocol_created(self, *args, **kwargs):
        self.agency.journal_protocol_created(self._descriptor.doc_id,
                                             self._instance_id,
                                             *args, **kwargs)

    @serialization.freeze_tag('AgencyAgent.start_agent')
    def start_agent(self, desc, **kwargs):
        return self.agency.start_agent(desc, **kwargs)

    @serialization.freeze_tag('AgencyAgent.check_if_hosted')
    def check_if_hosted(self, agent_id):
        d = self.agency.find_agent(agent_id)
        d.addCallback(bool)
        return d

    def on_killed(self):
        '''called as part of SIGTERM handler.'''

        def generate_body():
            d = defer.succeed(None)
            # run IAgent.killed() and wait for the protocols to finish the job
            d.addBoth(self._run_and_wait, self.agent.on_agent_killed)
            return d

        return self._terminate_procedure(generate_body)

    ### IAgencyAgent Methods ###

    @replay.named_side_effect('AgencyAgent.observe')
    def observe(self, _method, *args, **kwargs):
        res = common.Observer(_method, *args, **kwargs)
        self.call_next(res.initiate)
        return res

    @replay.named_side_effect('AgencyAgent.get_hostname')
    def get_hostname(self):
        return self.agency.get_hostname()

    @replay.named_side_effect('AgencyAgent.get_hostname')
    def get_ip(self):
        return self.agency.get_ip()

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

    @replay.named_side_effect('AgencyAgent.upgrade_agency')
    def upgrade_agency(self, upgrade_cmd):
        self.agency.upgrade(upgrade_cmd)

    @serialization.freeze_tag('AgencyAgent.leave_shard')
    def leave_shard(self, shard):
        self.log("Leaving shard %r", shard)
        bindings = self._messaging.get_bindings(shard)
        return defer.DeferredList([x.revoke() for x in bindings])

    @replay.named_side_effect('AgencyAgent.register_interest')
    def register_interest(self, agent_factory, *args, **kwargs):
        agent_factory = IInterest(agent_factory)
        if not IFirstMessage.implementedBy(agent_factory.initiator):
            raise TypeError(
                "%r.initiator expected to implemented IFirstMessage. Got %r" %\
                (agent_factory, agent_factory.initiator, ))
        p_type = agent_factory.protocol_type
        p_id = agent_factory.protocol_id
        if p_type not in self._interests:
            self._interests[p_type] = dict()
        if p_id in self._interests[p_type]:
            self.error('Already interested in %s.%s protocol', p_type, p_id)
            return False
        interest_factory = IAgencyInterestInternalFactory(agent_factory)
        interest = interest_factory(self, *args, **kwargs)
        self._interests[p_type][p_id] = interest
        self.debug('Registered interest in %s.%s protocol', p_type, p_id)
        return interest

    @replay.named_side_effect('AgencyAgent.revoke_interest')
    def revoke_interest(self, agent_factory):
        agent_factory = IInterest(agent_factory)
        p_type = agent_factory.protocol_type
        p_id = agent_factory.protocol_id
        if (p_type not in self._interests
            or p_id not in self._interests[p_type]):
            self.error('Requested to revoke interest we are not interested in'
                       ' %s.%s', p_type, p_id)
            return False
        self._interests[p_type][p_id].revoke()
        del(self._interests[p_type][p_id])

        return True

    @serialization.freeze_tag('AgencyAgent.initiate_protocol')
    @replay.named_side_effect('AgencyAgent.initiate_protocol')
    def initiate_protocol(self, factory, *args, **kwargs):
        return self._initiate_protocol(factory, args, kwargs)

    @serialization.freeze_tag('AgencyAgent.retrying_protocol')
    @replay.named_side_effect('AgencyAgent.retrying_protocol')
    def retrying_protocol(self, factory, recipients=None,
                          max_retries=None, initial_delay=1,
                          max_delay=None, args=None, kwargs=None):
        #FIXME: this is not needed in agency side API, could be in agent
        Factory = retrying.RetryingProtocolFactory
        factory = Factory(factory, max_retries=max_retries,
                          initial_delay=initial_delay, max_delay=max_delay)
        if recipients is not None:
            args = (recipients, ) + args if args else (recipients, )
        return self._initiate_protocol(factory, args, kwargs)

    @serialization.freeze_tag('AgencyAgent.periodic_protocol')
    @replay.named_side_effect('AgencyAgent.periodic_protocol')
    def periodic_protocol(self, factory, period, *args, **kwargs):
        #FIXME: this is not needed in agency side API, could be in agent
        factory = periodic.PeriodicProtocolFactory(factory, period)
        return self._initiate_protocol(factory, args, kwargs)

    @serialization.freeze_tag('AgencyAgent.initiate_protocol')
    @replay.named_side_effect('AgencyAgent.initiate_protocol')
    def initiate_task(self, *args, **kwargs):
        warnings.warn("initiate_task() is deprecated, "
                      "please use initiate_protocol()",
                      DeprecationWarning)
        return self.initiate_protocol(*args, **kwargs)

    @serialization.freeze_tag('AgencyAgent.retrying_protocol')
    @replay.named_side_effect('AgencyAgent.retrying_protocol')
    def retrying_task(self, *args, **kwargs):
        warnings.warn("retrying_task() is deprecated, "
                      "please use retrying_protocol()",
                      DeprecationWarning)
        return self.retrying_protocol(*args, **kwargs)

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

    @serialization.freeze_tag('AgencyAgency.query_view')
    def query_view(self, factory, **options):
        return self._database.query_view(factory, **options)

    @manhole.expose()
    @serialization.freeze_tag('AgencyAgency.terminate')
    def terminate(self):
        self.call_next(self._terminate)

    # get_mode() comes from dependency.AgencyAgentDependencyMixin

    @replay.named_side_effect('AgencyAgency.call_next')
    def call_next(self, method, *args, **kwargs):
        return self.call_later_ex(0, method, args, kwargs)

    @replay.named_side_effect('AgencyAgency.call_later')
    def call_later(self, time_left, method, *args, **kwargs):
        return self.call_later_ex(time_left, method, args, kwargs)

    @replay.named_side_effect('AgencyAgency.call_later_ex')
    def call_later_ex(self, time_left, method,
                      args=None, kwargs=None, busy=True):
        args = args or []
        kwargs = kwargs or {}
        call = time.callLater(time_left, self._call, method,
                              *args, **kwargs)
        call_id = str(uuid.uuid1())
        self._store_delayed_call(call_id, call, busy)
        return call_id

    @replay.named_side_effect('AgencyAgent.cancel_delayed_call')
    def cancel_delayed_call(self, call_id):
        try:
            _busy, call = self._delayed_calls.remove(call_id)
        except KeyError:
            self.warning('Tried to cancel nonexisting call id: %r', call_id)
            return

        self.log('Canceling delayed call with id %r (active: %s)',
                 call_id, call.active())
        if not call.active():
            self.log('Tried to cancel nonactive call id: %r', call_id)
            return
        call.cancel()

    #StateMachineMixin

    def get_machine_state(self):
        return self._get_machine_state()

    ### ITimeProvider Methods ###

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
        self._entries_since_snapshot += 1
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

    def register_protocol(self, protocol):
        protocol = IAgencyProtocolInternal(protocol)
        self.log('Registering protocol guid: %r', protocol.guid)
        assert protocol.guid not in self._protocols
        self._protocols[protocol.guid] = protocol
        return protocol

    def unregister_protocol(self, protocol):
        if protocol.guid in self._protocols:
            self.log('Unregistering protocol guid: %r', protocol.guid)
            protocol = self._protocols[protocol.guid]
            self.agency.journal_protocol_deleted(
                self._descriptor.doc_id, self._instance_id,
                protocol.get_agent_side(), protocol.snapshot())
            del self._protocols[protocol.guid]
        else:
            self.error('Tried to unregister protocol with guid: %r, '
                        'but not found!', protocol.guid)

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
                     'msg_class: %r', time_left, msg.get_msg_class())
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
            if recv_id is not None and recv_id in self._protocols:
                protocol = self._protocols[recv_id]
                protocol.on_message(msg)
                return True

        # Handle new conversation coming in (interest)
        p_type = msg.protocol_type
        if p_type in self._interests:
            p_id = msg.protocol_id
            interest = self._interests[p_type].get(p_id)
            if interest and interest.schedule_message(msg):
                return True

        self.warning("Couldn't find appropriate protocol for message: "
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
        return t.render((type(p).__name__, p.recipient.key,
                         p.recipient.shard, p.role)
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
        warnings.warn("AgencyAgent.wait_for_listeners_finish() is deprecated, "
                      "please use AgencyAgent.wait_for_protocols_finish()",
                      DeprecationWarning)
        return self.wait_for_protocols_finish()

    def wait_for_protocols_finish(self):
        '''Used by tests.'''

        def wait_for_protocol(protocol):
            d = protocol.notify_finish()
            d.addErrback(Failure.trap, ProtocolFailed)
            return d

        a = [interest.wait_finished() for interest in self._iter_interests()]
        b = [wait_for_protocol(l) for l in self._protocols.itervalues()]
        return defer.DeferredList(a + b)

    def is_idle(self):
        return (self.is_ready()
                and self.has_empty_protocols()
                and self.has_all_interests_idle()
                and not self.has_busy_calls()
                and self.has_all_long_running_protocols_idle())

    def is_ready(self):
        return self._cmp_state(AgencyAgentState.ready)

    def has_empty_protocols(self):
        return (len([l for l in self._protocols.itervalues()
                     if not l.is_idle()]) == 0)

    def has_busy_calls(self):
        for busy, call in self._delayed_calls.itervalues():
            if busy and call.active():
                return True
        return False

    def has_all_interests_idle(self):
        return all(i.is_idle() for i in self._iter_interests())

    def has_all_long_running_protocols_idle(self):
        return all(i.is_idle() for i in self._long_running_protocols)

    @manhole.expose()
    def show_activity(self):
        if self.is_idle():
            return None
        resp = "\n%r id: %r\n state: %r" % \
               (self.agent.__class__.__name__, self.get_descriptor().doc_id,
                self._get_machine_state().name)
        if not self.has_empty_protocols():
            resp += '\nprotocols: \n'
            t = text_helper.Table(fields=["Class"], lengths = [60])
            resp += t.render((i.get_agent_side().__class__.__name__, ) \
                             for i in self._protocols.itervalues())
        if self.has_busy_calls():
            resp += "\nbusy calls: \n"
            t = text_helper.Table(fields=["Call"], lengths = [60])
            resp += t.render((str(call), ) \
                             for busy, call in self._delayed_calls.itervalues()
                             if busy and call.active())

        if not self.has_all_interests_idle():
            resp += "\nInterests not idle: \n"
            t = text_helper.Table(fields=["Factory"], lengths = [60])
            resp += t.render((str(call.agent_factory), ) \
                             for call in self._iter_interests())
        resp += "#" * 60
        return resp

    def on_disconnect(self):
        if self._cmp_state(AgencyAgentState.ready):
            self._set_state(AgencyAgentState.disconnected)
            self.call_next(self.agent.on_agent_disconnect)

    def on_reconnect(self):
        if self._cmp_state(AgencyAgentState.disconnected):
            self._set_state(AgencyAgentState.ready)
            self.call_next(self.agent.on_agent_reconnect)

    ### Private Methods ###

    def _initiate_protocol(self, factory, args, kwargs):
        self.log('Initiating protocol for factory: %r, args: %r, kwargs: %r',
                 factory, args, kwargs)
        args = args or ()
        kwargs = kwargs or {}
        factory = IInitiatorFactory(factory)
        medium_factory = IAgencyInitiatorFactory(factory)
        medium = medium_factory(self, *args, **kwargs)
        if ILongRunningProtocol.providedBy(medium):
            self._long_running_protocols.append(medium)
            cb = lambda _: self._long_running_protocols.remove(medium)
            medium.notify_finish().addBoth(cb)
        return medium.initiate()

    def _subscribe_for_descriptor_changes(self):
        return self._database.changes_listener(
            (self._descriptor.doc_id, ), self._descriptor_changed)

    def _descriptor_changed(self, doc_id, rev):
        self.warning('Received the notification about other database session '
                     'changing our descriptor. This means that I got '
                     'restarted on some other machine and need to commit '
                     'suacide :(. Or you have a bug ;).')
        return self.terminate_hard()

    def _reload_descriptor(self):

        def setter(value):
            self._descriptor = value

        d = self.reload_document(self._descriptor)
        d.addCallback(setter)
        return d

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
        except Exception as e:
            d.errback(e)
            next_update()

    def _terminate_procedure(self, body):
        assert callable(body)

        if self._cmp_state(AgencyAgentState.terminating):
            return
        self._set_state(AgencyAgentState.terminating)

        # Revoke all queued protocols
        [i.clear_queue() for i in self._iter_interests()]

        # Revoke all interests
        [self.revoke_interest(i.agent_factory)
         for i in list(self._iter_interests())]

        d = defer.succeed(None)

        # Cancel all long running protocols
        d.addBoth(defer.drop_param, self._cancel_long_running_protocols)
        # Cancel all delayed calls
        d.addBoth(self._cancel_all_delayed_calls)
        # Kill all protocols
        d.addBoth(self._kill_all_protocols)
        # Again, just in case
        d.addBoth(self._cancel_all_delayed_calls)
        # Run code specific to the given shutdown
        d.addBoth(defer.drop_param, body)
        # Tell the agency we are no more
        d.addBoth(defer.drop_param, self._unregister_from_agency)
        # Close the messaging connection
        d.addBoth(defer.drop_param, self._messaging.disconnect)
        # Close the database connection
        d.addBoth(defer.drop_param, self._database.disconnect)
        d.addBoth(defer.drop_param,
                  self._set_state, AgencyAgentState.terminated)
        return d

    def _unregister_from_agency(self):
        self.agency.journal_agent_deleted(self._descriptor.doc_id,
                                          self._instance_id)
        self.agency.unregister_agent(self)

    def _cancel_long_running_protocols(self):
        return defer.DeferredList([defer.maybeDeferred(x.cancel)
                                   for x in self._long_running_protocols])

    @manhole.expose()
    def terminate_hard(self):
        '''Kill the agent without notifying anybody.'''

        def generate_body():
            d = defer.succeed(None)
            # run IAgent.killed() and wait for the listeners to finish the job
            d.addBoth(self._run_and_wait, self.agent.killed)
            return d

        return self._terminate_procedure(generate_body)

    def _terminate(self):
        '''terminate() -> Shutdown agent gently removing the descriptor and
        notifying partners.'''

        def generate_body():
            d = defer.succeed(None)
            # Run IAgent.shutdown() and wait for
            # the protocols to finish the job
            d.addBoth(self._run_and_wait, self.agent.shutdown_agent)
            # Delete the descriptor
            d.addBoth(lambda _: self.delete_document(self._descriptor))
            # TODO: delete the queue
            return d

        return self._terminate_procedure(generate_body)

    def _run_and_wait(self, _, method, *args, **kwargs):
        '''
        Run a agent-side method and wait for all the protocols
        to finish processing.
        '''
        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addBoth(defer.drop_param, self.wait_for_protocols_finish)
        return d

    def _iter_interests(self):
        return (interest
                for interests in self._interests.itervalues()
                for interest in interests.itervalues())

    def _kill_all_protocols(self, *_):

        def expire_one(protocol):
            d = protocol.cleanup()
            d.addErrback(Failure.trap, ProtocolFailed)
            return d

        d = defer.DeferredList([expire_one(x)
                                for x in self._protocols.values()])
        return d

    def _call_initiate(self, **kwargs):
        self._set_state(AgencyAgentState.initiating)
        d = defer.maybeDeferred(self.agent.initiate_agent, **kwargs)
        d.addCallback(fiber.drop_param, self._set_state,
                      AgencyAgentState.initiated)
        return d

    def _call_startup(self, call_startup=True):
        self._set_state(AgencyAgentState.starting_up)
        d = defer.succeed(None)
        if call_startup:
            d.addCallback(defer.drop_param, self.agent.startup_agent)
        d.addCallback(fiber.drop_param, self._become_ready)
        d.addErrback(self._startup_error)
        return d

    def _become_ready(self):
        self._set_state(AgencyAgentState.ready)

    def _startup_error(self, fail):
        self._error_handler(fail)
        self.error("Agent raised an error while starting up. "
                   "He will be punished by terminating. Medium state while "
                   "that happend: %r", self._get_machine_state())
        self.terminate()

    def _store_delayed_call(self, call_id, call, busy):
        if call.active():
            self.log('Storing delayed call with id %r', call_id)
            self._delayed_calls.set(call_id, (busy, call), call.getTime() + 1)

    def _cancel_all_delayed_calls(self):
        for call_id, (_busy, call) in self._delayed_calls.iteritems():
            self.log('Canceling delayed call with id %r (active: %s)',
                     call_id, call.active())
            if call.active():
                call.cancel()
        self._delayed_calls.clear()

    def _call(self, method, *args, **kwargs):

        def raise_on_fiber(res):
            if isinstance(res, fiber.Fiber):
                raise RuntimeError("We are not expecting method %r to "
                                   "return a Fiber, which it did!" % method)
            return res

        self.log('Calling method %r, with args: %r, kwargs: %r', method,
                 args, kwargs)
        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addCallback(raise_on_fiber)
        d.addErrback(self._error_handler)
        return d


class Agency(log.FluLogKeeper, log.Logger, manhole.Manhole,
             dependency.AgencyDependencyMixin, common.ConnectionManager):

    log_category = 'agency'

    __metaclass__ = type('MetaAgency', (type(manhole.Manhole),
                                        type(log.FluLogKeeper)), {})

    implements(IAgency, IExternalizer, ITimeProvider)

    agency_agent_factory = AgencyAgent

    _error_handler = error_handler

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)
        dependency.AgencyDependencyMixin.__init__(self, ExecMode.test)
        common.ConnectionManager.__init__(self)

        self._agents = []

        self.registry = weakref.WeakValueDictionary()
        # IJournaler
        self._journaler = None
        # IJournalerConnection
        self._jourconn = None
        # IDbConnectionFactory
        self._database = None
        # IConnectionFactory
        self._messaging = None
        self._hostname = None

        self._agency_id = str(uuid.uuid1())

        self.add_reconnected_cb(self._notify_agents_about_reconnection)
        self.add_disconnected_cb(self._notify_agents_about_disconnection)

    ### Public Methods ###

    def initiate(self, messaging, database, journaler):
        '''
        Asynchronous part of agency initialization. Needs to be called before
        agency is used for anything.
        '''
        self._hostname = unicode(socket.gethostbyaddr(socket.gethostname())[0])
        self._ip = unicode(socket.gethostbyname(socket.gethostname()))
        self._database = IDbConnectionFactory(database)
        self._messaging = IConnectionFactory(messaging)
        self._journaler = IJournaler(journaler)
        self._jourconn = self._journaler.get_connection(self)

        self._messaging.add_disconnected_cb(self._on_disconnected)
        self._messaging.add_reconnected_cb(self._check_msg_and_db_state)
        self._database.add_disconnected_cb(self._on_disconnected)
        self._database.add_reconnected_cb(self._check_msg_and_db_state)
        self._check_msg_and_db_state()
        return defer.succeed(self)

    @property
    def agency_id(self):
        return self._agency_id

    def iter_agents(self):
        return iter(self._agents)

    def get_agency(self, agency_id):
        if agency_id == self.agency_id:
            return self
        return None

    def get_agent(self, agent_id):
        for agent in self._agents:
            if agent.get_agent_id() == agent_id:
                return agent
        return None

    @manhole.expose()
    def start_agent(self, descriptor, **kwargs):
        factory = IAgentFactory(registry_lookup(descriptor.document_type))
        self.log('I will start: %r agent. Kwargs: %r', factory, kwargs)
        medium = self.agency_agent_factory(self, factory, descriptor)
        self._agents.append(medium)

        d = self.wait_connected()
        d.addCallback(defer.drop_param, medium.initiate, **kwargs)
        return d

    @manhole.expose()
    def get_hostname(self):
        return self._hostname

    @manhole.expose()
    def get_ip(self):
        return self._ip

    @manhole.expose()
    def get_logging_filter(self):
        return log.FluLogKeeper.get_debug()

    @manhole.expose()
    def set_logging_filter(self, filter):
        log.FluLogKeeper.set_debug(filter)

    def shutdown(self):
        '''Called when the agency is ordered to shutdown all the agents..'''
        d = defer.DeferredList([x._terminate() for x in self._agents])
        d.addCallback(lambda _: self._messaging.disconnect())
        return d

    def upgrade(self, upgrade_cmd):
        '''Called as the result of upgrade process triggered by host agent.'''
        return self.shutdown()

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
        self.remove_agent_recorders(agent_id)

    def remove_agent_recorders(self, agent_id):
        for key in self.registry.keys():
            if key[0] == agent_id:
                self.log("Removing recorder id %r, instance: %r",
                         key, self.registry[key])
                del(self.registry[key])

    def is_idle(self):
        return all([x.is_idle() for x in self._agents])

    ### Journaling Methods ###

    def register(self, recorder):
        j_id = recorder.journal_id
        self.log('Registering recorder: %r, id: %r',
                 recorder.__class__.__name__, j_id)
        if j_id in self.registry:
            raise RuntimeError(
                'Journal id %r already in registry, it points to %r object'
                % (j_id, self.registry[j_id], ))
        self.registry[j_id] = recorder

    def journal_new_entry(self, agent_id, instance_id, journal_id,
                          function_id, *args, **kwargs):
        return self._jourconn.new_entry(agent_id, instance_id, journal_id,
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

    def journal_protocol_created(self, agent_id, instance_id, protocol_factory,
                                 medium, *args, **kwargs):
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

    @serialization.freeze_tag('Agency.get_time')
    @replay.named_side_effect('Agency.get_time')
    def get_time(self):
        return time.time()

    ### Introspection and Manhole Methods ###

    @manhole.expose()
    def find_agent(self, desc):
        '''find_agent(agent_id_or_descriptor) -> Gives medium class of the
        agent if the agency hosts it.'''
        agent_id = (desc.doc_id
                    if isinstance(desc, descriptor.Descriptor)
                    else desc)
        self.log("I'm trying to find the agent with id: %s", agent_id)
        result = first(x for x in self._agents
                       if x._descriptor.doc_id == agent_id)
        return defer.succeed(result)

    @manhole.expose()
    def snapshot_agents(self, force=False):
        '''snapshot_agents(force=False): snapshot agents if number of entries
        from last snapshot if greater than 1000. Use force=True to override.'''
        for agent in self._agents:
            agent.check_if_should_snapshot(force)

    @manhole.expose()
    def list_agents(self):
        '''list_agents() -> List agents hosted by the agency.'''
        t = text_helper.Table(fields=("Agent ID", "Agent class", "State"),
                              lengths=(40, 25, 15))

        return t.render((a._descriptor.doc_id, a.log_name,
                         a._get_machine_state().name)
                        for a in self._agents)

    @manhole.expose()
    def get_nth_agent(self, n):
        '''get_nth_agent(n) -> Get the agent by his index in the list.'''
        return self._agents[n]

    @manhole.expose()
    def get_agents(self):
        '''get_agents() -> Get the list of agents hosted by this agency.'''
        return self._agents

    ### private ###

    def _notify_agents_about_disconnection(self):
        for medium in self.iter_agents():
            medium.on_disconnect()

    def _notify_agents_about_reconnection(self):
        for medium in self.iter_agents():
            medium.on_reconnect()

    def _check_msg_and_db_state(self):
        all_connected = self._messaging.is_connected() and \
                        self._database.is_connected()
        if not all_connected:
            self._on_disconnected()
        else:
            self._on_connected()
