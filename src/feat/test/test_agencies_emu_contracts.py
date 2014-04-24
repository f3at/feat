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
# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid

from feat.agencies import message, recipient
from feat.agencies.contracts import ContractorState, AgencyContractor
from feat.agents.base import descriptor, contractor, replay, manager
from feat.interface import contracts, protocols
from feat.common import time, defer, first

from feat.test import common


class DummyContractor(contractor.BaseContractor, common.Mock):

    protocol_id = 'dummy-contract'
    interest_type = protocols.InterestType.public

    def __init__(self, medium, *args, **kwargs):
        contractor.BaseContractor.__init__(self, medium, *args, **kwargs)
        common.Mock.__init__(self)

    @replay.immutable
    def _get_medium(self, state):
        return state.medium

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

    protocol_id = 'dummy-contract'

    initiate_timeout = 10
    grant_timeout = 10

    def __init__(self, *args, **kwargs):
        manager.BaseManager.__init__(self, *args, **kwargs)
        common.Mock.__init__(self)

    @replay.immutable
    def _get_medium(self, state):
        return state.medium

    @common.Mock.stub
    def initiate(self):
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
    def cancelled(self, cancellation):
        pass

    @common.Mock.stub
    def completed(self, reports):
        pass

    @common.Mock.stub
    def aborted(self):
        pass


