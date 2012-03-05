from feat.test.integration import common
from feat.common import defer, text_helper
from feat.agents.base import resource

from featchat.application import featchat

from featchat.agents.connection.interface import IChatServerFactory


featchat.load()


class ConnectionSimulation(common.SimulationTest):
    """
    This test case is done in a little nonstandard way in order to
    demonstrate some techniques. Instead of constructing the full cluster
    and asking Host Agents to run some agents, we run them directly from
    the agency. This makes tests much faster to run as we don't build the
    shards nor discover monitoring.

    To make it possible the descriptors of connection agents are created
    with some fields set. Normaly it is a job of Host Agent to set them up.
    - 'shard' determines to which exchange the agent binds to
    - 'instance_id' is a counter of incarnations of the agent
    - 'resource' represents allocation done by Host Agent to run us,
       Connection Agent extracts the port it should listen on from it.

    Secondly this testcase demonstrates how to obtain the reference to the
    dependency instance (the chat service component) to perfrom assertations
    upon them. To do this the proper driver.find_dependecy() calls are
    perfromed.
    """

    @defer.inlineCallbacks
    def prolog(self):
        n = 3
        for x in range(n):
            yield self._spawn_connection_agent()
        self.agents = [x.get_agent()
                       for x in self.driver.iter_agents('connection_agent')]
        self.servers = [self.driver.find_dependency(
            component=IChatServerFactory,
            index=x) for x in range(n)]
        self.assertEqual(n, len(self.servers))
        self.assertEqual(n, self.count_agents('connection_agent'))

    @defer.inlineCallbacks
    def testDispatchingMessages(self):
        # checks that the messages are properly dispatched with notifications
        first = 'from first server'
        second = 'from second server'
        self.servers[0].publish_message(first)
        self.servers[1].publish_message(second)
        yield self.wait_for_idle(10)
        self.assertEqual([second], self.servers[0].get_messages())
        self.assertEqual([first], self.servers[1].get_messages())
        self.assertEqual([first, second], self.servers[2].get_messages())

    @defer.inlineCallbacks
    def _spawn_connection_agent(self):
        from featchat.agents.common import connection
        desc = connection.Descriptor(
            name='chatroom',
            shard='some shard',
            resources=dict(chat=resource.AllocatedRange([1000])),
            instance_id=1)
        yield self.driver.save_document(desc)
        self.set_local('desc', desc)
        script = text_helper.format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        agency.start_agent(desc)
        wait_for_idle()
        """)
        yield self.process(script)
