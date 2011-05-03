# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer
from twisted.trial.unittest import FailTest

from feat import everything
from feat.common import delay
from feat.test.integration import common
from feat.common.text_helper import format_block
from feat.agents.base import agent, replay, descriptor
from feat.agents.common import host, rpc
from feat.interface.recipient import *
from feat.agents.base import resource
from feat.common import fiber
from feat.interface.generic import *


class Common(object):

    def _get_premodified(self, resource):
        '''
        Returns preallocated and modifications.
        '''
        totals = resource.get_totals()
        modifications = resource.get_modifications()
        result = dict()
        for name in totals:
            result[name] = 0
        for m in modifications:
            for r in modifications[m].delta:
                if modifications[m].delta[r] > 0:
                    result[r] += modifications[m].delta[r]
        return result


@descriptor.register('requesting_agent_mod')
class Descriptor(descriptor.Descriptor):
    pass


@agent.register('requesting_agent_mod')
class RequestingAgent(agent.BaseAgent, rpc.AgentMixin):

    @replay.mutable
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        rpc.AgentMixin.initiate(self)


class RemotePremodifyTest(common.SimulationTest, Common):

    @defer.inlineCallbacks
    def prolog(self):
        delay.time_scale = 1
        setup = format_block("""
        agency = spawn_agency()

        host_desc = descriptor_factory('host_agent')
        req_desc = descriptor_factory('requesting_agent_mod')

        host_medium = agency.start_agent(host_desc, hostdef=hostdef, \
        run_startup=False)
        host_agent = host_medium.get_agent()

        host_agent.start_agent(req_desc)
        """)

        hostdef = host.HostDef()
        hostdef.resources = {"a": 5, "epu": 5}
        self.set_local("hostdef", hostdef)

        yield self.process(setup)
        self.host_agent = self.get_local('host_agent')

        self.req_agent = self.driver.find_agent(
            self.get_local('req_desc')).get_agent()

    def testValidateProlog(self):
        agents = [x for x in self.driver.iter_agents()]
        self.assertEqual(2, len(agents))

    @defer.inlineCallbacks
    def testCallRemotePremodify(self):
        allocation = yield self.host_agent.allocate_resource(a=1)
        recp = IRecipient(self.host_agent)

        change = yield self.req_agent.call_remote(recp,
                "premodify_allocation", allocation_id=allocation.id, a=1)

        self._assert_allocated(self.host_agent, "a", 2)

    @defer.inlineCallbacks
    def testPartnerPremodifyApply(self):
        allocation = yield self.host_agent.allocate_resource(a=1)
        recp = IRecipient(self.host_agent)

        modification = yield self.req_agent.call_remote(recp,
                    "premodify_allocation", allocation_id=allocation.id, a=1)

        self._assert_allocated(self.host_agent, "a", 2)
        yield self.req_agent.call_remote(recp, "apply_modification",
                        modification.id)
        self._assert_allocated(self.host_agent, "a", 2)

    @defer.inlineCallbacks
    def testPartnerPremodifyUnknownid(self):
        allocation = yield self.host_agent.allocate_resource(a=1)
        recp = IRecipient(self.host_agent)

        modification = yield self.req_agent.call_remote(recp,
                    "premodify_allocation", allocation_id=allocation.id, a=1)

        d = defer.succeed(None)
        d = self.assertAsyncFailure(d, (resource.AllocationNotFound, ),
                fiber.maybe_fiber, self.req_agent.call_remote, recp,
                "premodify_allocation", allocation_id=10, a=1)
        yield d

    @defer.inlineCallbacks
    def testPartnerPremodifyTimeout(self):
        allocation = yield self.host_agent.allocate_resource(a=1)
        recp = IRecipient(self.host_agent)

        modification = yield self.req_agent.call_remote(recp,
                    "premodify_allocation", allocation_id=allocation.id, a=1)

        def check():
            return self._is_allocated(self.host_agent, "a", 1)

        yield self.wait_for(check, 40, freq=4)

    def _assert_allocated(self, agent, name, value):
        _, allocated = agent.list_resource()
        self.assertEqual(value, allocated.get(name))

    def _is_allocated(self, agent, name, value):
        _, allocated = agent.list_resource()
        return value == allocated.get(name)
