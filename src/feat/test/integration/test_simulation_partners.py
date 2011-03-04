# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat.common.text_helper import format_block
from feat.test.integration import common
from feat.agents.base import agent, descriptor, document


@document.register
class Descriptor(descriptor.Descriptor):

    document_type = 'base-agent'

agent.register('base-agent')(agent.BaseAgent)


class PartershipTest(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        # for this tests override DummyAgent with BaseAgent

        setup = format_block("""
        agency = spawn_agency()
        initiator = agency.start_agent(descriptor_factory('base-agent'))
        receiver = agency.start_agent(descriptor_factory('base-agent'))
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
        third = agency.start_agent(descriptor_factory('base-agent'))
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
