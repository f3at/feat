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
from zope.interface import implements

from feat.agents.base import replay, manager, protocols
from feat.agencies import recipient, message
from feat.common import reflect, serialization, fiber
from feat.agents.application import feat

from feat.interface.contractor import *
from feat.interface.contracts import *
from feat.interface.protocols import *


class MetaContractor(type(replay.Replayable)):
    implements(IContractorFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        cls.application.register_restorator(cls)
        super(MetaContractor, cls).__init__(name, bases, dct)


class BaseContractor(protocols.BaseInterested):
    """
    I am a base class for contractors of contracts.

    @ivar protocol_type: the type of contract this contractor bids on.
                         Must match the type of the manager for this contract;
                         see L{feat.agents.manager.BaseManager}
    @type protocol_type: str
    """

    __metaclass__ = MetaContractor

    implements(IAgentContractor)

    initiator = message.Announcement

    application = feat

    protocol_type = "Contract"
    protocol_id = None

    interest_type = InterestType.private

    bid_timeout = 10
    ack_timeout = 10

    def announced(self, announcement):
        '''@see: L{contractor.IAgentContractor}'''

    def announce_expired(self):
        '''@see: L{contractor.IAgentContractor}'''

    def rejected(self, rejection):
        '''@see: L{contractor.IAgentContractor}'''

    def granted(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def bid_expired(self):
        '''@see: L{contractor.IAgentContractor}'''

    def cancelled(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def acknowledged(self, grant):
        '''@see: L{contractor.IAgentContractor}'''

    def aborted(self):
        '''@see: L{contractor.IAgentContractor}'''


class NestingContractor(BaseContractor):

    @replay.mutable
    def fetch_nested_bids(self, state, recipients, original_announcement,
                          keep_sender=False):
        recipients = recipient.IRecipients(recipients)
        sender = original_announcement.reply_to
        max_distance = original_announcement.max_distance

        if sender in recipients and not keep_sender:
            self.log("Removing sender from list of recipients to nest")
            recipients.remove(sender)
        if len(recipients) == 0:
            self.log("Empty list to nest to, will not nest")
            return fiber.succeed(list())
        elif max_distance is not None and \
             original_announcement.level + 1 > max_distance:
            self.log("Reached max distance for nesting of %d, returning empy "
                     "list.", max_distance)
            return list()
        else:
            self.log("Will nest contract to %d contractors.", len(recipients))

        announcement = original_announcement.duplicate()
        announcement.level += 1

        announcement.expiration_time = self._get_time_window(
            announcement.expiration_time)

        current_time = state.agent.get_time()
        time_left = announcement.expiration_time - current_time
        state.nested_manager = state.agent.initiate_protocol(
            NestedManagerFactory(self.protocol_id, time_left),
            recipients, announcement)
        f = fiber.Fiber()
        f.add_callback(fiber.drop_param,
                       state.nested_manager.wait_for_bids)
        return f.succeed()

    @replay.mutable
    def grant_nested_bids(self, state, original_grant):
        if not hasattr(state, 'nested_manager'):
            return
        grant = original_grant.duplicate()
        grant.expiration_time = self._get_time_window(grant.expiration_time)
        state.nested_manager.grant_all(grant)

    @replay.journaled
    def wait_for_nested_complete(self, state):
        if not hasattr(state, 'nested_manager'):
            return fiber.succeed()
        return state.nested_manager.wait_for_complete()

    @replay.immutable
    def _get_time_window(self, state, expiration_time):
        # nested contract needs to have a smaller window for gathering
        # bids, otherwise everything would expire
        current_time = state.agent.get_time()
        time_left = expiration_time - current_time
        return current_time + 0.9 * time_left

    @replay.immutable
    def terminate_nested_manager(self, state):
        if hasattr(state, 'nested_manager'):
            state.nested_manager.terminate()

    @replay.mutable
    def handover(self, state, bid):
        if hasattr(state, 'nested_manager'):
            state.nested_manager.elect(bid)
        state.medium.handover(bid)


@feat.register_restorator
class NestedManagerFactory(serialization.Serializable):

    implements(manager.IManagerFactory)

    protocol_type = "Contract"

    def __init__(self, protocol_id, time_left):
        self.time_left = time_left
        self.protocol_id = protocol_id

    def __call__(self, agent, medium, *args, **kwargs):
        instance = NestedManager(agent, medium, *args, **kwargs)
        instance.announce_timeout = self.time_left
        instance.protocol_id = self.protocol_id
        return instance

    def __repr__(self):
        return "<NestedManagerFactory for %r, time: %r>" %\
               (self.protocol_id, self.time_left, )

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.time_left == other.time_left and\
               self.protocol_id == other.protocol_id

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


@feat.register_restorator
class NestedManager(manager.BaseManager):

    @replay.journaled
    def initiate(self, state, announcement):
        state.medium.announce(announcement)

    @replay.immutable
    def wait_for_bids(self, state):
        #FIXME: It would be better to use an agent notifier
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, state.medium.wait_for_state,
                       ContractState.closed, ContractState.expired)
        f.add_callback(fiber.drop_param, state.medium.get_bids)
        return f

    @replay.mutable
    def grant_all(self, state, grant):
        bids = state.medium.get_bids()
        if bids:
            params = map(lambda bid: (bid, grant, ), bids)
            state.medium.grant(params)

    @replay.immutable
    def wait_for_complete(self, state):
        #FIXME: It would be better to use an agent notifier
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, state.medium.wait_for_state,
                       ContractState.completed, ContractState.expired)
        f.add_callback(fiber.override_result, None)
        return f

    @replay.journaled
    def terminate(self, state):
        state.medium.terminate()

    @replay.immutable
    def elect(self, state, bid):
        state.medium.elect(bid)


@feat.register_restorator
class Service(serialization.Serializable):
    implements(IContractorFactory)

    protocol_type = "Contract"
    interest_type = InterestType.public
    initiator = message.Announcement

    def __init__(self, identifier):
        if not isinstance(identifier, str):
            identifier = IInterest(identifier).protocol_id
        self.protocol_id = 'discover-' + identifier

    def __call__(self, agent, medium):
        instance = ServiceDiscoveryContractor(agent, medium)
        instance.protocol_id = self.protocol_id
        return instance

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.protocol_id == other.protocol_id

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


class ServiceDiscoveryContractor(BaseContractor):

    interest_type = InterestType.public

    @replay.journaled
    def announced(self, state, announcement):
        state.medium.bid(message.Bid())
