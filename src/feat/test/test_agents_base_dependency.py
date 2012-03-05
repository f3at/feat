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
from zope.interface import directlyProvides, Interface

from feat.interface.agency import ExecMode
from feat.agents.base import testsuite, agent, dependency, descriptor
from feat.agents.application import feat
from feat.test import common


class TestDependency(testsuite.TestCase):

    def setUp(self):
        testsuite.TestCase.setUp(self)
        instance = self.ball.generate_agent(AgentWithDependency)
        self.agent = self.ball.load(instance)

    def testCallDependency(self):
        expected = [
            testsuite.side_effect('AgencyAgent.get_mode',
                                  ExecMode.test, (SomeInterface, ))]
        out, _ = self.ball.call(expected, self.agent.dependency, SomeInterface)
        self.assertEqual(out, ExecMode.test)


        expected = [
            testsuite.side_effect('AgencyAgent.get_mode',
                                  ExecMode.production, (SomeInterface, ))]
        out, _ = self.ball.call(expected, self.agent.dependency, SomeInterface)
        self.assertEqual(out, ExecMode.production)

    def testCallUnknown(self):
        expected = [
            testsuite.side_effect('AgencyAgent.get_mode',
                                  ExecMode.test, (UnknownInterface, ))]
        self.assertRaises(dependency.UndefinedDependency, self.ball.call,
                          expected, self.agent.dependency, UnknownInterface)

    def testCallUndefined(self):
        expected = [
            testsuite.side_effect('AgencyAgent.get_mode',
                                  ExecMode.simulation, (SomeInterface, ))]
        self.assertRaises(dependency.UndefinedDependency, self.ball.call,
                          expected, self.agent.dependency, SomeInterface)

    def testMixin(self):
        expected = [
            testsuite.side_effect('AgencyAgent.get_mode',
                                  ExecMode.test, (MixinInterface, ))]
        out, _ = self.ball.call(
            expected, self.agent.dependency, MixinInterface)
        self.assertEqual(out, ExecMode.test)


class TestProblemWithAnnotations(common.TestCase):

    def testDependenciesAreNotGlobal(self):
        self.assertNotIn(SomeInterface,
                         agent.BaseAgent._get_defined_components())
        self.assertIn(SomeInterface,
                      AgentWithDependency._get_defined_components())


class SomeInterface(Interface):

    def __call__():
        pass


class MixinInterface(Interface):

    def __call__():
        pass


class UnknownInterface(Interface):

    def __call__():
        pass


def test():
    return ExecMode.test
directlyProvides(test, (SomeInterface, MixinInterface, ))


def production():
    return ExecMode.production
directlyProvides(production, SomeInterface)


class AgentMixin(object):

    dependency.register(
        MixinInterface, 'feat.test.test_agents_base_dependency.test',
        ExecMode.test)


@feat.register_agent('blah_blah_blah')
class OtherAgent(agent.BaseAgent, AgentMixin):
    '''Important is not to move this definion below AgentWithDependency.
    This is here to reproduce the bug related to annotations and it depends
    on the order of class definition.
    '''


@feat.register_agent('blah_blah')
class AgentWithDependency(agent.BaseAgent, AgentMixin):

    dependency.register(
        SomeInterface, 'feat.test.test_agents_base_dependency.test',
        ExecMode.test)
    dependency.register(
        SomeInterface, 'feat.test.test_agents_base_dependency.production',
        ExecMode.production)


@feat.register_descriptor('blah_blah')
class Descriptor(descriptor.Descriptor):
    pass