@common.attr(timescale=0.05)
class TestManager(common.TestCase, common.AgencyTestHelper):

    protocol_type = 'Contract'
    protocol_id = 'dummy-contract'

    timeout = 3

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        yield common.AgencyTestHelper.setUp(self)
        desc = yield self.doc_factory(descriptor.Descriptor)
        self.log("Descriptor: %r", desc)
        self.agent = yield self.agency.start_agent(desc)

        self.contractors = []
        for x in range(3):
            endpoint, queue = self.setup_endpoint()
            self.contractors.append({'endpoint': endpoint, 'queue': queue})
        self.recipients = map(lambda x: x['endpoint'], self.contractors)
        self.queues = map(lambda x: x['queue'], self.contractors)

    def start_manager(self):
        self.manager =\
                self.agent.initiate_protocol(DummyManager, self.recipients)
        self.finished = self.manager.notify_finish()
        self.medium = self.manager._get_medium()
        self.guid = self.medium.guid
        return self.medium.wait_for_state(contracts.ContractState.initiated)

    @defer.inlineCallbacks
    def assertState(self, _, state):
        self.assertEqual(state, self.manager._get_medium().state)
        if state not in (contracts.ContractState.completed,
                         contracts.ContractState.terminated, ):
            self.assertFailure(self.finished, protocols.ProtocolFailed)
            yield self.finished
        defer.returnValue(self.manager)

    def _consume_all(self, *_):
        return defer.DeferredList(map(lambda x: x.get(), self.queues))

    def _put_bids(self, results, costs):
        '''
        Put "refuse" as a cost to send Refusal.
        Put "skip" to ignore
        '''

        defers = []
        for result, sender, cost in zip(results, self.recipients, costs):
            called, msg = result
            assert cost is not None
            if cost and cost == "skip":
                continue
            elif cost and cost == "refuse":
                bid = message.Refusal()
            else:
                bid = message.Bid()
                bid.payload['cost'] = cost

            self.log('Puting bid')
            defers.append(self.reply(bid, sender, msg))

        return defer.DeferredList(defers)

    def testInitiateTimeout(self):
        d = self.start_manager()
        d.addCallback(self._wait_for_finish)
        d.addCallback(self.assertState, contracts.ContractState.wtf)
        return d

    def testSendAnnouncementAndWaitForExpired(self):
        d = self.start_manager()

        d.addCallback(defer.drop_param, self.send_announce, self.manager)
        d.addCallback(defer.drop_param, self._consume_all)

        def asserts_on_msgs(results):
            for result in results:
                called, arg = result
                self.assertTrue(called)
                self.assertTrue(isinstance(arg, message.Announcement))
                self.assertFalse(arg.traversal_id is None)

        d.addCallback(asserts_on_msgs)
        d.addCallback(self._wait_for_finish)
        d.addCallback(lambda x: self.manager)
        d.addCallback(self.assertCalled, 'closed', times=0)
        d.addCallback(self.assertCalled, 'expired')
        d.addCallback(self.assertState, contracts.ContractState.expired)

        return d

    @common.attr(timescale=0.02)
    def testSendAnnouncementRecvBidsAndGoToClosed(self):
        d = self.start_manager()

        closed = self.cb_after(None, self.medium, '_on_announce_expire')

        d.addCallback(defer.drop_param, self.send_announce, self.manager)
        d = self._consume_all()
        d.addCallback(self._put_bids, (1, 1, "skip", ))
        d.addCallback(lambda _: closed)

        def asserts_on_manager(_):
            self.assertEqual(contracts.ContractState.closed, self.medium.state)
            self.assertEqual(2, len(self.medium.contractors))
            for x in self.medium.contractors.values():
                self.assertTrue(isinstance(x.bid, message.Bid))

            return self.manager

        d.addCallback(asserts_on_manager)
        d.addCallback(self.assertCalled, 'bid', times=2)
        d.addCallback(self._wait_for_finish)
        d.addCallback(self.assertState, contracts.ContractState.expired)

        return d

    def testRefuseAndGrantFromBidHandler(self):

        @replay.immutable
        def bid_handler(s, state, bid):
            s.log('Received bid: %r', bid.payload['cost'])
            if bid.payload['cost'] == 3:
                state.medium.reject(bid)
            elif bid.payload['cost'] == 2:
                pass
            elif bid.payload['cost'] == 1:
                grant = message.Grant()
                state.medium.grant((bid, grant, ))

        d = self.start_manager()
        self.stub_method(self.manager, 'bid', bid_handler)

        d.addCallback(defer.drop_param, self.send_announce, self.manager)
        d.addCallback(defer.drop_param, self._consume_all)
        d.addCallback(self._put_bids, (3, 2, 1, ))

        d = self.queues[0].get()
        d.addCallback(self.assertIsInstance, message.Rejection)
        d.addCallback(lambda _: self.queues[1].get())
        d.addCallback(self.assertIsInstance, message.Rejection)
        d.addCallback(lambda _: self.queues[2].get())
        d.addCallback(self.assertIsInstance, message.Grant)

        def asserts_on_manager(_):
            self.assertEqual(3, len(self.medium.contractors))
            self.assertEqual(1, len(self.medium.contractors.with_state(\
                        ContractorState.granted)))
            self.assertEqual(2, len(self.medium.contractors.with_state(\
                        ContractorState.rejected)))

        d.addCallback(asserts_on_manager)
        d.addCallback(self.assertState, contracts.ContractState.expired)

        return d

    def testGrantingFromClosedState(self):

        @replay.immutable
        def closed_handler(s, state):
            s.log('Contracts closed, sending grants')
            to_grant = [x.bid for x in state.medium.contractors.values()
                        if x.bid.payload['cost'] < 3]
            params = map(lambda bid: (bid, message.Grant(), ),
                         to_grant)
            state.medium.grant(params)

        d = self.start_manager()
        self.stub_method(self.manager, 'closed', closed_handler)

        d.addCallback(defer.drop_param, self.send_announce, self.manager)
        d.addCallback(defer.drop_param, self._consume_all)

        def put_bids(results):
            cb = self.cb_after(None, obj=self.manager, method='closed')
            self._put_bids(results, (3, 2, 1, ))
            return cb

        d.addCallback(put_bids)

        d.addCallback(lambda _: self.queues[0].get())
        d.addCallback(self.assertIsInstance, message.Rejection)
        d.addCallback(lambda _: self.queues[1].get())
        d.addCallback(self.assertIsInstance, message.Grant)
        d.addCallback(lambda _: self.queues[2].get())
        d.addCallback(self.assertIsInstance, message.Grant)

        def asserts_on_manager(_):
            self.assertEqual(3, len(self.medium.contractors))
            self.assertEqual(2, len(self.medium.contractors.with_state(\
                        ContractorState.granted)))
            self.assertEqual(1, len(self.medium.contractors.with_state(\
                        ContractorState.rejected)))

        d.addCallback(asserts_on_manager)

        d.addCallback(lambda _: self._terminate_manager())
        d.addCallback(self.assertState, contracts.ContractState.granted)

        return d

    def testTerminatingFromClosedState(self):

        @replay.immutable
        def closed_handler(s, state):
            s.log('Contracts closed, terminating.')
            bidded = state.medium.contractors.with_state(ContractorState.bid)
            to_elect = first(x.bid for x in bidded
                             if x.bid.payload['cost'] == 3)

            state.medium.elect(to_elect)
            state.medium.terminate()

        d = self.start_manager()
        self.stub_method(self.manager, 'closed', closed_handler)

        d.addCallback(defer.drop_param, self.send_announce, self.manager)
        d.addCallback(defer.drop_param, self._consume_all)

        def put_bids(results):
            cb = self.cb_after(None, obj=self.manager, method='closed')
            self._put_bids(results, (3, 2, 1, ))
            return cb

        d.addCallback(put_bids)
        d.addCallback(lambda _: self.assert_queue_empty(self.queues[0]))
        d.addCallback(lambda _: self.queues[1].get())
        d.addCallback(self.assertIsInstance, message.Rejection)
        d.addCallback(lambda _: self.queues[2].get())
        d.addCallback(self.assertIsInstance, message.Rejection)

        def asserts_on_manager(_):
            self.assertEqual(3, len(self.medium.contractors))
            self.assertEqual(2, len(self.medium.contractors.with_state(\
                        ContractorState.rejected)))
            self.assertEqual(1, len(self.medium.contractors.with_state(\
                        ContractorState.elected)))

        d.addCallback(asserts_on_manager)
        d.addCallback(self.assertState,
                      contracts.ContractState.terminated)

        return d

    def testRefusingContractors(self):
        d = self.start_manager()

        closed = self.medium.notify_finish()
        self.assertFailure(closed, protocols.ProtocolFailed)

        d.addCallback(defer.drop_param, self.send_announce, self.manager)
        d.addCallback(defer.drop_param, self._consume_all)
        # None stands for Refusal
        d.addCallback(self._put_bids, ("refuse", "refuse", "refuse", ))
        d.addCallback(lambda _: closed)

        def asserts_on_manager(_):
            self.assertEqual(contracts.ContractState.expired,
                             self.medium.state)
            self.assertEqual(3, len(self.medium.contractors))
            for contractor in self.medium.contractors.values():
                self.assertEqual(ContractorState.refused, contractor.state)

            return self.manager

        d.addCallback(asserts_on_manager)
        d.addCallback(self.assertCalled, 'bid', times=0)
        d.addCallback(self.assertCalled, 'closed', times=0)
        d.addCallback(self.assertCalled, 'expired', times=1, params=[])

        d.addCallback(self.assertState, contracts.ContractState.expired)

        return d

    def testTimeoutAfterGrant(self):

        @replay.immutable
        def bid_handler(s, state, bid):
            state.medium.grant((bid, message.Grant(), ))

        d = self.start_manager()
        self.stub_method(self.manager, 'bid', bid_handler)

        d.addCallback(defer.drop_param, self.send_announce, self.manager)
        d.addCallback(defer.drop_param, self._consume_all)
        # None stands for Refusal
        d.addCallback(self._put_bids, (1, 2, 3, ))
        d.addCallback(self._wait_for_finish)
        d.addCallback(self.assertState, contracts.ContractState.aborted)
        d.addCallback(lambda _: self.manager)
        d.addCallback(self.assertCalled, 'aborted', params=[])

        return d

    def testRecvCancellation(self):

        @replay.immutable
        def closed_handler(s, state):
            s.log('Contracts closed, granting everybody')
            params = [(x.bid, message.Grant(), )
                      for x in state.medium.contractors.values()]
            state.medium.grant(params)

        d = self.start_manager()
        self.stub_method(self.manager, 'closed', closed_handler)

        d.addCallback(defer.drop_param, self.send_announce, self.manager)
        d.addCallback(defer.drop_param, self._consume_all)
        d.addCallback(self._put_bids, (3, 2, 1, ))
        d.addCallback(lambda _: self.queues[2].get()) #just swallow
        d.addCallback(lambda _: self.queues[0].get())

        def complete_one(grant):
            msg = message.FinalReport()
            endpoint = self.recipients[0]
            return self.reply(msg, endpoint, grant)

        d.addCallback(complete_one)

        def asserts_on_manager(_):
            self.assertEqual(1, len(
                self.medium.contractors.with_state(ContractorState.completed)))
            self.assertEqual(2, len(
                self.medium.contractors.with_state(ContractorState.granted)))

        d.addCallback(lambda _: self.queues[1].get())

        def cancel_one(grant):
            msg = message.Cancellation(reason='Ad majorem dei gloriam!')
            endpoint = self.recipients[1]
            return self.reply(msg, endpoint, grant)

        d.addCallback(cancel_one)

        d.addCallback(lambda _: self.queues[0].get())
        d.addCallback(self.assertIsInstance, message.Cancellation)
        d.addCallback(lambda _: self.queues[2].get())
        d.addCallback(self.assertIsInstance, message.Cancellation)

        def asserts_on_manager2(_):
            self.assertEqual(3, len(
                self.medium.contractors.with_state(ContractorState.cancelled)))
            self.assertCalled(self.manager, 'cancelled', params=[])

        d.addCallback(asserts_on_manager2)
        d.addCallback(self._wait_for_finish)
        d.addCallback(self.assertState,
                      contracts.ContractState.cancelled)

        return d

    def testContactorsFinishAckSent(self):

        @replay.immutable
        def closed_handler(s, state):
            s.log('Contracts closed, granting everybody')
            params = map(lambda x: (x.bid, message.Grant(), ),
                         state.medium.contractors.values())
            state.medium.grant(params)

        d = self.start_manager()
        self.stub_method(self.manager, 'closed', closed_handler)

        d.addCallback(defer.drop_param, self.send_announce, self.manager)
        d.addCallback(defer.drop_param, self._consume_all)
        d.addCallback(self._put_bids, (3, 2, 1, ))
        d.addCallback(self._consume_all)

        def finish_all(results):
            for (called, grant), recipient in zip(results, self.recipients):
                msg = message.FinalReport()
                self.reply(msg, recipient, grant)

        d.addCallback(finish_all)

        d.addCallback(self._consume_all)

        def assert_acked(results):
            for called, msg in results:
                self.assertIsInstance(msg, message.Acknowledgement)

        d.addCallback(assert_acked)

        d.addCallback(lambda _: self.manager)
        d.addCallback(self.assertCalled, 'completed', params=[list])
        d.addCallback(self.assertState,
                      contracts.ContractState.completed)

        return d

    @defer.inlineCallbacks
    def testCountingExpectedBids(self):
        yield self.start_manager()

        self.assertEqual(len(self.recipients),
            self.manager._get_medium()._count_expected_bids(self.recipients))
        broadcast = recipient.Broadcast('some protocol')
        self.assertEqual(None,
               self.manager._get_medium()._count_expected_bids(broadcast))
        self.assertEqual(None,
               self.manager._get_medium()._count_expected_bids(
                             self.recipients + [broadcast]))
        yield self._terminate_manager()

    def _terminate_manager(self):
        self.manager._get_medium().cleanup()

    def _wait_for_finish(self, _, failed=True):
        d = self.medium.notify_finish()
        if failed:
            self.assertFailure(d, protocols.ProtocolFailed)
        return d

    def testGettingAllBidsGetsToClosed(self):
        d = self.start_manager()

        closed = self.cb_after(None, self.medium, '_close_announce_period')

        d.addCallback(defer.drop_param, self.send_announce, self.manager)
        d.addCallback(defer.drop_param, self._consume_all)
        d.addCallback(self._put_bids, (1, 1, 1, ))
        d.addCallback(lambda _: closed)

        def asserts_on_manager(_):
            self.assertEqual(3, self.medium.expected_bids)
            self.assertEqual(contracts.ContractState.closed, self.medium.state)
            self.assertEqual(3, len(self.medium.contractors))

            return self.manager

        d.addCallback(asserts_on_manager)
        d.addCallback(self.assertCalled, 'bid', times=3)

        d.addCallback(lambda _: self._terminate_manager())
        d.addCallback(self.assertState, contracts.ContractState.closed)

        return d


