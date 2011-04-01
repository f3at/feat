# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat.common.text_helper import format_block
from feat.test.integration import common
from feat.agents.base import (agent, descriptor, document, recipient,
                              partners, replay, resource, )
from feat.common import serialization, fiber


@serialization.register
class FailureOfPartner(Exception, serialization.Serializable):
    pass


@document.register
class Descriptor(descriptor.Descriptor):

    document_type = 'partner-agent'


class FailingPartner(partners.BasePartner):

    def initiate(self, agent):
        return fiber.fail(FailureOfPartner('test'))


class Partners(partners.Partners):

    partners.has_many('failers', 'partner-agent', FailingPartner, 'failer')


@agent.register('partner-agent')
class Agent(agent.BaseAgent):

    partners_class = Partners

    @replay.mutable
    def initiate(self, state):
        agent.BaseAgent.initiate(self)

        state.resources.define('foo', 2)


class PartnershipTest(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        # for this tests override DummyAgent with BaseAgent

        setup = format_block("""
        agency = spawn_agency()
        initiator = agency.start_agent(descriptor_factory('partner-agent'))
        receiver = agency.start_agent(descriptor_factory('partner-agent'))
        """)
        yield self.process(setup)
        self.receiver = self.get_local('receiver')
        self.initiator = self.get_local('initiator')
        self.agency = self.get_local('agency')

    def testValidateProlog(self):
        self.assertEqual(2, len(self.agency._agents))
        self.assertIsInstance(self.agency._agents[0].agent, agent.BaseAgent)
        self.assertIsInstance(self.agency._agents[1].agent, agent.BaseAgent)

    @defer.inlineCallbacks
    def testEstablishPartnership(self):
        yield self._establish_partnership()

        self.assertEqual(1, len(self.initiator.get_descriptor().partners))
        self.assertEqual(1, len(self.receiver.get_descriptor().partners))

    @defer.inlineCallbacks
    def testInitiatorTerminates(self):
        yield self._establish_partnership()

        yield self.initiator._terminate()
        yield self.receiver.wait_for_listeners_finish()

        self.assertEqual(1, len(self.agency._agents))
        self.assertEqual(0, len(self.receiver.get_descriptor().partners))

    @defer.inlineCallbacks
    def testReceiverTerminates(self):
        yield self._establish_partnership()

        yield self.receiver._terminate()
        yield self.initiator.wait_for_listeners_finish()

        self.assertEqual(1, len(self.agency._agents))
        self.assertEqual(0, len(self.initiator.get_descriptor().partners))

    @defer.inlineCallbacks
    def testThreeAgents(self):
        '''
        Three agents, all being partners. Than check the termination of
        two of them.
        '''
        yield self.process(format_block("""
        third = agency.start_agent(descriptor_factory('partner-agent'))
        """))

        agents = [self.initiator, self.receiver, self.get_local('third')]

        yield self._establish_partnership('initiator', 'receiver')
        self.assert_partners(agents, [1, 1, 0])
        yield self._establish_partnership('receiver', 'third')
        self.assert_partners(agents, [1, 2, 1])
        yield self._establish_partnership('third', 'initiator')
        self.assert_partners(agents, [2, 2, 2])

        yield self.initiator._terminate()
        yield agents[1].wait_for_listeners_finish()
        yield agents[2].wait_for_listeners_finish()

        self.assert_partners(agents, [2, 1, 1])

        yield self.receiver._terminate()
        yield agents[2].wait_for_listeners_finish()
        self.assert_partners(agents, [2, 1, 0])

    @defer.inlineCallbacks
    def testFailingPartner(self):
        d = self._failing_partnership(self.initiator, self.receiver)
        self.assertFailure(d, FailureOfPartner)
        yield d
        agents = [self.initiator, self.receiver]
        self.assert_partners(agents, [0, 0, 0])

    def testSubstitutePartner(self):
        '''
        Three agents, all being partners. Than check the termination of
        two of them.
        '''
        yield self.process(format_block("""
        third = agency.start_agent(descriptor_factory('base-agent'))
        """))

        agents = [self.initiator, self.receiver, self.get_local('third')]

        alloc1 = yield agents[2].get_agent().allocate_resource(foo=1)
        alloc2 = yield agents[2].get_agent().allocate_resource(foo=1)

        yield self._establish_partnership('initiator', 'receiver')
        self.assert_partners(agents, [1, 1, 0])
        yield self.initiator.get_agent().substitute_partner(
            recipient.IRecipient(self.receiver),
            recipient.IRecipient(agents[2]),
            alloc1.id)
        self.assert_partners(agents, [1, 1, 1])
        yield self.receiver.get_agent().substitute_partner(
            recipient.IRecipient(self.initiator),
            recipient.IRecipient(agents[2]),
            alloc2.id)
        self.assert_partners(agents, [1, 1, 2])

    @defer.inlineCallbacks
    def testFailingPartner(self):
        d = self._failing_partnership(self.initiator, self.receiver)
        self.assertFailure(d, FailureOfPartner)
        yield d
        agents = [self.initiator, self.receiver]
        self.assert_partners(agents, [0, 0, 0])

    @defer.inlineCallbacks
    def testEstablishPartnershipWithAllocations(self):
        i_alloc = yield self.initiator.get_agent().allocate_resource(foo=1)
        r_alloc = yield self.receiver.get_agent().allocate_resource(foo=1)
        yield self.initiator.get_agent().establish_partnership(
            recipient.IRecipient(self.receiver), i_alloc.id, r_alloc.id)

        agents = [self.initiator, self.receiver]
        self.assert_partners(agents, [1, 1])
        for medium in agents:
            agent = medium.get_agent()
            partner = agent.query_partners('all')[0]
            self.assertTrue(partner.allocation_id is not None)

    @defer.inlineCallbacks
    def testEstablishPartnershipWithPreAllocaton(self):
        i_alloc = yield self.initiator.get_agent().allocate_resource(foo=1)
        r_alloc = yield self.receiver.get_agent().preallocate_resource(foo=1)
        d = self.initiator.get_agent().establish_partnership(
            recipient.IRecipient(self.receiver), i_alloc.id, r_alloc.id)
        self.assertFailure(d, resource.AllocationNotFound)
        yield d

        agents = [self.initiator, self.receiver]
        self.assert_partners(agents, [0, 0])
        r_alloc = yield self.receiver.get_agent().release_resource(r_alloc.id)

    @defer.inlineCallbacks
    def testEstablishPartnershipWithUnknownAllocaton(self):
        i_alloc = yield self.initiator.get_agent().allocate_resource(foo=1)
        d = self.initiator.get_agent().establish_partnership(
            recipient.IRecipient(self.receiver), i_alloc.id, 2)
        self.assertFailure(d, resource.AllocationNotFound)
        yield d

        agents = [self.initiator, self.receiver]
        self.assert_partners(agents, [0, 0])

    def assert_partners(self, agents, expected):
        for agent, e in zip(agents, expected):
            self.assertEqual(e, len(agent.get_descriptor().partners))

    def _establish_partnership(self, initiator='initiator',
                               receiver='receiver'):
        script = format_block("""
        agent = %s.get_agent()
        agent.propose_to(%s)
        """ % (initiator, receiver, ))
        return self.process(script)

    def _failing_partnership(self, initiator, receiver):
        return initiator.get_agent().propose_to(
            recipient.IRecipient(receiver), partner_role='failer')
