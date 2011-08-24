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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat.agencies import tunneling
from feat.agencies.emu import tunneling as emu_tunneling
from feat.agencies.net import tunneling as net_tunneling
from feat.agents.base import message, recipient
from feat.common import serialization

from . import common


class Notification1(message.Notification):
    type_name = "dummy-notif"

    def __init__(self, *args, **kwargs):
        message.Notification.__init__(self, *args, **kwargs)
        if "value" not in self.payload:
            self.payload["value"] = "42"


class Notification2(Notification1):
    type_name = "dummy-notif"

    def __init__(self, *args, **kwargs):
        message.Notification.__init__(self, *args, **kwargs)
        if "value" not in self.payload:
            self.payload["value"] = 42

    @staticmethod
    def upgrade_to_2(snapshot):
        old_value = snapshot["payload"]["value"]
        snapshot["payload"]["value"] = int(old_value)
        return snapshot

    @staticmethod
    def downgrade_to_1(snapshot):
        old_value = snapshot["payload"]["value"]
        snapshot["payload"]["value"] = str(old_value)
        return snapshot


class TestMixin(object):

    def testCreateChannel(self):
        agent = common.StubAgent()
        channel = yield self.backend1.new_channel(agent)
        self.assertTrue(isinstance(channel, tunneling.Channel))
        channel.release()

    @defer.inlineCallbacks
    def testSimplePostMessage(self):
        agent = common.StubAgent()
        channel = yield self.backend1.new_channel(agent)

        msg = message.BaseMessage(payload='some message')
        recip = self._mk_recip(agent)

        channel.post(recip, msg)

        yield self.wait_for_idle()

        self.assertEqual(1, len(agent.messages))
        self.assertEqual('some message', agent.messages[0].payload)

        channel.release()

        msg = message.BaseMessage(payload='other message')
        recip = self._mk_recip(agent)

        channel.post(recip, msg)

        yield self.wait_for_idle()

        self.assertEqual(1, len(agent.messages))

    @defer.inlineCallbacks
    def testDialog(self):
        agent1 = common.StubAgent()
        agent2 = common.StubAgent()

        channel1 = yield self.backend1.new_channel(agent1)
        channel2 = yield self.backend1.new_channel(agent2)

        recip1 = self._mk_recip(agent1)
        recip2 = self._mk_recip(agent2)

        msg1 = message.DialogMessage()
        msg1.payload = "spam"

        channel1.post(recip2, msg1)

        yield self.wait_for_idle()

        self.assertEqual(len(agent2.messages), 1)
        msg1b = agent2.messages[0]
        self.assertEqual(msg1b.payload, "spam")
        self.assertEqual(msg1b.reply_to.key, agent1.get_agent_id())
        self.assertEqual(msg1b.reply_to.channel, self.backend1.channel_type)
        self.assertEqual(msg1b.reply_to.route, self.backend1.route)

        msg2 = message.DialogMessage()
        msg2.payload = "bacon"

        channel2.post(msg1b.reply_to, msg2)

        yield self.wait_for_idle()

        self.assertEqual(len(agent1.messages), 1)
        msg2b = agent1.messages[0]
        self.assertEqual(msg2b.payload, "bacon")
        self.assertEqual(msg2b.reply_to.key, agent2.get_agent_id())
        self.assertEqual(msg2b.reply_to.channel, self.backend1.channel_type)
        self.assertEqual(msg2b.reply_to.route, self.backend1.route)

        msg3 = message.DialogMessage()
        msg3.payload = "eggs"
        msg3.reply_to = recip1

        channel1.post(recip2, msg3)

        yield self.wait_for_idle()

        self.assertEqual(len(agent2.messages), 2)
        msg1b = agent2.messages[1]
        self.assertEqual(msg1b.payload, "eggs")
        self.assertEqual(msg1b.reply_to.key, agent1.get_agent_id())
        self.assertEqual(msg1b.reply_to.channel, self.backend1.channel_type)
        self.assertEqual(msg1b.reply_to.route, self.backend1.route)

    @defer.inlineCallbacks
    def testMultipleRecipients(self):
        agent1 = common.StubAgent()
        agent2 = common.StubAgent()
        agent3 = common.StubAgent()
        agent4 = common.StubAgent()

        channel1 = yield self.backend1.new_channel(agent1)
        yield self.backend1.new_channel(agent2)
        yield self.backend1.new_channel(agent3)

        recip1 = self._mk_recip(agent1)
        recip2 = self._mk_recip(agent2)
        recip3 = self._mk_recip(agent3)
        recip4 = self._mk_recip(agent4)

        msg = message.BaseMessage(payload='beans')

        channel1.post([recip1, recip2, recip3, recip4], msg)

        yield self.wait_for_idle()

        self.assertEqual(len(agent1.messages), 1)
        self.assertEqual(len(agent2.messages), 1)
        self.assertEqual(len(agent3.messages), 1)
        self.assertEqual(len(agent4.messages), 0)
        self.assertEqual(agent1.messages[0].payload, "beans")
        self.assertEqual(agent2.messages[0].payload, "beans")
        self.assertEqual(agent3.messages[0].payload, "beans")

    @defer.inlineCallbacks
    def testConvertion(self):
        agent1 = common.StubAgent()
        channel1 = yield self.backend1.new_channel(agent1)

        agent2 = common.StubAgent()
        channel2 = yield self.backend2.new_channel(agent2)

        msg = Notification1()
        msg.payload["value"] = "33"
        recip2 = self._mk_recip(agent2, self.backend2)

        channel1.post(recip2, msg)

        yield self.wait_for_idle()

        self.assertEqual(1, len(agent2.messages))
        self.assertEqual(agent2.messages[0].payload, {"value": 33})

        msg = Notification2()
        msg.payload["value"] = 66
        recip1 = self._mk_recip(agent1, self.backend1)

        channel2.post(recip1, msg)

        yield self.wait_for_idle()

        self.assertEqual(1, len(agent1.messages))
        self.assertEqual(agent1.messages[0].payload, {"value": "66"})

    ### private ###

    def wait_for_idle(self):

        def check():
            return self.backend1.is_idle() and self.backend2.is_idle()

        return self.wait_for(check, 20)

    def _mk_recip(self, agent, backend=None):
        backend = backend if backend is not None else self.backend1
        return recipient.Recipient(agent.get_agent_id(),
                                   backend.route,
                                   backend.channel_type)