@common.attr(timescale=0.05)
class TestContractor(common.TestCase, common.AgencyTestHelper):

    protocol_type = 'Contract'
    protocol_id = 'dummy-contract'

    timeout = 3

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        yield common.AgencyTestHelper.setUp(self)
        desc = yield self.doc_factory(descriptor.Descriptor)
        self.agent = yield self.agency.start_agent(desc)
        self.agent.register_interest(DummyContractor)

        self.contractor = None
        self.guid = None
        self.medium = None
        self.endpoint, self.queue = self.setup_endpoint()

    def tearDown(self):
        if self.medium:
            self.medium.cleanup()

    @defer.inlineCallbacks
    def testRecivingAnnouncement(self):
        yield self.recv_announce()

        self._get_contractor()
        d = self.medium.notify_finish()
        self.assertFailure(d, protocols.ProtocolFailed)
        yield d

        self.assertIsInstance(self.contractor, DummyContractor)
        self.assertCalled(self.contractor, 'announced', times=1)
        args = self.contractor.find_calls('announced')[0].args
        self.assertEqual(1, len(args))
        self.assertEqual(contracts.ContractState.closed,
                         self.medium.state)

    @common.attr(timescale=0.05)
    @defer.inlineCallbacks
    def testRecivingAnnouncementTwoTimes(self):
        '''
        This test checks that mechanics of storing traversal ids works
        correctly. Second announcement with same traversal id
        should be ignored.
        '''

        def count(num):
            return num == self._get_number_of_protocols()

        def check_protocols(num):
            return self.wait_for(count, 1, freq=0.05, kwargs={'num': num})

        # First
        yield self.recv_announce(time.future(3), traversal_id='first')
        yield check_protocols(1)
        # Expire first
        yield common.delay(None, 1)
        yield self._expire_contractor()
        yield check_protocols(0)

        # Duplicated
        yield self.recv_announce(time.future(1), traversal_id='first')
        self.assertEqual(0, self._get_number_of_protocols())
        yield common.delay(None, 2)

        yield self.recv_announce(time.future(3), traversal_id='other')
        yield check_protocols(1)
        yield common.delay(None, 1)
        yield self._expire_contractor()
        yield check_protocols(0)

        # now receive expired message
        yield self.recv_announce(1, traversal_id='first')
        self.assertEqual(0, self._get_number_of_protocols())
        yield check_protocols(0)

        yield self.recv_announce(time.future(10), traversal_id='first')
        yield check_protocols(1)
        yield common.delay(None, 1)
        yield self._expire_contractor()
        yield check_protocols(0)

    def _expire_contractor(self):
        c = first(x for x in self.agent._protocols.itervalues()
                  if isinstance(x, AgencyContractor))
        c.cleanup()

    def _get_number_of_protocols(self):
        return len([x for x in self.agent._protocols.itervalues()
                    if isinstance(x, AgencyContractor)])

    @defer.inlineCallbacks
    def testAnnounceExpiration(self):
        yield self.recv_announce()
        self._get_contractor()
        d = self.medium.notify_finish()
        self.assertFailure(d, protocols.ProtocolFailed)
        yield d
        self.assertCalled(self.contractor, 'announce_expired')
        self.assertState(None, contracts.ContractState.closed)

    def testPuttingBid(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.send_bid)

        def asserts(contractor):
            self.assertEqual(contracts.ContractState.bid,
                             contractor._get_medium().state)

        d.addCallback(asserts)
        d.addCallback(self.queue.get)

        def asserts_on_bid(msg):
            self.assertEqual(message.Bid, msg.__class__)
            bid = self.contractor._get_medium().own_bid
            reply_to = msg.reply_to
            msg.reply_to = None # Set by the backend
            self.assertEqual(type(bid), type(msg))
            self.assertEqual(msg.message_id, msg.message_id)
            medium = self.agent
            self.assertEqual(medium.get_agent_id(), reply_to.key)
            self.assertEqual(medium.get_shard_id(), reply_to.route)

        d.addCallback(asserts_on_bid)

        return d

    def testHandingOverTheBid(self):
        wait = self.cb_after(None, self.agent, 'unregister_protocol')

        d = self.recv_announce()
        d.addCallback(self._get_contractor)

        def send_delegated_bid(contractor):
            msg = message.Bid()
            msg.reply_to = self.endpoint
            msg.expiration_time = time.future(10)
            msg.protocol_type = self.protocol_type
            msg.protocol_id = self.protocol_id
            msg.message_id = str(uuid.uuid1())

            contractor._get_medium().handover(msg)
            return contractor

        d.addCallback(send_delegated_bid)

        d.addCallback(self.queue.get)

        def asserts_on_bid(msg):
            self.assertEqual(message.Bid, msg.__class__)
            a = self.contractor._get_medium().bid
            b = msg
            self.assertEqual(type(a), type(b))
            self.assertEqual(a.message_id, msg.message_id)
            self.assertEqual(self.endpoint, msg.reply_to)

        d.addCallback(asserts_on_bid)
        d.addCallback(lambda _: wait)
        d.addCallback(self.assertState,
                      contracts.ContractState.delegated)

        return d

    def testPuttingBidAndReachingTimeout(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.send_bid)
        d.addCallback(defer.bridge_param, self._wait_for_expiration)
        d.addCallback(self.assertCalled, 'bid_expired')
        d.addCallback(self.assertState, contracts.ContractState.expired)
        return d

    def testRefusing(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.send_refusal)

        d.addCallback(self.assertState, contracts.ContractState.refused)
        d.addCallback(self.queue.get)

        def asserts_on_refusal(msg):
            self.assertEqual(message.Refusal, msg.__class__)
            self.assertEqual(self.contractor._get_medium().guid,
                             msg.sender_id)

        d.addCallback(asserts_on_refusal)

        return d

    def testCorrectGrant(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.send_bid, 1)
        d.addCallback(self.recv_grant)

        def asserts(_):
            self.assertEqual(contracts.ContractState.granted,\
                                 self.medium.state)
            self.assertCalled(self.contractor, 'granted')
            call = self.contractor.find_calls('granted')[0]
            self.assertEqual(1, len(call.args))
            self.assertEqual(message.Grant, call.args[0].__class__)

        d.addCallback(asserts)

        return d

    def testBidRejected(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.send_bid)
        d.addCallback(self.recv_rejection)

        d.addCallback(self.assertCalled, 'rejected',
                      params=[message.Rejection])
        d.addCallback(self.assertState,
                      contracts.ContractState.rejected)

        return d

    def testCancelingGrant(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.send_bid)
        d.addCallback(self.recv_grant)
        d.addCallback(self.send_cancel)

        d.addCallback(self.assertState,
                      contracts.ContractState.defected)

        return d

    def testCancellingByManager(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.send_bid)
        d.addCallback(self.recv_grant)
        d.addCallback(self.recv_cancel)

        d.addCallback(self.assertCalled, 'cancelled',
                      params=[message.Cancellation])
        d.addCallback(self.assertState,
                      contracts.ContractState.cancelled)

        return d

    def testSendingReportThanExpiring(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.send_bid)
        d.addCallback(self.recv_grant)
        d.addCallback(self.send_final_report)

        def asserts(contractor):
            self.assertEqual(contracts.ContractState.completed,
                             contractor._get_medium().state)

        d.addCallback(asserts)
        d.addCallback(defer.bridge_param, self._wait_for_expiration)
        d.addCallback(self.assertState, contracts.ContractState.aborted)
        d.addCallback(self.assertCalled, 'aborted')

        return d

    def testSendingReportAndReceivingCancellation(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.send_bid)
        d.addCallback(self.recv_grant)
        d.addCallback(self.send_final_report)
        d.addCallback(self.recv_cancel)

        d.addCallback(self.assertCalled, 'aborted',
                      params=[])
        d.addCallback(self.assertState,
                      contracts.ContractState.aborted)

        return d

    def testCompletedAndAcked(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.send_bid)
        d.addCallback(self.recv_grant)
        d.addCallback(self.send_final_report)
        d.addCallback(self.recv_ack)

        d.addCallback(self.assertCalled, 'acknowledged',
                      params=[message.Acknowledgement])
        d.addCallback(self.assertState,
                      contracts.ContractState.acknowledged)

        return d

    def testReceivingFromIncorrectState(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(self.recv_grant)
        # this will be ignored, we follow the path to expiration
        d.addCallback(defer.bridge_param, self._wait_for_expiration)
        d.addCallback(self.assertCalled, 'announce_expired')
        d.addCallback(self.assertState, contracts.ContractState.closed)
        return d

    def testReceivingUnknownMessage(self):
        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(lambda contractor:
                 message.ContractMessage(receiver_id
                                         =contractor._get_medium().guid))
        d.addCallback(self.recv_msg)
        # this will be ignored, we follow the path to expiration

        d.addCallback(lambda _: self.contractor)
        d.addCallback(defer.bridge_param, self._wait_for_expiration)
        d.addCallback(self.assertCalled, 'announce_expired')
        d.addCallback(self.assertState, contracts.ContractState.closed)
        return d

    def testSendingMessageFromIncorrectState(self):

        @replay.immutable
        def custom_handler(s, state, msg):
            s.log("Sending refusal from incorrect state")
            msg = message.Refusal()
            msg.guid = state.medium.guid
            state.medium.refuse(msg)

        d = self.recv_announce()
        d.addCallback(self._get_contractor)
        d.addCallback(lambda contractor:
            contractor._get_medium().wait_for_state(
                contracts.ContractState.announced))
        d.addCallback(self._get_contractor)
        d.addCallback(self.send_bid)
        d.addCallback(self.stub_method, 'granted', custom_handler)
        d.addCallback(self.recv_grant)

        d.addCallback(self.assertState, contracts.ContractState.granted)

        return d

    def assertState(self, _, state):
        self.assertEqual(state, self.medium.state)
        return self.contractor

    def _get_contractor(self, *_):
        self.medium = first(x for x in self.agent._protocols.itervalues()
                            if isinstance(x, AgencyContractor))
        if self.medium is None:
            self.fail('Contractor not found')
        self.contractor = self.medium.get_agent_side()
        self.remote_id = self.medium.guid
        return self.contractor

    def _wait_for_expiration(self):
        d = self.medium.notify_finish()
        self.assertFailure(d, protocols.ProtocolFailed)
        return d
