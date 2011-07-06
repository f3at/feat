# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat import everything
from feat.common import serialization
from feat.test.integration import common
from feat.common.text_helper import format_block
from feat.agents.base import agent, replay, descriptor
from feat.common import fiber

from feat.interface.generic import *
from feat.interface.recipient import *


class U2(object):
    pass


@descriptor.register('sample_agent')
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('sample_agent')
class SampleAgent(agent.BaseAgent):

    @replay.mutable
    def initiate(self, state):
        agent.BaseAgent.initiate(self)

    @replay.mutable
    def crazy(self, state, arg):
        return arg
        #return fiber.fail(U2())


msg = "Replayability is skipped because there is no way that replay "\
      "will pass when passing an unserializable object."


@common.attr(timescale=0.1, skip_replayability=msg)
class UnserializableTest(common.SimulationTest):

    @defer.inlineCallbacks
    def prolog(self):
        setup = format_block("""
        agency = spawn_agency()

        d = descriptor_factory('sample_agent')
        m = agency.start_agent(d)
        a = m.get_agent()
        """)

        yield self.process(setup)
        yield self.wait_for_idle(10)

    @defer.inlineCallbacks
    def testReturnUnserializableObject(self):
        a = self.get_local("a")
        d = a.crazy(U2())
        self.assertFailure(d, TypeError)
        yield d
