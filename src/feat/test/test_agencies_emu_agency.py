# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4


from feat.agencies.emu import agency
from feat.agents import agent, descriptor, requester, message
from feat.interface import recipient
from zope.interface import classProvides
from feat.interface.requester import IRequesterFactory
from feat.common import log

import uuid
import common
import twisted

class DummyRequest(requester.BaseRequester):
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
        d = self.agency.callbackOnMessage('lobby', 'some_agent')
        payload = 5
        self.requester =\
                self.agent.initiate_protocol(DummyRequest, recipients, payload)
        
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
            self.assertEqual('RequestResponder', listener.__class__.__name__)
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
        d = self.agency.callbackOnMessage('lobby', 'some_agent')
        payload = 5
        self.requester =\
                self.agent.initiate_protocol(DummyRequest, recipients, payload)

        d.addCallback(self.cb_after, obj=self.agent,
                      method='unregister_listener')

        def assertTerminatedWithNoResponse(_):
            session_id = self.requester.medium.session_id
            self.assertFalse(session_id in self.agent._listeners.keys())
            self.assertFalse(self.requester.got_response)

        d.addCallback(assertTerminatedWithNoResponse)
        
        return d
