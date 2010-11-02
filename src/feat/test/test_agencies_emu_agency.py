# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid

from zope.interface import classProvides
from twisted.internet import reactor, defer

from feat.agencies.emu import agency
from feat.agents import agent, descriptor, requester, message, replier
from feat.interface import recipient
from feat.interface.requester import IRequesterFactory
from feat.interface.replier import IReplierFactory


from . import common


#from feat.common import log


class DummyRequester(requester.BaseRequester):
    classProvides(IRequesterFactory)

    protocol_id = 'dummy-request'
    timeout = 2

    def __init__(self, agent, medium, argument):
        requester.BaseRequester.__init__(self, agent, medium, argument)
        self.payload = argument
        self.got_response = False

    def initiate(self):
        msg = message.RequestMessage()
        msg.payload = self.payload
        self.medium.request(msg)

    def got_reply(self, message):
        self.got_response = True
        self.medium.terminate()


class DummyReplier(replier.BaseReplier):
    classProvides(IReplierFactory)
    
    protocol_id = 'dummy-request'
    
    def requested(self, request):
        self.medium.reply(message.ResponseMessage())
        self.medium.terminate()


class TestAgencyAgent(common.TestCase):

    timeout = 3

    def setUp(self):
        self.agency = agency.Agency()
        desc = descriptor.Descriptor()
        self.agent = self.agency.start_agent(agent.BaseAgent, desc)

    def testJoinShard(self):
        self.assertEqual(1, len(self.agency._shards))
        self.assertEqual('lobby', self.agency._shards.keys()[0])
        self.assertEqual(1, len(self.agency._shards['lobby']))

        self.agent.leaveShard()
        self.assertEqual(1, len(self.agency._shards))
        self.assertEqual(0, len(self.agency._shards['lobby']))

    def testRequester(self):
        recipients = recipient.Agent('some_agent', 'lobby')
        d = self.agency.cb_on_msg('lobby', 'some_agent')
        payload = 5
        self.requester =\
            self.agent.initiate_protocol(DummyRequester, recipients, payload)

        def assertsOnMessage(message):
            self.assertEqual(self.agent.descriptor.shard, \
                             message.reply_to_shard)
            self.assertEqual(self.agent.descriptor.uuid, \
                             message.reply_to_key)
            self.assertEqual('Request', message.protocol_type)
            self.assertEqual('dummy-request', message.protocol_id)
            self.assertEqual(payload, message.payload)

            session_id = message.session_id
            self.assertEqual(session_id, str(session_id))
            return session_id

        d.addCallback(assertsOnMessage)

        def assertsOnAgency(session_id):
            self.log('%r', self.agent._listeners.keys())
            self.assertTrue(session_id in self.agent._listeners.keys())
            listener = self.agent._listeners[session_id]
            self.assertEqual('AgencyRequester', listener.__class__.__name__)
            return session_id

        d.addCallback(assertsOnAgency)

        def mimicReceivingResponse(session_id):
            response = message.ResponseMessage()
            response.session_id = session_id
            key, shard = self.agent.descriptor.uuid, self.agent.descriptor.shard
            self.agent._messaging.publish(key, shard, response)
            return session_id

        d.addCallback(mimicReceivingResponse)
        d.addCallback(self.cb_after, \
                      obj=self.agent, method='unregister_listener')

        def assertGotResponseAndTerminated(session_id):
            self.assertFalse(session_id in self.agent._listeners.keys())
            self.assertTrue(self.requester.got_response)

        d.addCallback(assertGotResponseAndTerminated)

        return d


    def testRequestTimeout(self):
        self.agency.time_scale = 0.01

        recipients = recipient.Agent('some_agent', 'lobby')
        d = self.agency.cb_on_msg('lobby', 'some_agent')
        payload = 5
        self.requester =\
                self.agent.initiate_protocol(DummyRequester, recipients, payload)

        d.addCallback(self.cb_after, obj=self.agent,
                      method='unregister_listener')

        def assertTerminatedWithNoResponse(_):
            session_id = self.requester.medium.session_id
            self.assertFalse(session_id in self.agent._listeners.keys())
            self.assertFalse(self.requester.got_response)

        d.addCallback(assertTerminatedWithNoResponse)

        return d

    def testRegisteringReplier(self):
        self.agent.register_interest(DummyReplier)

        self.assertTrue('Request' in self.agent._interests)
        self.assertTrue('dummy-request' in self.agent._interests['Request'])

    def testReplierReplies(self):
        self.agent.register_interest(DummyReplier)

        shard = self.agent.descriptor.shard
        key = self.agent.descriptor.uuid
        recp = recipient.Agent(str(uuid.uuid1()), shard)
        d = self.agency.cb_on_msg(shard, recp.key)
        req = self._build_req_msg(recp)
        self.agency._messaging.publish(key, recp.shard, req)

        def assert_on_msg(msg):
            self.assertEqual('dummy-request', msg.protocol_id)
            self.assertEqual(req.session_id, msg.session_id)
            
        d.addCallback(assert_on_msg)

        return d

    def _build_req_msg(self, recp):
        r = message.RequestMessage()
        r.message_id = str(uuid.uuid1())
        r.session_id = str(uuid.uuid1())
        r.protocol_type = 'Request'
        r.protocol_id = 'dummy-request'
        r.reply_to_key = recp.key
        r.reply_to_shard = recp.shard
        return r