class TestEmuTunneling(common.TestCase, TestMixin):

    timeout = 5

    def setUp(self):
        bridge = emu_tunneling.Bridge()

        registry1 = serialization.get_registry().clone()
        registry1.register(Notification1)
        self.backend1 = emu_tunneling.Backend(version=1, bridge=bridge,
                                              registry=registry1)

        registry2 = serialization.get_registry().clone()
        registry2.register(Notification2)
        self.backend2 = emu_tunneling.Backend(version=2, bridge=bridge,
                                              registry=registry2)

        return common.TestCase.setUp(self)

    def tearDown(self):
        self.backend1.disconnect()
        self.backend2.disconnect()
        return common.TestCase.tearDown(self)


class TestNetTunneling(common.TestCase, TestMixin):

    timeout = 5

    def setUp(self):
        port_range = range(4000, 4100)
        registry1 = serialization.get_registry().clone()
        registry1.register(Notification1)
        self.backend1 = net_tunneling.Backend("localhost",
                                              port_range=port_range,
                                              version=1, registry=registry1)

        registry2 = serialization.get_registry().clone()
        registry2.register(Notification2)
        self.backend2 = net_tunneling.Backend("localhost",
                                              port_range=port_range,
                                              version=2, registry=registry2)

        return common.TestCase.setUp(self)

    def tearDown(self):
        self.backend1.disconnect()
        self.backend2.disconnect()
        return common.TestCase.tearDown(self)
