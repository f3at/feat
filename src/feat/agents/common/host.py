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
from feat.agents.base import requester, replay, manager, descriptor
from feat.agencies import message
from feat.database import  document
from feat.common import fiber
from feat.interface.agent import Access, Address, Storage
from feat.interface.recipient import IRecipient
from feat.agents.application import feat


__all__ = ['start_agent', 'start_agent_in_shard', 'check_categories',
           'HostDef', 'NoHostFound', 'Descriptor']


class SpecialHostPartnerMixin(object):
    '''
    This mixin should be used by agents which establish partnership with
    host agent, which does not necesarily reflect the fact that the host
    is running this agent.
    The point here is to remove the "host" role from the host partner in
    case we have been restarted on some other host.
    Other agents just remove the partnership, which is triggered by the
    host agent himself.
    '''

    @replay.mutable
    def initiate(self, state):
        partners = state.partners.hosts
        fibers = list()
        for partner in partners:
            f = fiber.wrap_defer(state.medium.check_if_hosted,
                                 partner.recipient.key)
            f.add_callback(self.fixup_host_role, partner)
            fibers.append(f)
        f = fiber.FiberList(fibers, consumeErrors=True)
        return f.succeed()

    @replay.mutable
    def fixup_host_role(self, state, hosted, partner):
        has_role = (partner.role == 'host')
        f = fiber.succeed()
        if hosted and not has_role:
            f.add_callback(fiber.drop_param, self.add_host_role,
                           partner)
        elif not hosted and has_role:
            f.add_callback(fiber.drop_param, self.remove_host_role,
                           partner)
        return f

    @replay.mutable
    def remove_host_role(self, state, partner):
        self.log("Removing 'host' role from the host partner %r, "
                 "aparently he is not hosting us any more", partner.recipient)
        partner.role = None
        return state.partners.update_partner(partner)

    @replay.mutable
    def add_host_role(self, state, partner):
        self.log("Adding 'host' role to the partner %r, who hosts us after"
                 " the restart", partner.recipient)
        partner.role = u'host'
        return state.partners.update_partner(partner)


class NoHostFound(Exception):
    pass


DEFAULT_RESOURCES = {"host": 1,
                     "bandwidth": 100,
                     "epu": 500,
                     "core": 2,
                     "mem": 1000}


DEFAULT_CATEGORIES = {'access': Access.none,
                      'address': Address.none,
                      'storage': Storage.none}

DEFAULT_PORTS_RANGES = {'misc': (8000, 9000)}


@feat.register_restorator
class HostDef(document.Document):

    type_name = "hostdef"

    # The resources available for this host type.
    document.field('resources', DEFAULT_RESOURCES)
    document.field('categories', DEFAULT_CATEGORIES)
    # List of ports ranges used for allocating new ports
    # name -> (first, last)
    document.field('ports_ranges', DEFAULT_PORTS_RANGES)


def start_agent(agent, recp, desc, allocation_id=None, *args, **kwargs):
    '''
    Tells remote host agent to start agent identified by desc.
    The result value of the fiber is IRecipient.
    '''
    f = fiber.Fiber()
    f.add_callback(agent.initiate_protocol, IRecipient(recp), desc,
                   allocation_id, *args, **kwargs)
    f.add_callback(StartAgentRequester.notify_finish)
    f.succeed(StartAgentRequester)
    return f


def start_agent_in_shard(agent, desc, shard, **kwargs):
    if shard is None or shard == 'lobby':
        return fiber.fail(ValueError(
            'We cannot start agent in shard without passing a meaningful '
            'value for the shard. (%r)' % shard))

    f = agent.discover_service(StartAgentManager, shard=shard, timeout=1)
    f.add_callback(_check_recp_not_empty, shard)
    f.add_callback(lambda recp:
                   agent.initiate_protocol(StartAgentManager, recp, desc,
                                           kwargs))
    f.add_callback(StartAgentManager.notify_finish)
    return f


def check_categories(host, categories):
    for name, val in categories.iteritems():
        if ((isinstance(val, Access) and val == Access.none) or
            (isinstance(val, Address) and val == Address.none) or
            (isinstance(val, Storage) and val == Storage.none)):
            continue

        host_categories = host._get_state().categories
        if not (name in host_categories.keys() and
                host_categories[name] == val):
                return False
    return True


def premodify_allocation(agent, host_agent_recipient, allocation_id, **delta):
    return agent.call_remote(host_agent_recipient, "premodify_allocation",
                             allocation_id, **delta)


def apply_modification(agent, host_agent_recipient, change_id):
    return agent.call_remote(host_agent_recipient, "apply_modification",
                             change_id)


def release_modification(agent, host_agent_recipient, change_id):
    return agent.call_remote(host_agent_recipient, "release_modification",
                             change_id)


def release_resource(agent, host_agent_recipient, alloc_id):
    return agent.call_remote(host_agent_recipient, "release_resource",
                             alloc_id)



### Private module stuff ###


def _check_recp_not_empty(recp, shard):
    if len(recp) == 0:
        return fiber.fail(
            NoHostFound('No hosts found in the shard %s' % (shard, )))
    return recp


class StartAgentManager(manager.BaseManager):

    protocol_id = 'start-agent'
    grant_timeout = 20

    @replay.entry_point
    def initiate(self, state, desc, kwargs):
        state.kwargs = kwargs
        payload = dict(descriptor=desc)
        msg = message.Announcement(payload=payload)
        state.medium.announce(msg)

    @replay.entry_point
    def closed(self, state):
        bids = state.medium.get_bids()
        bid = message.Bid.pick_best(bids)[0]
        grant = message.Grant()
        grant.payload['kwargs'] = state.kwargs
        state.medium.grant((bid, grant))

    @replay.entry_point
    def completed(self, state, reports):
        # returns the IRecipient of new agent
        return reports[0].payload


class StartAgentRequester(requester.BaseRequester):

    protocol_id = 'start-agent'
    timeout = 20

    @replay.journaled
    def initiate(self, state, descriptor, allocation_id, *args, **kwargs):
        msg = message.RequestMessage()
        msg.payload['doc_id'] = descriptor.doc_id
        msg.payload['args'] = args
        msg.payload['kwargs'] = kwargs
        msg.payload['allocation_id'] = allocation_id
        state.medium.request(msg)

    def got_reply(self, reply):
        return reply.payload['agent']


@feat.register_descriptor("host_agent")
class Descriptor(descriptor.Descriptor):

    # Agency ID is stored for this type of agent, to have a "salt" in a
    # document which is reinsterted to the database.
    # This is a workaround for a bug in CouchbDB. See:
    # "https://issues.apache.org/jira/browse/COUCHDB-1415
    descriptor.field('agency_id', None)

    @property
    def hostname(self):
        return self.doc_id
