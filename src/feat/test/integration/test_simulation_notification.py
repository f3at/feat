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
from twisted.internet import defer
from twisted.python import failure

from feat.test.integration import common

from feat.agents.base import agent, descriptor, replay, collector, poster
from feat.agencies import recipient
from feat.common.text_helper import format_block
from feat.agents.application import feat

from feat.interface.recipient import *
from feat.interface.protocols import *
from feat.interface.collector import *
from feat.interface.poster import *


@feat.register_descriptor("poster_test_agent")
class PosterDescriptor(descriptor.Descriptor):
    pass


@feat.register_agent("poster_test_agent")
class PosterAgent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state, desc):
        recip = IRecipient(desc)
        state.poster = state.medium.initiate_protocol(DummyPoster, recip)

    @replay.immutable
    def post(self, state, *args, **kwargs):
        state.poster.notify(*args, **kwargs)


@feat.register_descriptor("collector_test_agent")
class CollectorDescriptor(descriptor.Descriptor):
    pass


@feat.register_agent("collector_test_agent")
class CollectorAgent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        state.medium.register_interest(DummyCollector)
        state.notifications = []

    @replay.immutable
    def get_notifications(self, state):
        return state.notifications

    @replay.mutable
    def add_notification(self, state, notif):
        state.notifications.append(notif)


class DummyPoster(poster.BasePoster):
    protocol_id = 'dummy-notification'

    def pack_payload(self, value):
        return value


class DummyCollector(collector.BaseCollector):

    interest_type = InterestType.public
    protocol_id = 'dummy-notification'

    @replay.immutable
    def notified(self, state, message):
        state.agent.add_notification(message.payload)


@common.attr(timescale=0.05)
class NotificationTest(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
        agency = spawn_agency(start_host=False)
        cdesc1 = descriptor_factory('collector_test_agent')
        cdesc2 = descriptor_factory('collector_test_agent')
        pdesc1 = descriptor_factory('poster_test_agent')
        pdesc2 = descriptor_factory('poster_test_agent')
        pdesc3 = descriptor_factory('poster_test_agent')
        cmedium1 = agency.start_agent(cdesc1)
        cmedium2 = agency.start_agent(cdesc2)
        pmedium1 = agency.start_agent(pdesc1, desc=cdesc1)
        pmedium2 = agency.start_agent(pdesc2, desc=cdesc2)
        pmedium3 = agency.start_agent(pdesc3, desc=broadcast)
        collector1 = cmedium1.get_agent()
        collector2 = cmedium2.get_agent()
        poster1 = pmedium1.get_agent()
        poster2 = pmedium2.get_agent()
        poster3 = pmedium3.get_agent()
        """)

        recip = recipient.Broadcast('dummy-notification', 'lobby')
        self.set_local("broadcast", recip)

        return self.process(setup)

    def testValidateProlog(self):
        iter_agents = self.driver.iter_agents
        posters = [x for x in iter_agents("poster_test_agent")]
        collectors = [x for x in iter_agents("collector_test_agent")]
        self.assertEqual(3, len(posters))
        self.assertEqual(2, len(collectors))

    @defer.inlineCallbacks
    def testNotification(self):
        poster1 = self.get_local('poster1')
        poster2 = self.get_local('poster2')
        poster3 = self.get_local('poster3')
        collector1 = self.get_local('collector1')
        collector2 = self.get_local('collector2')

        self.assertEqual(len(collector1.get_notifications()), 0)
        self.assertEqual(len(collector2.get_notifications()), 0)

        poster1.post(1)
        poster2.post(2)
        poster3.post(3)
        poster1.post(4)
        poster2.post(5)
        poster3.post(6)

        check = lambda: len(collector1.get_notifications()) == 4 \
                    and len(collector2.get_notifications()) == 4

        yield self.wait_for(check, 10)

        self.assertEqual(set(collector1.get_notifications()),
                         set([1, 3, 4, 6]))
        self.assertEqual(set(collector2.get_notifications()),
                         set([2, 3, 5, 6]))
