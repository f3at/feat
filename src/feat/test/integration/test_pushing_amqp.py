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
from feat.agencies import message
from feat.test.integration import common
from feat.process import rabbitmq
from feat.process.base import DependencyError
from feat.agents.base import agent, descriptor, dependency, replay
from feat.agents.base.amqp.interface import *
from feat.interface.agency import ExecMode
from feat.common import fiber, manhole, defer, first
from feat.common.text_helper import format_block
from feat.test.common import delay, StubAgent, attr
from feat.agencies.messaging import net
from feat.agents.application import feat

from twisted.trial.unittest import SkipTest


@feat.register_descriptor('test-agent')
class Descriptor(descriptor.Descriptor):
    pass


@feat.register_agent('test-agent')
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
        self.assert_not_skipped()
        # run rabbitmq
        yield self.run_rabbit()

        # get connection faking the web team listening
        self.server = net.RabbitMQ('127.0.0.1',
                                   self.rabbit.get_config()['port'])
        yield self.server.connect()
        self.web = StubAgent()
        self.connection = self.server.new_channel(self.web,
                                                  self.web.get_agent_id())
        yield self.connection.initiate()
        pb = self.connection.bind('exchange', self.web.get_agent_id())
        yield pb.wait_created()

        # setup our agent
        yield common.SimulationTest.setUp(self)

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        spawn_agency(start_host=False, \
                     'feat.agents.base.amqp.interface.IAMQPClientFactory')
        agency = _
        descriptor_factory('test-agent')
        agency.start_agent(_, host='127.0.0.1', port=%(port)s, \
                           exchange=%(exchange)s, \
                           exchange_type=%(type)s)
        """) % dict(port=self.rabbit.get_config()['port'],
                    exchange="'exchange'", type="'direct'")
        yield self.process(setup)
        self.agent = first(self.driver.iter_agents('test-agent'))

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.agent.terminate()
        yield self.wait_for_idle(80)
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
        self.agent = first(self.driver.iter_agents('test-agent')).get_agent()

    @defer.inlineCallbacks
    def testWebGetsMessage(self):
        yield self.agent.push_msg(message.BaseMessage(),
                                              'key')
        labour = self.agent.get_labour()
        self.assertEqual(1, len(labour.messages))
        self.assertTrue('key' in labour.messages)

        self.assertIsInstance(labour.messages['key'][0],
                              message.BaseMessage)
