# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import uuid, time

from zope.interface import classProvides, implements
from twisted.internet import reactor, defer

from feat.agencies.emu import agency
from feat.agencies.emu.contracts import ContractorState
from feat.agents import agent, descriptor, contractor, message, manager
from feat.interface import recipient, contracts, protocols
from feat.interface.contractor import IContractorFactory
from feat.interface.manager import IManagerFactory

from . import common


class DummyContractor(contractor.BaseContractor, common.Mock):
    classProvides(IContractorFactory)
    
    protocol_id = 'dummy-contract'
    interest_type = protocols.InterestType.public

    def __init__(self, medium, *args, **kwargs):
        contractor.BaseContractor.__init__(self, medium, *args, **kwargs)
        common.Mock.__init__(self)

    @common.Mock.stub
    def announced(announce):
        pass

    @common.Mock.stub
    def announce_expired():
        pass

    @common.Mock.stub
    def bid_expired():
        pass

    @common.Mock.stub
    def rejected(rejection):
        pass

    @common.Mock.stub
    def granted(grant):
        pass

    @common.Mock.stub
    def cancelled(grant):
        pass

    @common.Mock.stub
    def acknowledged(grant):
        pass

    @common.Mock.stub
    def aborted():
        pass


class DummyManager(manager.BaseManager, common.Mock):
    classProvides(IManagerFactory)

    protocol_id = 'dummy-contract'

    initiate_timeout = 10
    grant_timeout = 10

    def __init__(self, *args, **kwargs):
        manager.BaseManager.__init__(self, *args, **kwargs)
        common.Mock.__init__(self)

    @common.Mock.stub
    def initiate(self):
        pass

    @common.Mock.stub
    def refused(self, refusal):
        pass

    @common.Mock.stub
    def bid(self, bid):
        pass

    @common.Mock.stub
    def closed(self):
        pass

    @common.Mock.stub
    def expired(self):
        pass

    @common.Mock.stub
    def cancelled(self, grant, cancellation):
        pass

    @common.Mock.stub
    def completed(self, grant, report):
        pass

    @common.Mock.stub
    def aborted(self, grant):
        pass



class AgencyTestHelper(object):

    def setUp(self):
        self.agency = agency.Agency()        
        self.session_id = None

    def _setup_endpoint(self):
        '''
        Sets up the destination for tested component to send messages to.

        @returns endpoint: Receipient instance pointing to the queue above
                           (use it for reply-to fields)
        @returns queue: Queue instance we use may .consume() on to get
                        messages from components being tested
        '''
        endpoint = recipient.Agent(str(uuid.uuid1()), 'lobby')
        queue = self.agency._messaging.defineQueue(endpoint.key)
        exchange = self.agency._messaging.defineExchange(endpoint.shard)
        exchange.bind(endpoint.key, queue)
        return endpoint, queue

    def _send_announce(self, manager):
        msg = message.Announcement()
        manager.medium.announce(msg)
        return manager

    def _send_bid(self, contractor, bid=1):
        msg = message.Bid()
        msg.bids = [ bid ]
        contractor.medium.bid(msg)
        return contractor

    def _send_refusal(self, contractor):
        msg = message.Refusal()
        contractor.medium.refuse(msg)
        return contractor

    def _send_final_report(self, contractor):
        msg = message.FinalReport()
        contractor.medium.finalize(msg)
        return contractor

    def _send_cancel(self, contractor, reason=""):
        msg = message.Cancellation()
        msg.reason = reason
        contractor.medium.cancel(msg)
        return contractor

    def _recv_announce(self, *_):
        msg = message.Announcement()
        msg.session_id = str(uuid.uuid1())
        self.session_id = msg.session_id
        return self._recv_msg(msg).addCallback(lambda ret: _)
        
    def _recv_grant(self, _, bid_index=0, update_report=None):
        msg = message.Grant()
        msg.bid_index = bid_index
        msg.update_report = update_report
        msg.session_id = self.session_id
        return self._recv_msg(msg).addCallback(lambda ret: _)
        
    def _recv_rejection(self, _):
        msg = message.Rejection()
        msg.session_id = self.session_id
        return self._recv_msg(msg).addCallback(lambda ret: _)

    def _recv_cancel(self, _, reason=""):
        msg = message.Cancellation()
        msg.reason = reason
        msg.session_id = self.session_id
        return self._recv_msg(msg).addCallback(lambda ret: _)

    def _recv_ack(self, _):
        msg = message.Acknowledgement()
        msg.session_id = self.session_id
        return self._recv_msg(msg).addCallback(lambda ret: _)

    def _recv_msg(self, msg, reply_to=None, key='dummy-contract'):
        d = self.cb_after(arg=None, obj=self.agent, method='on_message')

        if reply_to:
            msg.reply_to = reply_to
        else:
            msg.reply_to = self.endpoint
        msg.expiration_time = time.time() + 10
        msg.protocol_type = "Contract"
        msg.protocol_id = "dummy-contract"
        msg.message_id = str(uuid.uuid1())

        shard = self.agent.descriptor.shard
        self.agent._messaging.publish(key, shard, msg)
        return d

    def _reply(self, msg, reply_to, original_msg):
        d = self.cb_after(arg=None, obj=self.agent, method='on_message')

        dest = recipient.IRecipient(original_msg)

        msg.reply_to = recipient.IRecipient(reply_to)
        msg.message_id = str(uuid.uuid1())
        msg.protocol_id = original_msg.protocol_id
        msg.expiration_time = time.time() + 10
        msg.protocol_type = original_msg.protocol_type

        self.agent._messaging.publish(dest.key, dest.shard, msg)
        return d


