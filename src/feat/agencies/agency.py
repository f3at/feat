# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.

# Import standard library modules
import copy
import uuid
import weakref
import socket

# Import external project modules
from twisted.python.failure import Failure
from zope.interface import implements

# Import feat modules
from feat.agencies import common, dependency, retrying, messaging
from feat.agencies import recipient
from feat.agents.base import replay
from feat import applications

from feat.common import log, defer, fiber, serialization, journal, time
from feat.common import manhole, text_helper, container, first, error, enum

# Internal to register serialization adapters
from feat.common.serialization import adapters

# Internal imports for agency
from feat.agencies import contracts, requests, tasks, notifications

# Import interfaces
from interface import (AgencyRoles, IAgencyAgentInternal,
                       IFirstMessage, IAgencyInterestInternalFactory,
                       IAgencyProtocolInternal,
                       IAgencyInitiatorFactory, IJournaler,
                       ILongRunningProtocol, )
from feat.interface.recipient import IRecipient
from feat.interface.agency import IAgency, ExecMode
from feat.interface.agent import IAgencyAgent, IAgentFactory, AgencyAgentState
from feat.database.interface import IDocument, NotFoundError, ConflictError
from feat.database.interface import IDbConnectionFactory
from feat.interface.generic import ITimeProvider
from feat.interface.journal import IRecorderNode, IJournalKeeper, IRecorder
from feat.interface.protocols import (IInterest, ProtocolFailed,
                                      IInitiatorFactory, )
from feat.interface.serialization import ISerializable, IExternalizer


# How many entries should be between two snapshot at minimum
MIN_ENTRIES_PER_SNAPSHOT = 600
HOST_RESTART_RETRY_INTERVAL = 5


