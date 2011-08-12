# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import uuid

from twisted.internet import defer, reactor

from feat.agencies import tunneling
from feat.agencies.emu import tunneling as emu_tunneling
from feat.agents.base import message, recipient

from . import common


class TestTunneling(common.TestCase):

    timeout = 5

    def setUp(self):
        self.backend = emu_tunneling.Backend()

    def testCreateChannel(self):
        agent = common.StubAgent()
        channel = yield self.backend.new_channel(agent)
        self.assertTrue(isinstance(channel, tunneling.Channel))
        channel.release()

    @defer.inlineCallbacks
    def testSimplePostMessage(self):
        agent = common.StubAgent()
        channel = yield self.backend.new_channel(agent)

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

        channel1 = yield self.backend.new_channel(agent1)
        channel2 = yield self.backend.new_channel(agent2)

        recip1 = self._mk_recip(agent1)
        recip2 = self._mk_recip(agent2)

        msg1 = message.DialogMessage()
        msg1.payload = "spam"

        channel1.post(recip2, msg1)

        yield self.wait_for_idle()

        self.assertEqual(len(agent2.messages), 1)
        msg1b = agent2.messages[0]
        self.assertEqual(msg1b.payload, "spam")
        self.assertEqual(msg1b.reply_to.key, agent1.channel_id)
        self.assertEqual(msg1b.reply_to.channel, self.backend.channel_type)
        self.assertEqual(msg1b.reply_to.route, self.backend.get_route())

        msg2 = message.DialogMessage()
        msg2.payload = "bacon"

        channel2.post(msg1b.reply_to, msg2)

        yield self.wait_for_idle()

        self.assertEqual(len(agent1.messages), 1)
        msg2b = agent1.messages[0]
        self.assertEqual(msg2b.payload, "bacon")
        self.assertEqual(msg2b.reply_to.key, agent2.channel_id)
        self.assertEqual(msg2b.reply_to.channel, self.backend.channel_type)
        self.assertEqual(msg2b.reply_to.route, self.backend.get_route())

        msg3 = message.DialogMessage()
        msg3.payload = "eggs"
        msg3.reply_to = recip1

        channel1.post(recip2, msg3)

        yield self.wait_for_idle()

        self.assertEqual(len(agent2.messages), 2)
        msg1b = agent2.messages[1]
        self.assertEqual(msg1b.payload, "eggs")
        self.assertEqual(msg1b.reply_to.key, agent1.channel_id)
        self.assertEqual(msg1b.reply_to.channel, self.backend.channel_type)
        self.assertEqual(msg1b.reply_to.route, self.backend.get_route())

    @defer.inlineCallbacks
    def testMultipleRecipients(self):
        agent1 = common.StubAgent()
        agent2 = common.StubAgent()
        agent3 = common.StubAgent()
        agent4 = common.StubAgent()

        channel1 = yield self.backend.new_channel(agent1)
        yield self.backend.new_channel(agent2)
        yield self.backend.new_channel(agent3)

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

    ### private ###

    def wait_for_idle(self):
        return self.wait_for(self.backend.is_idle, 20)

    def _mk_recip(self, agent):
        return recipient.Recipient(agent.channel_id,
                                   self.backend.get_route(),
                                   self.backend.channel_type)
