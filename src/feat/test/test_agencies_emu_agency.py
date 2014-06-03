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
import time

from twisted.internet import defer
from zope.interface import implements

from feat.agents.base import descriptor, requester, replier, replay
from feat.agencies import message, retrying
from feat.interface.agency import ExecMode

from feat.database.interface import NotFoundError
from feat.interface.requests import RequestState
from feat.interface.protocols import ProtocolFailed, IInterest, InterestType

from feat.test import common, dummies #don't remove dummies, it defines adapter


class DummyRequester(requester.BaseRequester):

    protocol_id = 'dummy-request'
    timeout = 2

    @replay.entry_point
    def initiate(self, state, argument):
        state._got_response = False
        msg = message.RequestMessage()
        msg.payload = argument
        state.medium.request(msg)

    @replay.entry_point
    def got_reply(self, state, message):
        state._got_response = True
        return message.payload

    @replay.immutable
    def _get_medium(self, state):
        self.log(state)
        return state.medium

    @replay.immutable
    def got_response(self, state):
        return state._got_response


class DummyReplier(replier.BaseReplier):

    protocol_id = 'dummy-request'

    @replay.entry_point
    def requested(self, state, request):
        state.agent.got_payload = request.payload
        state.medium.reply(message.ResponseMessage(payload=request.payload))


class DummyInterest(object):

    implements(IInterest)

    def __init__(self):
        self.protocol_type = "Contract"
        self.protocol_id = "some-contract"
        self.interest_type = InterestType.public
        self.initiator = message.Announcement


class TestDependencies(common.TestCase, common.AgencyTestHelper):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        yield common.AgencyTestHelper.setUp(self)

    def testGettingModes(self):
        self.assertEqual(ExecMode.test, self.agency.get_mode('unknown'))
        self.agency.set_mode('something', ExecMode.production)
        self.assertEqual(ExecMode.production,
                         self.agency.get_mode('something'))
        self.agency._set_default_mode(ExecMode.production)
        self.assertEqual(ExecMode.production,
                         self.agency.get_mode('unknown'))


class TestAgencyAgent(common.TestCase, common.AgencyTestHelper):

    timeout = 3
    protocol_type = 'Request'
    protocol_id = 'dummy-request'

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        yield common.AgencyTestHelper.setUp(self)

        desc = yield self.doc_factory(descriptor.Descriptor)
        self.agent = yield self.agency.start_agent(desc)

        self.assertEqual(1, self.agent.get_descriptor().instance_id)

        self.endpoint, self.queue = self.setup_endpoint()

    def testJoinShard(self):
        messaging = self.agent._messaging
        self.assertTrue(len(messaging.get_bindings('lobby')) > 1)

        self.agent.leave_shard('lobby')
        self.assertEqual(0, len(messaging.get_bindings('lobby')))

    @defer.inlineCallbacks
    def testSwitchingShardRebinding(self):
        messaging = self.agent._messaging
        initial = len(messaging.get_bindings('lobby'))
        interest = DummyInterest()
        self.agent.register_interest(interest)
        self.assertEqual(initial + 1, len(messaging.get_bindings('lobby')))
        yield self.agent.leave_shard('lobby')
        self.assertEqual(0, len(messaging.get_bindings('lobby')))

        yield self.agent.join_shard('new shard')
        self.assertEqual(initial + 1,
                         len(messaging.get_bindings('new shard')))
        self.assertEqual(0, len(messaging.get_bindings('lobby')))

    @defer.inlineCallbacks
    def testUpdateDocument(self):
        desc = self.agent.get_descriptor()
        self.assertIsInstance(desc, descriptor.Descriptor)

        def update_fun(desc):
            desc.shard = 'changed'

        yield self.agent.update_descriptor(update_fun)
        self.assertEqual('changed', self.agent._descriptor.shard)

    def testRegisterTwice(self):
        self.assertTrue(self.agent.register_interest(DummyReplier))
        self.failIf(self.agent.register_interest(DummyReplier))

    def testRegisteringAndRevokeReplier(self):
        self.agent.register_interest(DummyReplier)

        self.assertTrue('Request' in self.agent._interests)
        self.assertTrue('dummy-request' in self.agent._interests['Request'])

        self.agent.revoke_interest(DummyReplier)
        self.assertFalse('dummy-request' in self.agent._interests['Request'])

        #calling once again nothing bad should happened
        req = self.agent.revoke_interest(DummyReplier)
        self.assertFalse(req)

    def tesGetingRequestWithoutInterest(self):
        '''Current implementation just ignores such events. Update this test
        in case we decide to do sth else'''
        key = (self.agent.get_descriptor()).doc_id
        msg = message.RequestMessage()
        return self.recv_msg(msg, self.endpoint, key)

    @defer.inlineCallbacks
    def testTerminatingTheAgent(self):
        # make him have running retrying request (covers all the hard cases)
        d = self.cb_after(None, self.agent, 'initiate_protocol')
        factory = retrying.RetryingProtocolFactory(DummyRequester)
        self.agent.initiate_protocol(factory, self.endpoint, None)
        yield d

        yield self.agent._terminate()

        self.assertCalled(self.agent.agent, 'shutdown')

        doc_id = self.agent._descriptor.doc_id
        d = self.agency._database.get_connection().get_document(doc_id)
        self.assertFailure(d, NotFoundError)
        yield d
        self.assertEqual(0, len(self.agency._agents))


