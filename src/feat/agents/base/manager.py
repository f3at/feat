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

from feat.agents.base import protocols, replay
from feat.agencies import message
from feat.common import serialization, reflect
from feat.agents.application import feat

from feat.interface.manager import *
from feat.interface.protocols import *


class MetaManager(type(replay.Replayable)):

    implements(IManagerFactory)

    def __init__(cls, name, bases, dct):
        cls.type_name = reflect.canonical_name(cls)
        cls.application.register_restorator(cls)
        super(MetaManager, cls).__init__(name, bases, dct)


class BaseManager(protocols.BaseInitiator):
    """
    I am a base class for managers of contracts.

    @ivar protocol_type: the type of contract this manager manages.
                         Must match the type of the contractor for this
                         contract; see L{feat.agents.contractor.BaseContractor}
    @type protocol_type: str
    """

    __metaclass__ = MetaManager

    implements(IAgentManager)

    application = feat

    protocol_type = "Contract"
    protocol_id = None

    initiate_timeout = 10
    announce_timeout = 10
    grant_timeout = 10

    def bid(self, bid):
        '''@see: L{manager.IAgentManager}'''

    def closed(self):
        '''@see: L{manager.IAgentManager}'''

    def expired(self):
        '''@see: L{manager.IAgentManager}'''

    def cancelled(self, cancellation):
        '''@see: L{manager.IAgentManager}'''

    def completed(self, report):
        '''@see: L{manager.IAgentManager}'''

    def aborted(self):
        '''@see: L{manager.IAgentManager}'''


@feat.register_restorator
class DiscoverService(serialization.Serializable):

    implements(IManagerFactory)

    protocol_type = "Contract"

    def __init__(self, identifier, timeout):
        if not isinstance(identifier, str):
            identifier = IInitiatorFactory(identifier).protocol_id

        self.protocol_id = 'discover-' + identifier
        self.timeout = timeout

    def __call__(self, agent, medium):
        instance = ServiceDiscoveryManager(agent, medium)
        instance.protocol_id = self.protocol_id
        instance.announce_timeout = self.timeout
        return instance


class ServiceDiscoveryManager(BaseManager):

    @replay.journaled
    def initiate(self, state):
        state.providers = list()
        state.medium.announce(message.Announcement())

    @replay.mutable
    def bid(self, state, bid):
        state.providers.append(bid.reply_to)
        state.medium.reject(bid, message.Rejection())

    @replay.immutable
    def expired(self, state):
        return state.providers
