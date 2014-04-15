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

import os
import sys
import types

from zope.interface import implements

from feat.common import log, decorator, fiber, manhole, mro
from feat.interface import generic, agent, protocols
from feat import applications
from feat.agencies import retrying, recipient
from feat.agents.base import (replay, requester, alert,
                              replier, partners, dependency, manager, )
from feat.agents.common import monitor, rpc
from feat.agents.application import feat
from feat.configure import configure

from feat.interface.agent import AgencyAgentState


@decorator.simple_function
def update_descriptor(function):

    @replay.immutable
    def decorated(self, state, *args, **kwargs):
        immfun = replay.immutable(function)
        method = types.MethodType(immfun, self, self.__class__)
        f = fiber.succeed(method, debug_depth=2, debug_call=function)
        f.add_callback(state.medium.update_descriptor, *args, **kwargs)
        return f

    return decorated


@feat.register_restorator
class BasePartner(partners.BasePartner):
    pass


@feat.register_restorator
class MonitorPartner(monitor.PartnerMixin, BasePartner):

    type_name = "agent->monitor"


@feat.register_restorator
class HostPartner(BasePartner):

    type_name = "agent->host"

    def on_buried(self, agent):
        if self.role == u"host":
            agent.info("Received host agent %s buried, committing suicide.",
                       self.recipient.key)
            agent.terminate_hard()

    def on_restarted(self, agent):
        '''
        This called also after host agent has switched shard.
        The agents which have been initialized before it happened should be
        restarted accordingly.
        '''
        if agent.get_shard_id == 'lobby':
            return agent.switch_shard(self.recipient.shard)


class Partners(partners.Partners):

    partners.has_many("monitors", "monitor_agent", MonitorPartner)
    partners.has_many("hosts", "host_agent", HostPartner)


class MetaAgent(type(replay.Replayable), type(manhole.Manhole)):
    implements(agent.IAgentFactory)

    ### used by partnership protocol ###

    @property
    def identity_for_partners(cls):
        return getattr(cls.partners_class, 'identity_for_partners',
                       cls.descriptor_type)