@common.attr(timescale=0.05)
class TestRequests(common.TestCase, common.AgencyTestHelper):

    timeout = 3

    protocol_type = 'Request'
    protocol_id = 'dummy-request'

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        yield common.AgencyTestHelper.setUp(self)

        desc = yield self.doc_factory(descriptor.Descriptor)
        self.agent = yield self.agency.start_agent(desc)

        self.endpoint, self.queue = self.setup_endpoint()

    def testRequester(self):

        d = self.queue.get()
        payload = 5
        self.requester =\
            self.agent.initiate_protocol(DummyRequester,
                                         self.endpoint, payload)
        self.medium = self.requester._get_medium()
        self.finished = self.requester.notify_finish()
        self.assertIsInstance(self.finished, defer.Deferred)

        def assertsOnMessage(message):
            desc = self.agent.get_descriptor()
            self.assertEqual(desc.shard, \
                             message.reply_to.route)
            self.assertEqual(desc.doc_id, \
                             message.reply_to.key)
            self.assertEqual('Request', message.protocol_type)
            self.assertEqual('dummy-request', message.protocol_id)
            self.assertEqual(payload, message.payload)
            self.assertTrue(message.expiration_time is not None)

            guid = message.sender_id
            self.assertEqual(guid, str(guid))

            self.assertEqual(RequestState.requested, self.medium.state)
            return guid, message

        d.addCallback(assertsOnMessage)

        def assertsOnAgency((guid, msg, )):
            self.log('%r', self.agent._protocols.keys())
            self.assertTrue(guid in self.agent._protocols.keys())
            protocol = self.agent._protocols[guid]
            self.assertEqual('AgencyRequester', protocol.__class__.__name__)
            return guid, msg

        d.addCallback(assertsOnAgency)

        def mimicReceivingResponse((guid, msg, )):
            response = message.ResponseMessage()
            self.reply(response, self.endpoint, msg)

            return guid

        d.addCallback(mimicReceivingResponse)
        d.addCallback(lambda _: self.finished)

        def assertGotResponseAndTerminated(guid):
            self.assertFalse(guid in self.agent._protocols.keys())
            self.assertTrue(self.requester.got_response)

        d.addCallback(assertGotResponseAndTerminated)

        return d

    @common.attr(timeout=10)
    @defer.inlineCallbacks
    def testRequestTimeout(self):
        payload = 5
        self.requester =\
            yield self.agent.initiate_protocol(DummyRequester,
                                         self.endpoint, payload)
        self.medium = self.requester._get_medium()
        self.finished = self.requester.notify_finish()
        self.assertFailure(self.finished, ProtocolFailed)
        yield self.finished

        guid = self.medium.guid
        self.assertFalse(guid in self.agent._protocols.keys())
        self.assertFalse(self.requester.got_response())
        self.assertEqual(RequestState.closed, self.medium.state)

        msg = yield self.queue.get()
        self.assertIsInstance(msg, message.RequestMessage)

    def testReplierReplies(self):
        self.agent.register_interest(DummyReplier)

        key = (self.agent.get_descriptor()).doc_id

        req = self._build_req_msg(self.endpoint)
        d = self.recv_msg(req, self.endpoint, key)

        d.addCallback(lambda _: self.queue.get())

        def assert_on_msg(msg):
            self.assertEqual('dummy-request', msg.protocol_id)

        d.addCallback(assert_on_msg)

        return d

    def testNotProcessingExpiredRequests(self):
        self.agent.register_interest(DummyReplier)
        self.agent.agent.got_payload = False

        key = (self.agent.get_descriptor()).doc_id
        # define false sender, he will get the response later
        req = self._build_req_msg(self.endpoint)
        expiration_time = time.time() - 1
        d = self.recv_msg(req, self.endpoint, key, expiration_time)

        def asserts_after_procesing(return_value):
            self.log(return_value)
            self.assertFalse(return_value)
            self.assertEqual(False, self.agent.agent.got_payload)

        d.addCallback(asserts_after_procesing)

        return d

    @defer.inlineCallbacks
    def testTwoAgentsTalking(self):
        receiver = self.agent
        desc = yield self.doc_factory(descriptor.Descriptor)
        sender = yield self.agency.start_agent(desc)
        receiver.register_interest(DummyReplier)
        requester = sender.initiate_protocol(DummyRequester, receiver, 1)
        r = yield requester.notify_finish()
        self.assertEqual(1, r)
        self.assertTrue(requester.got_response)
        self.assertEqual(1, receiver.agent.got_payload)

    def _build_req_msg(self, recp):
        r = message.RequestMessage()
        r.guid = str(uuid.uuid1())
        r.traversal_id = str(uuid.uuid1())
        r.payload = 10
        return r