class TestManager(common.TestCase, AgencyTestHelper):
    
    timeout = 3

    def setUp(self):
        AgencyTestHelper.setUp(self)
        desc = descriptor.Descriptor()
        self.agent = self.agency.start_agent(agent.BaseAgent, desc)

        self.contractors = []
        for x in range(3):
            endpoint, queue = self._setup_endpoint()
            self.contractors.append({'endpoint': endpoint, 'queue': queue})
        self.recipients = map(lambda x: x['endpoint'], self.contractors)
        self.queues = map(lambda x: x['queue'], self.contractors)

    def start_manager(self):
        self.manager =\
                self.agent.initiate_protocol(DummyManager, self.recipients)
        self.medium = self.manager.medium
        self.session_id = self.medium.session_id

    def assertUnregistered(self, _, state):
        self.assertFalse(self.manager.medium.session_id in\
                             self.agent._listeners)
        self.assertEqual(state, self.manager.medium.state)
        return self.manager

    def _put_bids(self, results, costs):
        '''Put None as a cost to send Refusal'''

        defers = []
        for result, sender, cost in zip(results, self.recipients, costs):
            called, msg = result
            if cost:
                bid = message.Bid()
                bid.bids = [cost]
            else:
                bid = message.Refusal()
            bid.session_id = msg.session_id
            self.log('Puting bid')
            defers.append(self._reply(bid, sender, msg))

        return defer.DeferredList(defers)

    def testInitiateTimeout(self):
        self.agency.time_scale = 0.01
        self.start_manager()

        d = self.cb_after(arg=None, obj=self.agent,
                          method='unregister_listener')

        return d
 
    def testSendAnnouncementAndWaitForExpired(self):
        self.agency.time_scale = 0.01
        self.start_manager()

        self._send_announce(self.manager)
        d = defer.DeferredList(map(lambda x: x.consume(), self.queues))

        def asserts_on_msgs(results):
            for result in results:
                called, arg = result
                self.assertTrue(called)
                self.assertTrue(isinstance(arg, message.Announcement))

        d.addCallback(asserts_on_msgs)
        d.addCallback(lambda x: self.manager)
        d.addCallback(self.cb_after, obj=self.agent,
                      method='unregister_listener')
        d.addCallback(self.assertCalled, 'closed', times=0)
        d.addCallback(self.assertCalled, 'expired')
        d.addCallback(self.assertUnregistered, contracts.ContractState.expired)

        return d

    def testSendAnnouncementRecvBidsAndGoToClosed(self):
        self.agency.time_scale = 0.01
        self.start_manager()
        
        closed = self.cb_after(None, self.medium, '_on_announce_expire')

        self._send_announce(self.manager)
        d = defer.DeferredList(map(lambda x: x.consume(), self.queues))
        d.addCallback(self._put_bids, (1,1,1,))
        d.addCallback(lambda _: closed)

        def asserts_on_manager(_):
            self.assertEqual(contracts.ContractState.closed, self.medium.state)
            self.assertEqual(3, len(self.medium.contractors))
            for bid in self.medium.contractors:
                self.assertTrue(isinstance(bid, message.Bid))

            return self.manager
  
        d.addCallback(asserts_on_manager)
        d.addCallback(self.assertCalled, 'bid', times=3)

        d.addCallback(self.cb_after, obj=self.agent,
                       method='unregister_listener')
        d.addCallback(self.assertUnregistered, contracts.ContractState.expired)

        return d

    def testRefuseAndGrantFromBidHandler(self):

        def bid_handler(s, bid):
            s.log('Received bid: %r', bid.bids)
            if bid.bids[0] == 3:
                s.medium.reject(bid)
            elif bid.bids[0] == 2:
                pass
            elif bid.bids[0] == 1:
                grant = message.Grant(bid_index=0)
                s.medium.grant((bid, grant,))

        self.start_manager()
        self.stub_method(self.manager, 'bid', bid_handler)
        
        self._send_announce(self.manager)
        d = defer.DeferredList(map(lambda x: x.consume(), self.queues))
        d.addCallback(self._put_bids, (3,2,1,))

        d = self.queues[0].consume()
        d.addCallback(self.assertIsInstance, message.Rejection)
        d.addCallback(lambda _: self.queues[1].consume())
        d.addCallback(self.assertIsInstance, message.Rejection)
        d.addCallback(lambda _: self.queues[2].consume())
        d.addCallback(self.assertIsInstance, message.Grant)

        def asserts_on_manager(_):
            self.assertEqual(3, len(self.medium.contractors))
            self.assertEqual(1, len(self.medium.contractors.with_state(\
                        ContractorState.granted)))
            self.assertEqual(2, len(self.medium.contractors.with_state(\
                        ContractorState.rejected)))

        d.addCallback(asserts_on_manager)

        d.addCallback(lambda _: self.medium._terminate())

        return d

    def testGrantingFromClosedState(self):
        self.agency.time_scale = 0.01
        
        def closed_handler(s):
            s.log('Contracts closed, sending grants')
            to_grant = filter(lambda x: x.bids[0] < 3, s.medium.contractors)
            params = map(lambda bid: (bid, message.Grant(bid_index=0),),
                         to_grant)
            s.medium.grant(params)

        self.start_manager()
        self.stub_method(self.manager, 'closed', closed_handler)
        
        self._send_announce(self.manager)
        d = defer.DeferredList(map(lambda x: x.consume(), self.queues))
        d.addCallback(self._put_bids, (3,2,1,))

        d.addCallback(self.cb_after, obj=self.manager, method='closed')
        d.addCallback(lambda _: self.queues[0].consume())
        d.addCallback(self.assertIsInstance, message.Rejection)
        d.addCallback(lambda _: self.queues[1].consume())
        d.addCallback(self.assertIsInstance, message.Grant)
        d.addCallback(lambda _: self.queues[2].consume())
        d.addCallback(self.assertIsInstance, message.Grant)

        def asserts_on_manager(_):
            self.assertEqual(3, len(self.medium.contractors))
            self.assertEqual(2, len(self.medium.contractors.with_state(\
                        ContractorState.granted)))
            self.assertEqual(1, len(self.medium.contractors.with_state(\
                        ContractorState.rejected)))

        d.addCallback(asserts_on_manager)

        d.addCallback(lambda _: self.medium._terminate())

        return d
        
    def testRefusingContractors(self):
        self.agency.time_scale = 0.01
        self.start_manager()
        
        closed = self.cb_after(None, self.medium, '_on_announce_expire')

        self._send_announce(self.manager)
        d = defer.DeferredList(map(lambda x: x.consume(), self.queues))
        # None stands for Refusal
        d.addCallback(self._put_bids, (None,None,None,)) 
        d.addCallback(lambda _: closed)

        def asserts_on_manager(_):
            self.assertEqual(contracts.ContractState.expired, self.medium.state)
            self.assertEqual(3, len(self.medium.contractors))
            for contractor in self.medium.contractors.values():
                self.assertEqual(ContractorState.refused, contractor.state)

            return self.manager
  
        d.addCallback(asserts_on_manager)
        d.addCallback(self.assertCalled, 'bid', times=0)
        d.addCallback(self.assertCalled, 'closed', times=0)
        d.addCallback(self.assertCalled, 'expired', times=1)

        d.addCallback(self.assertUnregistered, contracts.ContractState.expired)

        return d


    def testTimeoutAfterGrant(self):
        self.agency.time_scale = 0.01

        def bid_handler(s, bid):
            s.medium.grant((bid, message.Grant(bid_index=0),))

        self.start_manager()
        self.stub_method(self.manager, 'bid', bid_handler)

        self._send_announce(self.manager)
        d = defer.DeferredList(map(lambda x: x.consume(), self.queues))
        # None stands for Refusal
        d.addCallback(self._put_bids, (1,2,3,))
        
        d.addCallback(self.cb_after, obj=self.agent,
                      method='unregister_listener')
        d.addCallback(self.assertUnregistered, contracts.ContractState.aborted)
        d.addCallback(lambda _: self.manager)
        d.addCallback(self.assertCalled, 'aborted')
        
        return d
        

