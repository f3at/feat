from feat.test.integration import common
from feat.process import rabbitmq
from feat.process.base import DependencyError
from feat.agents.base import agent, descriptor, dependency, replay, message
from feat.agents.base.amqp.interface import *
from feat.interface.agency import ExecMode
from feat.common import fiber, manhole, defer
from feat.common.text_helper import format_block
from feat.test.common import delay, StubAgent, attr
from feat.agencies.net import messaging

from twisted.trial.unittest import SkipTest


@descriptor.register('test-agent')
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('test-agent')
class Agent(agent.BaseAgent):

    dependency.register(IAMQPClientFactory,
                        'feat.agents.base.amqp.production.AMQPClient',
                        ExecMode.production)
    dependency.register(IAMQPClientFactory,
                        'feat.agents.base.amqp.simulation.AMQPClient',
                        ExecMode.test)

    @replay.mutable
    def initiate(self, state, host, port, exchange, exchange_type):
        state.connection = self.dependency(
            IAMQPClientFactory, self, exchange, port=port,
            exchange_type=exchange_type)
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, state.connection.connect)
        return f

    @manhole.expose()
    @replay.journaled
    def push_msg(self, state, msg, key):
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, state.connection.publish, msg, key)
        return f

    @replay.journaled
    def shutdown(self, state):
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, state.connection.disconnect)
        return f

    @replay.immutable
    def get_labour(self, state):
        return state.connection


@attr('slow')
class TestWithRabbit(common.SimulationTest):

    timeout = 20

    @defer.inlineCallbacks
    def setUp(self):
        # run rabbitmq
        yield self.run_rabbit()

        # get connection faking the web team listening
        self.server = messaging.Messaging('127.0.0.1',
                                          self.rabbit.get_config()['port'])
        self.web = StubAgent()
        self.connection = yield self.server.new_channel(self.web)
        pb = self.connection.bind(self.web.get_agent_id(), 'exchange')
        yield pb.wait_created()

        # setup our agent
        yield common.SimulationTest.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        spawn_agency('feat.agents.base.amqp.interface.IAMQPClientFactory')
        agency = _
        agency.disable_protocol('setup-monitoring', 'Task')
        descriptor_factory('test-agent')
        agency.start_agent(_, host='127.0.0.1', port=%(port)s, \
                           exchange=%(exchange)s, \
                           exchange_type=%(type)s)
        """) % dict(port=self.rabbit.get_config()['port'],
                    exchange="'exchange'", type="'direct'")
        yield self.process(setup)
        self.agent = list(self.driver.iter_agents())[0]

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.agent.terminate()
        yield self.wait_for_idle(10)
        yield self.server.disconnect()
        yield self.rabbit.terminate()
        yield common.SimulationTest.tearDown(self)

    @defer.inlineCallbacks
    def testWebGetsMessage(self):
        cb = self.cb_after(None, self.web, 'on_message')
        yield self.agent.get_agent().push_msg(message.BaseMessage(),
                                              self.web.get_agent_id())
        yield cb
        self.assertIsInstance(self.web.messages[0], message.BaseMessage)

    @defer.inlineCallbacks
    def run_rabbit(self):
        try:
            self.rabbit = rabbitmq.Process(self)
        except DependencyError as e:
            raise SkipTest(str(e))

        yield self.rabbit.restart()


class SimulationWithoutRabbit(common.SimulationTest):

    timeout = 20

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()
        agency.disable_protocol('setup-monitoring', 'Task')
        descriptor_factory('test-agent')
        agency.start_agent(_, host='127.0.0.1', port=%(port)s, \
                           exchange=%(exchange)s, \
                           exchange_type=%(type)s)
        """) % dict(port=1234,
                    exchange="'exchange'", type="'direct'")
        yield self.process(setup)
        self.agent = list(self.driver.iter_agents())[0]

    @defer.inlineCallbacks
    def testWebGetsMessage(self):
        yield self.agent.get_agent().push_msg(message.BaseMessage(),
                                              'key')
        labour = self.agent.get_agent().get_labour()
        self.assertEqual(1, len(labour.messages))
        self.assertTrue('key' in labour.messages)

        self.assertIsInstance(labour.messages['key'][0],
                              message.BaseMessage)
