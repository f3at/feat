from twisted.internet import defer
from twisted.python import failure

from feat.test.integration import common

from feat.agents.base import agent, descriptor, replay, recipient
from feat.agents.base import collector, poster
from feat.common.text_helper import format_block

from feat.interface.recipient import *
from feat.interface.protocols import *
from feat.interface.collector import *
from feat.interface.poster import *


@descriptor.register("poster_test_agent")
class PosterDescriptor(descriptor.Descriptor):
    pass


@agent.register("poster_test_agent")
class PosterAgent(agent.BaseAgent):

    @replay.entry_point
    def initiate(self, state, desc):
        agent.BaseAgent.initiate(self)
        recip = IRecipient(desc)
        state.poster = state.medium.initiate_protocol(DummyPoster, recip)
        return self.initiate_partners()

    @replay.immutable
    def post(self, state, *args, **kwargs):
        state.poster.notify(*args, **kwargs)


@descriptor.register("collector_test_agent")
class CollectorDescriptor(descriptor.Descriptor):
    pass


@agent.register("collector_test_agent")
class CollectorAgent(agent.BaseAgent):

    @replay.entry_point
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        state.medium.register_interest(DummyCollector)
        state.notifications = []
        return self.initiate_partners()

    @replay.immutable
    def get_notifications(self, state):
        return state.notifications

    @replay.mutable
    def add_notification(self, state, notif):
        state.notifications.append(notif)


class DummyPoster(poster.BasePoster):
    protocol_id = 'dummy-notification'

    def pack_payload(self, value):
        return value


class DummyCollector(collector.BaseCollector):

    interest_type = InterestType.public
    protocol_id = 'dummy-notification'

    @replay.immutable
    def notified(self, state, message):
        state.agent.add_notification(message.payload)


@common.attr(timescale=0.05)
class NotificationTest(common.SimulationTest):

    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        cdesc1 = descriptor_factory('collector_test_agent')
        cdesc2 = descriptor_factory('collector_test_agent')
        pdesc1 = descriptor_factory('poster_test_agent')
        pdesc2 = descriptor_factory('poster_test_agent')
        pdesc3 = descriptor_factory('poster_test_agent')
        cmedium1 = agency.start_agent(cdesc1)
        cmedium2 = agency.start_agent(cdesc2)
        pmedium1 = agency.start_agent(pdesc1, cdesc1)
        pmedium2 = agency.start_agent(pdesc2, cdesc2)
        pmedium3 = agency.start_agent(pdesc3, broadcast)
        collector1 = cmedium1.get_agent()
        collector2 = cmedium2.get_agent()
        poster1 = pmedium1.get_agent()
        poster2 = pmedium2.get_agent()
        poster3 = pmedium3.get_agent()
        """)

        recip = recipient.Broadcast('dummy-notification', 'lobby')
        self.set_local("broadcast", recip)

        return self.process(setup)

    def testValidateProlog(self):
        iter_agents = self.driver.iter_agents
        posters = [x for x in iter_agents("poster_test_agent")]
        collectors = [x for x in iter_agents("collector_test_agent")]
        self.assertEqual(3, len(posters))
        self.assertEqual(2, len(collectors))

    @defer.inlineCallbacks
    def testNotification(self):
        poster1 = self.get_local('poster1')
        poster2 = self.get_local('poster2')
        poster3 = self.get_local('poster3')
        collector1 = self.get_local('collector1')
        collector2 = self.get_local('collector2')

        self.assertEqual(len(collector1.get_notifications()), 0)
        self.assertEqual(len(collector2.get_notifications()), 0)

        poster1.post(1)
        poster2.post(2)
        poster3.post(3)
        poster1.post(4)
        poster2.post(5)
        poster3.post(6)

        check = lambda: len(collector1.get_notifications()) == 4 \
                    and len(collector2.get_notifications()) == 4

        yield self.wait_for(check, 10)

        self.assertEqual(collector1.get_notifications(), [1, 3, 4, 6])
        self.assertEqual(collector2.get_notifications(), [2, 3, 5, 6])
