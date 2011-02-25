from feat.agents.base import (testsuite, agent, dependency, descriptor, )


class TestDependency(testsuite.TestCase):

    def setUp(self):
        testsuite.TestCase.setUp(self)
        instance = self.ball.generate_agent(AgentWithDependency)
        # instance.state.resources = self.ball.generate_resources(instance)
        # instance.state.partners = self.ball.generate_partners(instance)
        self.agent = self.ball.load(instance)

    def testCallDependency(self):
        expected = [
            testsuite.side_effect('AgencyAgent.get_mode',
                                  dependency.Mode.test, ('something', ))]
        out, _ = self.ball.call(expected, self.agent.dependency, 'something')
        self.assertEqual(out, dependency.Mode.test)


        expected = [
            testsuite.side_effect('AgencyAgent.get_mode',
                                  dependency.Mode.production, ('something', ))]
        out, _ = self.ball.call(expected, self.agent.dependency, 'something')
        self.assertEqual(out, dependency.Mode.production)

    def testCallUnknown(self):
        expected = [
            testsuite.side_effect('AgencyAgent.get_mode',
                                  dependency.Mode.test, ('unknown', ))]
        self.assertRaises(dependency.UndefinedDependency, self.ball.call,
                          expected, self.agent.dependency, 'unknown')

    def testCallUndefined(self):
        expected = [
            testsuite.side_effect('AgencyAgent.get_mode',
                                  dependency.Mode.simulation, ('something', ))]
        self.assertRaises(dependency.UndefinedDependency, self.ball.call,
                          expected, self.agent.dependency, 'something')


def test():
    return dependency.Mode.test


def production():
    return dependency.Mode.production


@agent.register('blah_blah')
class AgentWithDependency(agent.BaseAgent):

    dependency.register('something', test, dependency.Mode.test)
    dependency.register('something', production, dependency.Mode.production)


@descriptor.register('blah_blah')
class Descriptor(descriptor.Descriptor):
    pass
