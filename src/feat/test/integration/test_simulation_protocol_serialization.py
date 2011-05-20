from twisted.internet import defer
from twisted.python import failure

from feat.test import common as test_common
from feat.test.integration import common

from feat.agents.base import agent, descriptor, replay, message
from feat.agents.base import requester, replier
from feat.common import fiber
from feat.common.text_helper import format_block

from feat.interface.recipient import *


@descriptor.register("protoser_test_agent")
class Descriptor(descriptor.Descriptor):
    pass


@agent.register("protoser_test_agent")
class Agent(agent.BaseAgent):

    @replay.entry_point
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        state.medium.register_interest(NormalReplier)
        state.medium.register_interest(SerializedReplier)
        state.medium.register_interest(PooledReplier)
        self.reset()

    @replay.immutable
    def get_count(self, state):
        return state.count

    @replay.immutable
    def get_curr(self, state):
        return state.curr

    @replay.immutable
    def get_max(self, state):
        return state.max

    @replay.mutable
    def reset(self, state):
        state.count = 0
        state.curr = 0
        state.max = 0

    @replay.mutable
    def protocol_started(self, state):
        state.curr += 1
        state.count += 1
        state.max = max(state.curr, state.max)

    @replay.mutable
    def protocol_terminated(self, state):
        state.curr -= 1
        assert state.curr >= 0


class NormalRequester(requester.BaseRequester):

    protocol_id = 'test_normal'
    timeout = 10

    @replay.entry_point
    def initiate(self, state):
        msg = message.RequestMessage()
        state.medium.request(msg)


class NormalReplier(replier.BaseReplier):

    protocol_id = 'test_normal'

    @replay.entry_point
    def requested(self, state, request):
        state.agent.protocol_started()
        f = fiber.Fiber()
        f.add_callback(test_common.delay, 1)
        f.add_callback(self.done)
        return f.succeed()

    @replay.mutable
    def done(self, state, _):
        response = message.ResponseMessage()
        state.medium.reply(response)
        state.agent.protocol_terminated()


class SerializedRequester(NormalRequester):

    protocol_id = 'test_serialized'


class SerializedReplier(NormalReplier):

    protocol_id = 'test_serialized'
    concurrency = 1


class PooledRequester(NormalRequester):

    protocol_id = 'test_pooled'


class PooledReplier(NormalReplier):

    protocol_id = 'test_pooled'
    concurrency = 3


@common.attr(timescale=0.05)
class ProtoSerializationTest(common.SimulationTest):

    timeout = 15

    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        desc1 = descriptor_factory('protoser_test_agent')
        desc2 = descriptor_factory('protoser_test_agent')
        medium1 = agency.start_agent(desc1)
        medium2 = agency.start_agent(desc2)
        agent1 = medium1.get_agent()
        agent2 = medium2.get_agent()
        """)
        return self.process(setup)

    @defer.inlineCallbacks
    def checkMultipleRequest(self, factory, count, max):
        medium1 = self.get_local('medium1')
        medium2 = self.get_local('medium2')
        agent1 = self.get_local('agent1')
        agent2 = self.get_local('agent2')
        recip2 = IRecipient(agent2)

        self.assertEqual(agent2.get_curr(), 0)
        self.assertEqual(agent2.get_max(), 0)
        self.assertEqual(agent2.get_count(), 0)

        for _ in range(count):
            agent1.initiate_protocol(factory, recip2)

        yield medium1.wait_for_listeners_finish()
        yield medium2.wait_for_listeners_finish()
        yield medium1.wait_for_listeners_finish()

        self.assertEqual(agent2.get_curr(), 0)
        self.assertEqual(agent2.get_max(), max)
        self.assertEqual(agent2.get_count(), count)

    def testValidateProlog(self):
        agents = [x for x in self.driver.iter_agents()]
        self.assertEqual(2, len(agents))

    def testNormalRequester(self):
        return self.checkMultipleRequest(NormalRequester, 8, 8)

    def testSerializedRequester(self):
        return self.checkMultipleRequest(SerializedRequester, 8, 1)

    def testPooledRequester(self):
        return self.checkMultipleRequest(PooledRequester, 8, 3)
