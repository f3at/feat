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

    @common.stub
    def announce_expired():
        pass

    @common.stub
    def bid_expired():
        pass

    @common.stub
    def rejected(rejection):
        pass

    @common.stub
    def granted(grant):
        pass

    @common.stub
    def canceled(grant):
        pass

    @common.stub
    def acknowledged(grant):
        pass

    @common.stub
    def aborted():
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
        self.session_id = None

    def tearDown(self):
        self._cancel_expiration_call_if_necessary()

    def testRecivingAnnouncement(self):
        d = self._recv_announce()
        
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
                             contractor.medium.state)
            self.assertNotEqual(None, contractor.medium.announce)
            self.assertEqual(announce, contractor.medium.announce)
            self.assertTrue(isinstance(contractor.medium.announce,\
                                       message.Announcement))

        d.addCallback(asserts_on_contractor)
        
        return d

    def testAnnounceExpiration(self):
        self.agency.time_scale = 0.01

        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.cb_after, obj=self.agent,\
                          method='unregister_listener')
        d.addCallback(self.assertCalled, 'announce_expired')

        return d

    def testPuttingBid(self):
        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid)

        def asserts(contractor):
            self.assertEqual(contracts.ContractState.bid,
                             contractor.medium.state)

        d.addCallback(asserts)
        d.addCallback(self.queue.consume)
        
        def asserts_on_bid(msg):
            self.assertEqual(message.Bid, msg.__class__)
            self.assertEqual(self.contractor.medium.bid, msg)

        d.addCallback(asserts_on_bid)

        return d            

    def testPuttingBidAndReachingTimeout(self):
        self.agency.time_scale = 0.01

        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid)
        d.addCallback(self.cb_after, obj=self.agent,\
                          method='unregister_listener')
        d.addCallback(self.assertCalled, 'bid_expired')
        d.addCallback(self.assertUnregistered, contracts.ContractState.expired)

        return d

    def testRefusing(self):
        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_refusal)

        d.addCallback(self.assertUnregistered, contracts.ContractState.refused)
        d.addCallback(self.queue.consume)
        
        def asserts_on_refusal(msg):
            self.assertEqual(message.Refusal, msg.__class__)
            self.assertEqual(self.contractor.medium.session_id, msg.session_id)

        d.addCallback(asserts_on_refusal)
        
        return d

    def testCorrectGrant(self):
        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid, 1)
        d.addCallback(self._recv_grant, bid_index=0)

        def asserts(_):
            self.assertEqual(contracts.ContractState.granted,\
                                 self.contractor.medium.state)
            self.assertCalled(self.contractor, 'granted')
            call = self.contractor.find_calls('granted')[0]
            self.assertEqual(1, len(call.args))
            self.assertEqual(message.Grant, call.args[0].__class__)
            self.assertEqual(0, call.args[0].bid_index)

        d.addCallback(asserts)

        return d

    def testGrantWithBidWeHaventSent(self):
        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid, 1)
        d.addCallback(self._recv_grant, bid_index=1)

        d.addCallback(self.assertUnregistered, contracts.ContractState.wtf)

        return d

    def testGrantWithUpdater(self):
        self.agency.time_scale = 0.01

        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid, 1)
        d.addCallback(self._recv_grant, bid_index=0, update_report=1)

        d.addCallback(self.queue.consume) # this is a bid
        
        def assert_msg_is_report(msg):
            self.assertEqual(message.UpdateReport, msg.__class__)

        for x in range(3):
            d.addCallback(self.queue.consume)
            d.addCallback(assert_msg_is_report)

        d.addCallback(self._get_contractor)
        d.addCallback(lambda contractor: contractor.medium._terminate())

        return d

    def assertUnregistered(self, _, state):
        self.assertFalse(self.contractor.medium.session_id in\
                             self.agent._listeners)
        self.assertEqual(state, self.contractor.medium.state)

    def _cancel_expiration_call_if_necessary(self):
        if self.contractor and self.contractor.medium._expiration_call and\
                not (self.contractor.medium._expiration_call.called or
                     self.contractor.medium._expiration_call.cancelled):
            self.warning("Canceling contractor expiration call in tearDown")
            self.contractor.medium._expiration_call.cancel()    

    def _get_contractor(self, _):
        self.contractor = self.agent._listeners.values()[0].contractor
        return self.contractor

    def _send_bid(self, contractor, bid=1):
        msg = message.Bid()
        msg.bids = [ bid ]
        contractor.medium.bid(msg)
        return contractor

    def _send_refusal(self, contractor):
        msg = message.Refusal()
        contractor.medium.refuse(msg)
        return contractor

    def _recv_announce(self, *_):
        msg = message.Announcement()
        msg.session_id = str(uuid.uuid1())
        self.session_id = msg.session_id
        return self._recv_msg(msg)

    def _recv_grant(self, _, bid_index, update_report=None):
        msg = message.Grant()
        msg.bid_index = bid_index
        msg.update_report = update_report
        msg.session_id = self.session_id
        return self._recv_msg(msg)

    def _recv_msg(self, msg):
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