class AgencyAgent(log.LogProxy, log.Logger, manhole.Manhole,
                  dependency.AgencyAgentDependencyMixin,
                  common.StateMachineMixin):

    implements(IAgencyAgent, IAgencyAgentInternal, ITimeProvider,
               IRecorderNode, IJournalKeeper, ISerializable)

    type_name = "agent-medium" # this is used by ISerializable

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

        self.log_name = descriptor.doc_id
        self.log_category = descriptor.type_name

        self.agent = factory(self)
        self.log('Instantiated the %r instance', self.agent)

        self._protocols = {} # {puid: IAgencyProtocolInternal}
        self._interests = {} # {protocol_type: {protocol_id: IInterest}}
        self._long_running_protocols = [] # Long running protocols

        # Bindings which should not be revoked when agent changes the shard.
        # This is important when the agent creates an interest on startup
        # and bind it with .bind_to_lobby() call. Later on, when it
        # changes shard, the binding is preserved.
        # NOTE: It would be better to use WeakSet() here, but it was
        # introduced in python 2.7 and we need to stay compatibile with 2.6
        self._bindings_preserved_on_shard_change = weakref.WeakKeyDictionary()

        self._notifier = defer.Notifier()

        self._database = None
        self._messaging = None
        self._configuration = None

        self._updating = False
        self._update_queue = []
        self._delayed_calls = dict()
        # Terminating flag, used to not to run
        # termination procedure more than once
        self._terminating = False

        # this is set if initiate_agent() throws an error. Its used by
        # the StartAgent task of Host Agent to know that the agent is going
        # to be terminated
        self.startup_failure = None

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
        d.addCallback(setter, "_messaging")
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

    @manhole.expose()
    def get_instance_id(self):
        return self._instance_id

    @manhole.expose()
    def get_full_id(self):
        desc = self._descriptor
        return desc.doc_id + u"/" + unicode(desc.instance_id)

    @manhole.expose()
    def get_shard_id(self):
        return self._descriptor.shard

    def get_status(self):
        return self._get_machine_state()

    def remote_get_status(self):
        # jelly doesn't support serialization of Enums,
        # for this reason we need to send int
        return int(self.get_status())

    @manhole.expose()
    def get_agent_type(self):
        return self._descriptor.type_name

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
        self._entries_since_snapshot = 0
        self.agency.journal_agent_snapshot(
            agent_id, self._instance_id, self.snapshot_agent())

    def journal_protocol_created(self, *args, **kwargs):
        self.agency.journal_protocol_created(self._descriptor.doc_id,
                                             self._instance_id,
                                             *args, **kwargs)

    @serialization.freeze_tag('AgencyAgent.check_if_hosted')
    def check_if_hosted(self, agent_id):
        d = self.agency.find_agent(agent_id)
        d.addCallback(bool)
        return d

    def on_killed(self):
        '''called as part of SIGTERM handler.'''

        def generate_body():
            return self.agent.on_agent_killed()

        return self._terminate_procedure(generate_body)

    ### IAgencyAgent Methods ###

    @serialization.freeze_tag('AgencyAgent.get_own_address')
    @replay.named_side_effect('AgencyAgent.get_own_address')
    def get_own_address(self):
        return IRecipient(self._descriptor)

    @serialization.freeze_tag('AgencyAgent.create_external_route')
    @replay.named_side_effect('AgencyAgent.create_external_route')
    def create_external_route(self, backend_id, **kwargs):
        self._messaging.create_external_route(backend_id, **kwargs)

    @serialization.freeze_tag('AgencyAgent.remove_external_route')
    @replay.named_side_effect('AgencyAgent.remove_external_route')
    def remove_external_route(self, backend_id, **kwargs):
        self._messaging.remove_external_route(backend_id, **kwargs)

    @replay.named_side_effect('AgencyAgent.get_tunneling_url')
    @serialization.freeze_tag('AgencyAgent.get_tunneling_url')
    def get_tunneling_url(self):
        return self._messaging.get_tunneling_url()

    @replay.named_side_effect('AgencyAgent.observe')
    def observe(self, _method, *args, **kwargs):
        res = common.Observer(_method, *args, **kwargs)
        self.call_next(res.initiate)
        return res

    @replay.named_side_effect('AgencyAgent.get_hostname')
    def get_hostname(self):
        return self.agency.get_hostname()

    @replay.named_side_effect('AgencyAgent.get_ip')
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
        self.debug("Joining shard %r", shard)
        # Rebind agents queue
        self.create_binding(self._descriptor.doc_id, shard, public=False)
        # Iterate over interest and create bindings
        for interest in self._iter_interests():
            interest.bind(shard)

    @serialization.freeze_tag('AgencyAgent.upgrade_agency')
    @replay.named_side_effect('AgencyAgent.upgrade_agency')
    def upgrade_agency(self, upgrade_cmd):
        self.agency.upgrade(upgrade_cmd)

    @serialization.freeze_tag('AgencyAgent.leave_shard')
    def leave_shard(self, shard):
        self.debug("Leaving shard %r", shard)
        bindings = self._messaging.get_bindings(shard)
        for x in bindings:
            if x not in self._bindings_preserved_on_shard_change:
                self.debug("Revoking binding (%s, %s)",
                           x.recipient.key, x.recipient.route)
                self._messaging.revoke_binding(x)
            else:
                self.debug("Not revoking binding (%s, %s) because its"
                           " mark to be preserved.",
                           x.recipient.key, x.recipient.route)

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
        factory = IInitiatorFactory(factory)
        self.debug('Initiating protocol %s.%s, args: %r, kwargs: %r',
                   factory.protocol_type, factory.protocol_id, args, kwargs)
        medium_factory = IAgencyInitiatorFactory(factory)
        medium = medium_factory(self, *args, **kwargs)

        if medium is None:
            self.debug('Protocol factory declined running the protocol %s.%s.',
                       factory.protocol_type, factory.protocol_id)
            return

        done = medium.notify_finish()
        done.addErrback(Failure.trap, ProtocolFailed)

        if IAgencyProtocolInternal.providedBy(medium):
            self.register_protocol(medium)
            self.journal_protocol_created(factory, medium, args, kwargs)
            done.addBoth(defer.drop_param, self.unregister_protocol, medium)

        if ILongRunningProtocol.providedBy(medium):
            # This interface is implemented by the simpler protocols
            # (example: RetryingProtocol).
            self._long_running_protocols.append(medium)
            cb = lambda _: self._long_running_protocols.remove(medium)
            done.addBoth(cb)

        return medium.initiate()

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

    @serialization.freeze_tag('AgencyAgent.register_change_listener')
    def register_change_listener(self, filter_, callback, **kwargs):
        if isinstance(filter_, (str, unicode)):
            filter_ = (filter_, )

        return self._database.changes_listener(filter_, callback, **kwargs)

    @serialization.freeze_tag('AgencyAgent.cancel_change_listener')
    @replay.named_side_effect('AgencyAgent.cancel_change_listener')
    def cancel_change_listener(self, filter_):
        self._database.cancel_listener(filter_)

    @serialization.freeze_tag('AgencyAgency.query_view')
    def query_view(self, factory, **options):
        return self._database.query_view(factory, **options)

    @serialization.freeze_tag('AgencyAgency.get_attachment_body')
    def get_attachment_body(self, attachment):
        return self._database.get_attachment_body(attachment)

    @serialization.freeze_tag('AgencyAgent.get_database')
    @replay.named_side_effect('AgencyAgent.get_database')
    def get_database(self):
        return self._database

    @manhole.expose()
    @serialization.freeze_tag('AgencyAgency.terminate')
    def terminate(self):
        self.call_next(self._terminate)

    @manhole.expose()
    @serialization.freeze_tag('AgencyAgency.terminate_hard')
    def terminate_hard(self):
        '''Kill the agent without notifying anybody.'''

        def generate_body():
            return self.agent.on_agent_killed()

        return self._terminate_procedure(generate_body)

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
        call_id = str(uuid.uuid1())
        d = defer.Deferred()
        d.addCallback(self._call, *args, **kwargs)
        d.addBoth(defer.bridge_param, self.cancel_delayed_call,
                  call_id)
        call = time.callLater(time_left, d.callback, method)

        self._store_delayed_call(call_id, call, busy)
        return call_id

    @replay.named_side_effect('AgencyAgent.cancel_delayed_call')
    def cancel_delayed_call(self, call_id):
        try:
            _busy, call = self._delayed_calls.pop(call_id)
        except KeyError:
            self.log('Tried to cancel nonexisting call id: %r', call_id)
            return

        if call.active():
            call.cancel()

    @replay.named_side_effect("AgencyAgent.is_connected")
    def is_connected(self):
        return self.agency.is_connected()

    @replay.named_side_effect('AgencyAgent.get_base_gateway_url')
    def get_base_gateway_url(self):
        return ''

    #StateMachineMixin

    @replay.named_side_effect('AgencyAgent.get_machine_state')
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
        self._entries_since_snapshot += 1
        return self.agency.journal_new_entry(self._descriptor.doc_id,
                                             self._instance_id,
                                             journal_id, function_id,
                                             *args, **kwargs)

    ### ISerializable Methods ###

    def snapshot(self):
        return (self._descriptor.doc_id, self._instance_id, )

    ### IAgencyAgentInternal Methods ###

    def create_binding(self, key, shard=None, public=False,
                       special_lobby_binding=False):
        '''Used by Interest instances.'''
        shard = shard or self.get_shard_id()
        factory = recipient.Broadcast if public else recipient.Agent
        recp = factory(key, shard)
        binding = self._messaging.create_binding(recp)
        if special_lobby_binding:
            # this is WeakKeyDictionary
            self._bindings_preserved_on_shard_change[binding] = True
        return binding

    def revoke_binding(self, binding):
        self._messaging.revoke_binding(binding)

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
        if not self._protocols:
            self._notifier.callback('protocols_finished', None)

    def send_msg(self, recipients, msg):
        assert msg.expiration_time is not None
        self._messaging.post(recipients, msg)
        return msg

    ### Introspection Methods ###

    @manhole.expose()
    def get_agency(self):
        '''Returns the medium agency.'''
        return self.agency

    @manhole.expose()
    def get_description(self):
        return self.agent.get_description()

    @manhole.expose()
    def get_agent(self):
        '''Returns the agent side instance.'''
        return self.agent

    @manhole.expose()
    def list_partners(self):
        t = text_helper.Table(fields=["Partner", "Id", "Shard", "Role"],
                  lengths = [20, 35, 35, 10])

        partners = self.agent.query_partners('all')
        return t.render((type(p).__name__, p.recipient.key,
                         p.recipient.route, p.role)
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

    ### private ###

    def _set_channel(self, channel, channel_type):
        assert channel.channel_type == channel_type, \
               "Unexpected channel type"
        assert self._channels[channel_type] is None, \
               "Channel not pre-enabled"
        self._channels[channel_type] = channel
        self._notifier.callback(channel_type, self)
        self.debug("Channel %s enabled for agent %s",
                   channel_type, self.get_full_id())

    def _subscribe_for_descriptor_changes(self):
        return self._database.changes_listener(
            (self._descriptor.doc_id, ), self._descriptor_changed)

    def _descriptor_changed(self, doc_id, rev, deleted, own_change):
        if own_change:
            self.log("Ignoring old change notification for "
                     "document %s revision %s", doc_id, rev)
            return
        self.warning('Received the notification about other database session '
                     'changing our descriptor. This means that I got '
                     'restarted on some other machine and need to commit '
                     'suicide :(. Or you have a bug ;).')
        self.debug("Revision received: %s, deleted flag: %s, "
                   "current revision: %s", rev, deleted,
                   self._descriptor.rev)
        return self.terminate_hard()

    def _configuration_changed(self, doc_id, rev, deleted, own_change):
        self.debug('Received notification about agents configuration changing.'
                   ' Reloading.')
        setter = lambda value, name: setattr(self, name, value)

        d = self._database.get_document(doc_id)
        d.addCallback(defer.keep_param, setter, '_configuration')
        d.addCallback(defer.inject_param, 1,
                      self._call, self.agent.on_agent_configuration_change)
        return d

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
        there it would get the notification update and suicide.
        '''

        def do_set(desc):
            desc.instance_id = self._instance_id
            desc.under_restart = None

        return self.update_descriptor(do_set)

    def _load_configuration(self):

        def not_found(fail, doc_id):
            fail.trap(NotFoundError)
            self.info('Agent configuration not found in database. '
                         'Expected doc_id: %r', doc_id)
            return

        d_id = self.agent.configuration_doc_id
        d = self.get_document(d_id)
        d.addCallback(defer.bridge_param, self._database.changes_listener,
                      (d_id, ), self._configuration_changed)
        d.addErrback(not_found, d_id)
        return d

    def _next_update(self):

        def saved(desc, result, d):
            self.log("Updating descriptor: %r", desc)
            self._descriptor = desc
            d.callback(result)

        def error_handler(failure, d):
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
                                errback=error_handler, errbackArgs=(d, ))
            save_d.addBoth(next_update)
        except Exception as e:
            d.errback(e)
            next_update()

    def _terminate_procedure(self, body):
        assert callable(body)

        if self._cmp_state((AgencyAgentState.terminating,
                            AgencyAgentState.terminated)):
            return
        self._set_state(AgencyAgentState.terminating)

        self.log('Begging termination procedure, storing snapshot.')
        self.check_if_should_snapshot(force=True)

        d = defer.succeed(None)

        # Cancel all long running protocols
        d.addBoth(defer.drop_param, self._cancel_long_running_protocols)
        d.addErrback(self._handle_failure)
        # Cancel all delayed calls
        d.addBoth(defer.drop_param, self._cancel_all_delayed_calls)
        d.addErrback(self._handle_failure)
        # Kill all protocols
        d.addBoth(self._kill_all_protocols)
        d.addErrback(self._handle_failure)
        # Again, just in case
        d.addBoth(defer.drop_param, self._cancel_all_delayed_calls)
        d.addErrback(self._handle_failure)
        # Run code specific to the given shutdown
        d.addBoth(defer.drop_param, body)
        d.addErrback(self._handle_failure)
        d.addBoth(self._kill_all_protocols)
        d.addErrback(self._handle_failure)
        # Tell the agency we are no more
        d.addBoth(defer.drop_param, self._unregister_from_agency)
        d.addErrback(self._handle_failure)
        if self._messaging:
            # Close the messaging connection
            d.addBoth(defer.drop_param, self._messaging.release)
            d.addErrback(self._handle_failure)
        else:
            d.addCallback(defer.drop_param, self.warning,
                          "Agent doesn't have _messaging reference.")
        if self._database:
            # Close the database connection
            d.addBoth(defer.drop_param, self._database.disconnect)
            d.addErrback(self._handle_failure)
        else:
            d.addCallback(defer.drop_param, self.warning,
                          "Agent doesn't have _database reference.")
        d.addBoth(defer.drop_param,
                  self._set_state, AgencyAgentState.terminated)
        d.addErrback(self._handle_failure)
        return d

    def _handle_failure(self, failure):
        error.handle_failure(self, failure, "Failure during termination")

    def _unregister_from_agency(self):
        self.agency.journal_agent_deleted(self._descriptor.doc_id,
                                          self._instance_id)
        self.agency.unregister_agent(self)

    def _cancel_long_running_protocols(self):
        return defer.DeferredList([defer.maybeDeferred(x.cancel)
                                   for x in self._long_running_protocols])

    def _terminate(self):
        '''Shutdown agent gently removing the descriptor and
        notifying partners.'''

        def generate_body():
            d = defer.succeed(None)
            d.addBoth(defer.drop_param, self.agent.shutdown_agent)
            # Delete the descriptor
            d.addBoth(lambda _: self.delete_document(self._descriptor))
            return d

        return self._terminate_procedure(generate_body)

    def _iter_interests(self):
        return (interest
                for interests in self._interests.itervalues()
                for interest in interests.itervalues())

    def _kill_all_protocols(self, *_):

        # Revoke all interests
        for i in list(self._iter_interests()):
            self.revoke_interest(i.agent_factory)

        if not self._protocols:
            return defer.succeed(None)

        d = self._notifier.wait('protocols_finished')

        for x in self._protocols.values():
            x.cleanup()
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
        error.handle_failure(self, fail,
                             "Agent raised an error while starting up. "
                             "He will be punished by terminating. "
                             "Medium state while that happened: %r",
                             self._get_machine_state())

        # this allows StartAgent task of Host Agent know what is going on
        self.startup_failure = fail
        # terminate() doesn't return the Deferred, so its a fire-and-forget
        # the terminatation is done in a broken execution chain
        self.terminate()

    def _store_delayed_call(self, call_id, call, busy):
        if call.active():
            self._delayed_calls[call_id] = busy, call

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
        d.addErrback(defer.inject_param, 1, error.handle_failure, self,
                     'Failure calling method %r, with args: %r, kwargs: %r',
                     method, args, kwargs)
        return d


class ShutdownStage(enum.Enum):

    initiated, slaves, agents, internals, process = range(5)


class Shutdown(common.Procedure):

    stages = ShutdownStage

    def stage_initiated(self):
        self.debug("Starting agency shutdown. Options: %r", self.opts)

    def stage_agents(self):
        if self.opts.get('gentle', True):
            d = defer.DeferredList([x._terminate()
                                    for x in self.friend._agents])
        else:
            d = defer.DeferredList([x.on_killed()
                                    for x in self.friend._agents])
        return d

    def stage_internals(self):
        return self.friend._disconnect_backends()


class StartupStage(enum.Enum):

    (initiated, configure, messaging, database, journaler,
     private, finish) = range(7)


class Startup(common.Procedure):

    stages = StartupStage

    def stage_initiated(self):
        self.debug("Starting agency. Options: %r", self.opts)

    def stage_configure(self):
        self._db = self.opts.get('database', None)
        self._backends = self.opts.get('backends', [])
        self._messaging = self.opts.get('messaging',
                                        messaging.Messaging(self.friend))
        self._journaler = self.opts.get('journaler', None)

    def stage_journaler(self):
        if self._journaler is None:
            return

        self.friend._journaler = IJournaler(self._journaler)
        self.friend._jourconn = self._journaler.get_connection(self.friend)

    def stage_messaging(self):
        self.friend._messaging = self._messaging

        self._messaging.add_disconnected_cb(self.friend._on_disconnected)
        self._messaging.add_reconnected_cb(self.friend._check_msg_and_db_state)
        d = defer.succeed(None)
        for backend in self._backends:
            d.addCallback(defer.drop_param,
                          self._messaging.add_backend, backend)
        return d

    def stage_database(self):
        if self._db is None:
            return

        d = self.friend._database = IDbConnectionFactory(self._db)
        d.add_disconnected_cb(self.friend._on_disconnected)
        d.add_reconnected_cb(self.friend._check_msg_and_db_state)

    def stage_private(self):
        self.friend._check_msg_and_db_state()

    def stage_finish(self):
        pass


class Agency(log.LogProxy, log.Logger, manhole.Manhole,
             dependency.AgencyDependencyMixin, common.ConnectionManager):

    log_category = 'agency'
    type_name = "agency" # this is used by ISerializable

    implements(IAgency, IExternalizer, ITimeProvider, ISerializable)

    agency_agent_factory = AgencyAgent

    shutdown_factory = Shutdown
    startup_factory = Startup

    start_host_agent = False

    def __init__(self):
        log.LogProxy.__init__(self, log.get_default() or log.FluLogKeeper())
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

        try:
            hostname = socket.gethostname()
            self.debug("socket hostname: %s", hostname)
            self._hostname = unicode(
                socket.gethostbyaddr(hostname)[0])
            self._ip = unicode(socket.gethostbyname(self._hostname))
        except socket.gaierror:
            # this fixes the issues when office is out of internet ;)
            self._hostname = unicode(socket.gethostname())
            self._ip = u'127.0.0.1'

        self._shutdown_task = None
        self._startup_task = None

        self._agency_id = str(uuid.uuid1())
        self.log_name = self._agency_id

        # hostdef to pass to the Host Agent we run
        self._hostdef = None

        # flag saying that we are in the process of starting the Host Agent,
        # it's used not to do this more than once
        self._starting_host = False

        self.add_reconnected_cb(self._notify_agents_about_reconnection)
        self.add_disconnected_cb(self._notify_agents_about_disconnection)

        #actions to be performed on host agent, list of tuples
        #(method_name, args, kwargs)
        self._pending_host_agent_calls = list()

        # static agents, list of tuples (initial_descriptor, kwargs, name)
        self.static_agents = list()

    ### Public Methods ###

    def initiate(self, database=None, journaler=None, *backends):
        '''
        Asynchronous part of agency initialization. Needs to be called before
        agency is used for anything.
        '''
        return self._initiate(database=database, journaler=journaler,
                              backends=backends)

    @property
    def agency_id(self):
        return self._agency_id

    @property
    def role(self):
        return AgencyRoles.unknown

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

    def set_host_def(self, hostdef):
        '''
        Sets the hostdef param which will get passed to the Host Agent which
        the agency starts if it becomes the master.
        '''
        if self._hostdef is not None:
            self.info("Overwriting previous hostdef, which was %r",
                      self._hostdef)
        self._hostdef = hostdef

    def start_agent_locally(self, descriptor, **kwargs):
        factory = IAgentFactory(
            applications.lookup_agent(descriptor.type_name))
        self.log('I will start: %r agent. Kwargs: %r', factory, kwargs)
        medium = self.agency_agent_factory(self, factory, descriptor)
        self.register_agent(medium)

        d = self._database.wait_connected()
        d.addCallback(defer.drop_param, medium.initiate, **kwargs)
        d.addCallback(defer.override_result, medium)
        if descriptor.type_name == 'host_agent':
            d.addCallback(defer.bridge_result, medium.call_next,
                          self._on_host_started)
        return d

    @manhole.expose()
    @serialization.freeze_tag('IAgency.start_agent')
    def start_agent(self, descriptor, **kwargs):
        return self.start_agent_locally(descriptor, **kwargs)

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
    def set_logging_filter(self, filter_):
        log.FluLogKeeper.set_debug(filter_)

    @manhole.expose()
    def shutdown(self):
        '''Called when the agency is ordered to shutdown all the agents..'''
        return self._shutdown(gentle=True)

    @manhole.expose()
    def kill(self):
        '''
        Called when the agency terminated as the result of violent shutdown.
        '''
        return self._shutdown(gentle=False)

    def upgrade(self, upgrade_cmd):
        '''Called as the result of upgrade process triggered by host agent.'''
        return self._shutdown(gentle=True)

    def on_killed(self):
        '''Called when the agency process is terminating. (SIGTERM)'''
        return self._shutdown(gentle=False)

    def register_agent(self, medium):
        self._agents.append(medium)

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
                try:
                    self.log("Removing recorder id %r, instance: %r",
                             key, self.registry[key])
                    del(self.registry[key])
                except KeyError:
                    self.debug("Removing recorder id %r failed. It seems it "
                               "dissapeared from WeakRefDict between "
                               "obtaining the list of keys and iterating "
                               "over it.", key)

    def is_idle(self):
        return (all([x.is_idle() for x in self._agents]) and
                self._messaging.is_idle() and
                not self._starting_host)

    def add_static_agent(self, desc, kwargs, name):
        self.debug("Configuring agency to start agent %s with descriptor %r "
                   "Passing %r to his initiate()",
                   desc.type_name, desc, kwargs)
        self.static_agents.append((desc, kwargs, name))

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
        self.log("Storing agents snapshot. Agent_id: %r, Instance_id: %r.",
                 agent_id, instance_id)
        self._jourconn.snapshot(agent_id, instance_id, snapshot)

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
        '''Gives medium class of the agent if the agency hosts it.'''
        agent_id = (desc.doc_id
                    if IDocument.providedBy(desc)
                    else desc)
        self.log("I'm trying to find the agent with id: %s", agent_id)
        result = first(x for x in self._agents
                       if x._descriptor.doc_id == agent_id)
        return defer.succeed(result)

    @manhole.expose()
    def snapshot_agents(self, force=False):
        '''snapshot agents if number of entries from last snapshot if greater
        than 1000. Use force=True to override.'''
        for agent in self._agents:
            agent.check_if_should_snapshot(force)

    @manhole.expose()
    def list_agents(self):
        '''List agents hosted by the agency.'''
        t = text_helper.Table(fields=("Agent ID", "Agent class", "State"),
                              lengths=(40, 25, 15))

        return t.render((a._descriptor.doc_id, a.log_category,
                         a._get_machine_state().name)
                        for a in self._agents)

    @manhole.expose()
    def get_nth_agent(self, n):
        '''Get the agent by his index in the list.'''
        return self._agents[n]

    @manhole.expose()
    def get_agents(self):
        '''Get the list of agents hosted by this agency.'''
        return self._agents

    @manhole.expose()
    def get_host_agent(self):
        medium = self._get_host_medium()
        return medium and medium.get_agent()

    ### public methods doing things on Host Agent ###

    def host_agent_call(self, _method, *args, **kwargs):
        '''Public method exposed to all the agency submodules, which need
        to call the method on the host agent.
        This works regardless if host agent already running or not. If
        it is still being started the method will be called when he is ready.
        '''
        d = defer.Deferred()
        self._pending_host_agent_calls.append((_method, args, kwargs, d))
        self._flush_pending_host_agent_calls()
        return d

    def raise_alert(self, service, status_info=None):
        return self.host_agent_call('raise_alert', service, status_info)

    def resolve_alert(self, service, status_info=None):
        return self.host_agent_call('resolve_alert', service, status_info)

    @manhole.expose()
    def spawn_agent(self, desc, **kwargs):
        return self.host_agent_call('spawn_agent', desc, **kwargs)

    ### protected ###

    def _initiate(self, **opts):
        self._startup_task = type(self).startup_factory(self, **opts)
        d = self._startup_task.initiate()
        d.addBoth(defer.bridge_param, setattr, self, '_startup_task', None)
        return d

    def _shutdown(self, **opts):
        if self._shutdown_task is not None:
            return self._shutdown_task.reentrant_call(**opts)
        else:
            self._shutdown_task = type(self).shutdown_factory(self, **opts)
            return self._shutdown_task.initiate()

    def _can_start_host_agent(self):
        if self._startup_task:
            self.debug('Not starting host agent, because the agency '
                       'is still starting up')
            return False

        if self._shutdown_task is not None:
            self.debug('Not starting host agent, because the agency '
                       'is about to terminate.')
            return False

        if self.get_host_agent():
            self.debug('Not starting host agent, because we already '
                       ' have one')
            return False

        if self._starting_host:
            self.debug('Not starting host agent, because we are already '
                       'starting one.')
            return False
        return True

    def _on_host_started(self):
        self.info("Host agent started.")
        medium = self._get_host_medium()
        d = medium.wait_for_state(AgencyAgentState.ready)
        d.addCallback(defer.drop_param, self._flush_pending_host_agent_calls)
        for desc, kwargs, name in self.static_agents:
            d.addCallback(defer.drop_param, self.host_agent_call,
                          'add_static_agent', desc, kwargs, name)
        return d

    def _flush_pending_host_agent_calls(self):
        medium = self._get_host_medium()
        illegal_states = [
            AgencyAgentState.not_initiated,
            AgencyAgentState.initiating,
            AgencyAgentState.terminating,
            AgencyAgentState.terminated]
        if not medium:
            self.debug("Host agent is not there yet, we will perform "
                       "his calls later.")
            return
        if medium._cmp_state(illegal_states):
            self.debug("Host agent is in state %r, we will perform "
                       "his calls later.", medium.state)
            return

        agent = medium.get_agent()
        while True:
            try:
                method_name, args, kwargs, d = \
                             self._pending_host_agent_calls.pop(0)
            except IndexError:
                break
            else:
                method = getattr(agent, method_name)
                if not callable(method):
                    self.error("Unknown method name %r on host agent. "
                               "Ignoring.", method_name)
                    continue
                d2 = defer.Deferred()
                d2.addCallback(defer.drop_param, method, *args, **kwargs)
                d2.chainDeferred(d)
                medium.call_next(d2.callback, None)

    def _get_host_agent_id(self):
        return self.get_hostname()

    def _start_host_agent(self):
        '''
        This method starts saves the host agent descriptor and runs it.
        To make this happen following conditions needs to be fulfilled:
         - it is a master agency,
         - we are not starting a host agent already,
         - we are not terminating,
         - and last but not least, we dont have a host agent running.
        '''

        def set_flag(value):
            self._starting_host = value

        if not self._can_start_host_agent():
            return

        def handle_error_on_get(fail, connection, doc_id):
            fail.trap(NotFoundError)
            factory = serialization.lookup('host_agent')
            desc = factory(shard=u'lobby', doc_id=doc_id,
                           agency_id=self.agency_id)
            self.info("Host Agent descriptor not found in database, "
                      "creating a brand new instance.")
            return connection.save_document(desc)

        def handle_success_on_get(desc):
            msg = ("Descriptor of host agent has been found in "
                   "database (hostname: %s). I will wait patiently "
                   "until in disappears. It should happened any minute now "
                   "providing there is still a monitor agent in the "
                   "cluster who will take care of it. In other case "
                   "you would have to cleanup the database. In development "
                   "the --force-host-restart feat script option is your "
                   "only friend. " % desc.doc_id)
            raise error.FeatError(msg)

        set_flag(True)
        self.info('Starting host agent.')
        conn = self._database.get_connection()

        doc_id = self._get_host_agent_id()
        d = defer.Deferred()
        d.addCallback(defer.drop_param, self._database.wait_connected)
        d.addCallback(defer.drop_param, conn.get_document, doc_id)
        d.addCallbacks(handle_success_on_get, handle_error_on_get,
                       errbackArgs=(conn, doc_id, ))
        d.addCallback(self.start_agent, hostdef=self._hostdef)
        d.addBoth(defer.bridge_param, set_flag, False)
        d.addErrback(self._host_restart_failed)
        time.callLater(0, d.callback, None)

    ### private ###

    def _get_host_medium(self):
        return first((x for x in self._agents
                      if x.get_descriptor().type_name == 'host_agent'))

    def _host_restart_failed(self, failure):
        error.handle_failure(self, failure, "Failure during host restart")
        self.debug("Retrying in %d seconds", HOST_RESTART_RETRY_INTERVAL)
        time.callLater(HOST_RESTART_RETRY_INTERVAL, self._start_host_agent)

    def _notify_agents_about_disconnection(self):
        for medium in self.iter_agents():
            medium.on_disconnect()

    def _notify_agents_about_reconnection(self):
        for medium in self.iter_agents():
            medium.on_reconnect()

    def _check_msg_and_db_state(self):
        messaging = self._messaging
        database = self._database

        all_connected = messaging.is_connected() and database.is_connected()

        if not all_connected:
            self._on_disconnected()
        else:
            self._on_connected()

    def _disconnect_backends(self):
        return self._messaging.disconnect_backends()

    ### ISerializable ###

    def snapshot(self):
        return None

    @serialization.freeze_tag('IAgency.get_config')
    @replay.named_side_effect('IAgency.get_config')
    def get_config(self):
        from feat.agencies.net import config
        return config.Config()
