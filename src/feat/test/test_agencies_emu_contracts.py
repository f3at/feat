# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid, time

from zope.interface import classProvides, implements
from twisted.internet import reactor, defer

from feat.agencies.emu import agency
from feat.agents import agent, descriptor, contractor, message, manager
from feat.interface import recipient, contracts
from feat.interface.contractor import IContractorFactory

from . import common


class DummyContractor(contractor.BaseContractor, common.Mock):
    classProvides(IContractorFactory)
    
    protocol_id = 'dummy-contract'

    @common.stub
    def announced(announce):
        pass


class TestContractor(common.TestCase):

    timeout = 3

    def setUp(self):
        self.agency = agency.Agency()
        desc = descriptor.Descriptor()
        self.agent = self.agency.start_agent(agent.BaseAgent, desc)
        self.agent.register_interest(DummyContractor)

        self.endpoint = recipient.Agent(str(uuid.uuid1()), 'lobby')
        self.queue = self.agency._messaging.defineQueue(self.endpoint.key)
        exchange = self.agency._messaging._getExchange(self.endpoint.shard)
        exchange.bind(self.endpoint.key, self.queue)

    def testRecivingAnnouncement(self):
        d = self._send_announcement()
        
        def asserts(rpl):
            self.assertEqual(True, rpl)
            self.assertEqual(1, len(self.agent._listeners))

        d.addCallback(asserts)
        d.addCallback(self._get_contractor)

        def asserts_on_contractor(contractor):
            self.assertEqual(DummyContractor, contractor.__class__)
            self.assertCalled(contractor, 'announced', times=1)
            args = contractor.find_calls('announced')[0].args
            self.assertEqual(1, len(args))
            announce = args[0]
            self.assertEqual(contracts.ContractState.announced,
                             contractor.state)
            self.assertNotEqual(None, contractor.announce)
            self.assertEqual(announce, contractor.announce)
            self.assertTrue(isinstance(contractor.announce,\
                                       message.Announcement))

        d.addCallback(asserts_on_contractor)
        
        return d

    def _get_contractor(self, _):
        return self.agent._listeners.values()[0].contractor

    def _send_announcement(self):
        msg = message.Announcement()
        msg.session_id = str(uuid.uuid1())
        return self._sendMsg(msg)

    def _sendMsg(self, msg):
        d = self.cb_after(arg=None, obj=self.agent, method='on_message')
        msg.reply_to_shard = self.endpoint.shard
        msg.reply_to_key = self.endpoint.key
        msg.expiration_time = time.time() + 10
        msg.protocol_type = "Contract"
        msg.protocol_id = "dummy-contract"
        msg.message_id = str(uuid.uuid1())

        key = self.agent.descriptor.uuid
        shard = self.agent.descriptor.shard
        self.agent._messaging.publish(key, shard, msg)
        return d