class BaseAgent(mro.FiberMroMixin, log.Logger, log.LogProxy, replay.Replayable,
                manhole.Manhole, rpc.AgentMixin,
                dependency.AgentDependencyMixin, monitor.AgentMixin,
                alert.AgentMixin):

    __metaclass__ = MetaAgent

    ignored_state_keys = ['medium']

    implements(agent.IAgent, generic.ITimeProvider)

    partners_class = Partners

    application = feat

    standalone = False

    categories = {'access': agent.Access.none,
                  'address': agent.Address.none,
                  'storage': agent.Storage.none}

    # resources required to run the agent
    resources = {'epu': 1}

    def __init__(self, medium):
        manhole.Manhole.__init__(self)
        log.Logger.__init__(self, medium)
        log.LogProxy.__init__(self, medium)
        replay.Replayable.__init__(self, medium)

    @replay.immutable
    def restored(self, state):
        log.Logger.__init__(self, state.medium)
        log.LogProxy.__init__(self, state.medium)
        replay.Replayable.restored(self)

    def init_state(self, state, medium):
        state.medium = agent.IAgencyAgent(medium)
        state.partners = self.partners_class(self)

    ### Used by gateway model ###

    @replay.immutable
    def get_agent_status(self, state):
        return state.medium.state

    ### IAgent Methods ###

    @replay.journaled
    def initiate_agent(self, state, **keywords):
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, self.call_mro, 'initiate', **keywords)
        f.add_callback(fiber.drop_param, self._initiate_partners)
        return f

    @replay.journaled
    def startup_agent(self, state):
        return self.call_mro('startup')

    @replay.journaled
    def shutdown_agent(self, state):
        return self.call_mro('shutdown')

    @replay.journaled
    def on_agent_killed(self, state):
        return self.call_mro('on_killed')

    @replay.journaled
    def on_agent_disconnect(self, state):
        return self.call_mro('on_disconnect')

    @replay.journaled
    def on_agent_reconnect(self, state):
        return self.call_mro('on_reconnect')

    @replay.journaled
    def on_agent_configuration_change(self, state, config):
        return self.call_mro_ex('on_configuration_change',
                                dict(config=config),
                                raise_on_unconsumed=False)

    ### Methods called as a result of agency calls ###

    @replay.immutable
    def initiate(self, state):
        state.medium.register_interest(replier.Ping)

    @replay.journaled
    def shutdown(self, state):
        desc = self.get_descriptor()
        self.info('Agent shutdown, partners: %r', desc.partners)
        fibers = [x.call_mro('on_shutdown', agent=self)
                   for x in desc.partners]
        f = fiber.FiberList(fibers)
        return f.succeed()

    def startup(self):
        pass

    def on_killed(self):
        pass

    def on_disconnect(self):
        pass

    def on_reconnect(self):
        pass

    ### Public methods ###

    @replay.immutable
    def get_descriptor(self, state):
        '''Returns a copy of the agent descriptos.'''
        return state.medium.get_descriptor()

    @replay.immutable
    def get_configuration(self, state):
        '''Returns a copy of the agent config.'''
        return state.medium.get_configuration()

    @replay.immutable
    def get_agent_id(self, state):
        '''Returns a global unique identifier for the agent.
        Do not change when the agent is restarted.'''
        desc = state.medium.get_descriptor()
        return desc.doc_id

    @replay.immutable
    def get_hostname(self, state):
        '''Returns a hostname the agent is running on'''
        return state.medium.get_hostname()

    @replay.immutable
    def get_instance_id(self, state):
        """Returns the agent instance identifier.
        Changes when the agent is restarted.
        It's unique only for the agent."""
        desc = state.medium.get_descriptor()
        return desc.instance_id

    @replay.immutable
    def get_full_id(self, state):
        """Return a global unique identifier for this agent instance.
        It's a combination of agent_id and instance_id:
          full_id = agent_id + '/' + instance_id
        """
        desc = state.medium.get_descriptor()
        return desc.doc_id + u"/" + unicode(desc.instance_id)

    @replay.immutable
    def get_shard_id(self, state):
        '''Returns current shard identifier.'''
        return state.medium.get_descriptor().shard

    @replay.immutable
    def get_agent_type(self, state):
        return state.medium.get_descriptor().type_name

    def get_cmd_line(self, *args, **kwargs):
        raise NotImplemented('To be used for standalone agents!')

    @rpc.publish
    @replay.journaled
    def switch_shard(self, state, shard):
        self.debug('Switching shard to %r.', shard)
        desc = state.medium.get_descriptor()
        if desc.shard == shard:
            self.debug("switch_shard(%s) called, but we are already member "
                       "of this shard, ignoring.", shard)
            return fiber.succeed()

        def save_change(desc, shard):
            desc.shard = shard

        f = fiber.Fiber()
        f.add_callback(fiber.drop_param, state.medium.leave_shard, desc.shard)
        f.add_callback(fiber.drop_param, self.update_descriptor,
                       save_change, shard)
        f.add_callback(fiber.drop_param, state.medium.join_shard, shard)
        f.add_callback(fiber.drop_param, self._fix_alert_poster, shard)
        f.add_callback(fiber.drop_param,
                       self._notify_partners_about_shard_switch)
        return f.succeed()

    @replay.immutable
    def _notify_partners_about_shard_switch(self, state):
        fibers = list()
        own = self.get_own_address()
        for partner in state.partners.all:
            fibers.append(requester.notify_restarted(
                self, partner.recipient, own, own))
        if fibers:
            return fiber.FiberList(fibers, consumeErrors=True).succeed()

    ### ITimeProvider Methods ###

    @replay.immutable
    def get_time(self, state):
        return generic.ITimeProvider(state.medium).get_time()

    ### Public Methods ###

    @rpc.publish
    @replay.journaled
    def terminate_hard(self, state):
        self.call_next(state.medium.terminate_hard)

    @rpc.publish
    @replay.journaled
    def terminate(self, state):
        self.call_next(state.medium.terminate)

    @manhole.expose()
    @replay.journaled
    def wait_for_ready(self, state):
        return fiber.wrap_defer(state.medium.wait_for_state,
                                AgencyAgentState.ready)

    @manhole.expose()
    def propose_to(self, recp, partner_role=None, our_role=None):
        return self.establish_partnership(recipient.IRecipient(recp),
                                          partner_role=partner_role,
                                          our_role=our_role)

    @replay.journaled
    def establish_partnership(self, state, recp, allocation_id=None,
                              partner_allocation_id=None,
                              partner_role=None, our_role=None,
                              substitute=None, allow_double=False,
                              max_retries=0, **options):
        f = fiber.succeed()
        found = state.partners.find(recp)
        default_role = getattr(self.partners_class, 'default_role', None)
        our_role = our_role or default_role
        if not allow_double and found:
            msg = ('establish_partnership() called for %r which is already '
                   'our partner with the class %r.' % (recp, type(found), ))
            self.debug(msg)

            if substitute:
                f.add_callback(fiber.drop_param, state.partners.remove,
                               substitute)

            f.chain(fiber.fail(partners.DoublePartnership(msg)))
            return f
        factory = retrying.RetryingProtocolFactory(requester.Propose,
                                                   max_retries=max_retries)
        f.add_callback(fiber.drop_param, self.initiate_protocol,
                       factory, recp, allocation_id,
                       partner_allocation_id,
                       our_role, partner_role, substitute, options)
        f.add_callback(fiber.call_param, "notify_finish")
        return f

    @replay.journaled
    def substitute_partner(self, state, partners_recp, recp, alloc_id):
        '''
        Establish the partnership to recp and, when it is successfull
        remove partner with recipient partners_recp.

        Use with caution: The partner which we are removing is not notified
        in any way, so he still keeps link in his description. The correct
        usage of this method requires calling it from two agents which are
        divorcing.
        '''
        partner = state.partners.find(recipient.IRecipient(partners_recp))
        if not partner:
            msg = 'subsitute_partner() did not find the partner %r' %\
                  partners_recp
            self.error(msg)
            return fiber.fail(partners.FindPartnerError(msg))
        return self.establish_partnership(recp, partner.allocation_id,
                                          alloc_id, substitute=partner)

    @manhole.expose()
    @replay.journaled
    def breakup(self, state, recp):
        '''Order the agent to break the partnership with the given
        recipient'''
        recp = recipient.IRecipient(recp)
        partner = self.find_partner(recp)
        if partner:
            return state.partners.breakup(partner)
        else:
            self.warning('We were trying to break up with agent recp %r.,'
                         'but apparently he is not our partner!.', recp)

    @replay.immutable
    def create_partner(self, state, partner_class, recp, allocation_id=None,
                       role=None, substitute=None, options=None):
        return state.partners.create(partner_class, recp, allocation_id, role,
                                     substitute, options)

    @replay.immutable
    def remove_partner(self, state, partner):
        return state.partners.remove(partner)

    @replay.mutable
    def partner_sent_notification(self, state, recp, notification_type,
                                  payload, sender):
        return state.partners.receive_notification(
            recp, notification_type, payload, sender)

    @manhole.expose()
    @replay.immutable
    def query_partners(self, state, name_or_class):
        '''Query the partners by the relation name or partner class.'''
        return state.partners.query(name_or_class)

    @manhole.expose()
    @replay.immutable
    def query_partners_with_role(self, state, name, role):
        return state.partners.query_with_role(name, role)

    @replay.immutable
    def find_partner(self, state, recp_or_agent_id):
        return state.partners.find(recp_or_agent_id)

    @replay.immutable
    def query_partner_handler(self, state, partner_type, role=None):
        return state.partners.query_handler(partner_type, role)

    @manhole.expose()
    @replay.immutable
    def get_medium(self, state):
        return state.medium

    @manhole.expose()
    @replay.immutable
    def get_own_address(self, state):
        '''Return IRecipient representing the agent.'''
        return state.medium.get_own_address()

    @replay.immutable
    def initiate_protocol(self, state, *args, **kwargs):
        return state.medium.initiate_protocol(*args, **kwargs)

    @replay.immutable
    def register_interest(self, state, *args, **kwargs):
        return state.medium.register_interest(*args, **kwargs)

    @replay.immutable
    def revoke_interest(self, state, *args, **kwargs):
        return state.medium.revoke_interest(*args, **kwargs)

    @replay.immutable
    def get_document(self, state, doc_id):
        return fiber.wrap_defer(state.medium.get_document, doc_id)

    @replay.immutable
    def delete_document(self, state, doc):
        return fiber.wrap_defer(state.medium.delete_document, doc)

    @replay.immutable
    def register_change_listener(self, state, filter_, callback, **kwargs):
        return fiber.wrap_defer(state.medium.register_change_listener,
            filter_, callback, **kwargs)

    @replay.immutable
    def cancel_change_listener(self, state, filter_):
        state.medium.cancel_change_listener(filter_)

    @replay.immutable
    def query_view(self, state, factory, **options):
        return fiber.wrap_defer(state.medium.query_view, factory, **options)

    @replay.immutable
    def get_attachment_body(self, state, attachment):
        return fiber.wrap_defer(state.medium.get_attachment_body, attachment)

    @replay.immutable
    def save_document(self, state, doc):
        return fiber.wrap_defer(state.medium.save_document, doc)

    @replay.immutable
    def update_document(self, state, doc_or_id, *args, **kwargs):
        db = state.medium.get_database()
        return fiber.wrap_defer(db.update_document, doc_or_id, *args, **kwargs)

    @update_descriptor
    def update_descriptor(self, state, desc, method, *args, **kwargs):
        return method(desc, *args, **kwargs)

    @replay.journaled
    def discover_service(self, state, string_or_factory,
                         timeout=3, shard='lobby'):
        initiator = manager.DiscoverService(string_or_factory, timeout)
        recp = recipient.Broadcast(route=shard,
                                   protocol_id=initiator.protocol_id)

        f = fiber.succeed(initiator)
        f.add_callback(self.initiate_protocol, recp)
        # this contract will always finish in expired state as it is blindly
        # rejecting all it gets
        f.add_callback(manager.ServiceDiscoveryManager.notify_finish)
        f.add_errback(self._expire_handler)
        return f

    @replay.immutable
    def get_database(self, state):
        return state.medium.get_database()

    @replay.immutable
    def call_next(self, state, method, *args, **kwargs):
        return state.medium.call_next(method, *args, **kwargs)

    @replay.immutable
    def call_later(self, state, time_left, method, *args, **kwargs):
        return state.medium.call_later(time_left, method, *args, **kwargs)

    @replay.immutable
    def cancel_delayed_call(self, state, call_id):
        state.medium.cancel_delayed_call(call_id)

    @replay.immutable
    def observe(self, state, _method, *args, **kwargs):
        return state.medium.observe(_method, *args, **kwargs)

    @replay.immutable
    def get_tunneling_url(self, state):
        return state.medium.get_tunneling_url()

    @replay.journaled
    def add_tunneling_route(self, state, recp, url):
        state.medium.create_external_route('tunnel', recipient=recp, uri=url)

    @replay.journaled
    def remove_tunneling_route(self, state, recp, url):
        state.medium.remove_external_route('tunnel', recipient=recp, uri=url)

    ### used by model api ###

    def get_description(self):
        '''
        Override this to give an description specific for the instance of the
        agent. This will be shown in the the /agents section of the gateway.
        '''

    ### Private Methods ###

    def _expire_handler(self, fail):
        if fail.check(protocols.ProtocolFailed):
            return fail.value.args[0]
        else:
            fail.raiseException()

    @replay.journaled
    def _initiate_partners(self, state):
        desc = self.get_descriptor()
        results = [state.partners.initiate_partner(x) for x in desc.partners]
        fibers = [x for x in results if isinstance(x, fiber.Fiber)]
        f = fiber.FiberList(fibers)
        f.add_callback(fiber.drop_param,
                       state.medium.register_interest,
                       replier.PartnershipProtocol)
        f.add_callback(fiber.drop_param,
                       state.medium.register_interest,
                       replier.ProposalReceiver)
        return f.succeed()


class StandalonePartners(Partners):

    default_role = u'standalone'


class Standalone(BaseAgent):

    partners_class = StandalonePartners

    standalone = True

    @staticmethod
    def get_cmd_line(desc):
        python_path = ":".join(sys.path)
        path = os.environ.get("PATH", "")

        command = os.path.join(configure.bindir, 'feat')
        args = ['-X', '--agent-id', str(desc.doc_id)]
        agent = applications.lookup_agent(desc.type_name)
        if agent and agent.application.name != 'feat':
            app = agent.application
            args += ['--application', '.'.join([app.module, app.name])]

        env = dict(PYTHONPATH=python_path,
                   FEAT_DEBUG=log.FluLogKeeper.get_debug(), PATH=path)
        return command, args, env
