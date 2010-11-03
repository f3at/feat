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

    def __init__(self, *args, **kwargs):
        contractor.BaseContractor.__init__(self, *args, **kwargs)
        common.Mock.__init__(self)

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
        self.contractor = None

    def tearDown(self):
        self._cancel_expiration_call_if_necessary()

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
            self.assertNotEqual(None, contractor.medium.announce)
            self.assertEqual(announce, contractor.medium.announce)
            self.assertTrue(isinstance(contractor.medium.announce,\
                                       message.Announcement))

        d.addCallback(asserts_on_contractor)
        
        return d

    def testContractorExpireExpirationTime(self):
        self.agency.time_scale = 0.01

        d = self._send_announcement()
        d.addCallback(self.cb_after, obj=self.agent,\
                          method='unregister_listener')

        return d

    def testPutingBid(self):
        d = self._send_announcement()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid)

        def asserts(contractor):
            self.assertEqual(contracts.ContractState.bid, contractor.state)

        d.addCallback(asserts)
        d.addCallback(self.queue.consume)
        
        def asserts_on_bid(msg):
            self.assertEqual(message.Bid, msg.__class__)
            self.assertEqual(self.contractor.medium.bid, msg)

        
        d.addCallback(asserts_on_bid)

        return d            

    def _cancel_expiration_call_if_necessary(self):
        if self.contractor and self.contractor.medium._expiration_call and\
                not (self.contractor.medium._expiration_call.called or
                     self.contractor.medium._expiration_call.cancelled):
            self.warning("Canceling contractor expiration call in tearDown")
            self.contractor.medium._expiration_call.cancel()    

    def _get_contractor(self, _):
        self.contractor = self.agent._listeners.values()[0].contractor
        return self.contractor

    def _send_bid(self, contractor):
        msg = message.Bid()
        msg.bids = [ 1 ]
        contractor.medium.bid(msg)
        return contractor

    def _send_announcement(self, *_):
        msg = message.Announcement()
        msg.session_id = str(uuid.uuid1())
        return self._send_msg(msg)

    def _send_msg(self, msg):
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