class TestContractor(common.TestCase, AgencyTestHelper):

    timeout = 3

    def setUp(self):
        AgencyTestHelper.setUp(self)
        desc = descriptor.Descriptor()
        self.agent = self.agency.start_agent(agent.BaseAgent, desc)
        self.agent.register_interest(DummyContractor)

        self.contractor = None
        self.session_id = None
        self.endpoint, self.queue = self._setup_endpoint()

    def tearDown(self):
        self._cancel_expiration_call_if_necessary()

    def testRecivingAnnouncement(self):
        d = self._recv_announce()
        
        def asserts(_):
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
            self.log("Received report message")

        for x in range(3):
            d.addCallback(self.queue.consume)
            d.addCallback(assert_msg_is_report)

        d.addCallback(self._get_contractor)
        d.addCallback(lambda contractor: contractor.medium._terminate())

        return d

    def testBidRejected(self):
        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid)
        d.addCallback(self._recv_rejection)

        d.addCallback(self.assertCalled, 'rejected', params=[message.Rejection])
        d.addCallback(self.assertUnregistered, contracts.ContractState.rejected)

        return d
        
    def testCancelingGrant(self):
        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid)
        d.addCallback(self._recv_grant)
        d.addCallback(self._send_cancel)
        
        d.addCallback(self.assertUnregistered,
                      contracts.ContractState.cancelled)

        return d

    def testCancellingByManager(self):
        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid)
        d.addCallback(self._recv_grant)
        d.addCallback(self._recv_cancel)
        
        d.addCallback(self.assertCalled, 'cancelled',
                      params=[message.Cancellation])
        d.addCallback(self.assertUnregistered,
                      contracts.ContractState.cancelled)

        return d
        
    def testSendingReportThanExpiring(self):
        self.agency.time_scale = 0.01

        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid)
        d.addCallback(self._recv_grant)
        d.addCallback(self._send_final_report)
        
        def asserts(contractor):
            self.assertEqual(contracts.ContractState.completed,
                             contractor.medium.state)

        d.addCallback(asserts)

        d.addCallback(self.cb_after, obj=self.agent,
                      method='unregister_listener')
        d.addCallback(self.assertUnregistered, contracts.ContractState.aborted)
        d.addCallback(self.assertCalled, 'aborted')
        
        return d

    def testSendingReportAndReceivingCancellation(self):
        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid)
        d.addCallback(self._recv_grant)
        d.addCallback(self._send_final_report)
        d.addCallback(self._recv_cancel)

        d.addCallback(self.assertCalled, 'cancelled',
                      params=[message.Cancellation])
        d.addCallback(self.assertUnregistered,
                      contracts.ContractState.cancelled)

        return d

    def testCompletedAndAcked(self):
        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid)
        d.addCallback(self._recv_grant)
        d.addCallback(self._send_final_report)
        d.addCallback(self._recv_ack)

        d.addCallback(self.assertCalled, 'acknowledged',
                      params=[message.Acknowledgement])
        d.addCallback(self.assertUnregistered,
                      contracts.ContractState.acknowledged)

        return d

    def testReceivingFromIncorrectState(self):
        self.agency.time_scale = 0.01
        
        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._recv_grant)
        # this will be ignored, we follow the path to expiration
                
        d.addCallback(self.cb_after, obj=self.agent,\
                          method='unregister_listener')
        d.addCallback(self.assertCalled, 'announce_expired')
        d.addCallback(self.assertUnregistered, contracts.ContractState.closed)
        return d

    def testReceivingUnknownMessage(self):
        self.agency.time_scale = 0.01

        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(lambda contractor:
                 message.BaseMessage(session_id=contractor.medium.session_id))
        d.addCallback(self._recv_msg)
        # this will be ignored, we follow the path to expiration
                
        d.addCallback(lambda _: self.contractor)
        d.addCallback(self.cb_after, obj=self.agent,
                      method='unregister_listener')
        d.addCallback(self.assertCalled, 'announce_expired')
        d.addCallback(self.assertUnregistered, contracts.ContractState.closed)
        return d

    def testSendingMessageFromIncorrectState(self):

        def custom_handler(s, msg):
            s.log("Sending refusal from incorrect state")
            msg = message.Refusal()
            msg.session_id = s.medium.session_id
            s.medium.refuse(msg)

        d = self._recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self._send_bid)
        d.addCallback(self.stub_method, 'granted', custom_handler)
        d.addCallback(self._recv_grant)
        
        d.addCallback(self.assertUnregistered, contracts.ContractState.wtf)

        return d

    def assertUnregistered(self, _, state):
        self.assertFalse(self.contractor.medium.session_id in\
                             self.agent._listeners)
        self.assertEqual(state, self.contractor.medium.state)
        return self.contractor

    def _cancel_expiration_call_if_necessary(self):
        if self.contractor and self.contractor.medium._expiration_call and\
                not (self.contractor.medium._expiration_call.called or
                     self.contractor.medium._expiration_call.cancelled):
            self.warning("Canceling contractor expiration call in tearDown")
            self.contractor.medium._expiration_call.cancel()    

    def _get_contractor(self, _):
        self.contractor = self.agent._listeners.values()[0].contractor
        return self.contractor







