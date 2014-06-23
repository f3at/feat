import os
import tempfile

from feat.common import defer
from feat.test import common, dummies

from feat.agents.nagios import nagios_agent
from feat.agencies import recipient
from feat.agents.common import rpc


class NagiosAgentTest(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)

        self.medium = dummies.DummyMedium(self)
        self.agent = nagios_agent.NagiosAgent(self.medium)

    @defer.inlineCallbacks
    def testUpdateConfig(self):
        target = tempfile.mktemp('_nagios.cfg')
        target = os.path.abspath(target)
        self.addCleanup(os.unlink, target)

        update_command = 'cp %%(path)s %s' % (target, )
        yield self.agent.initiate(update_command=update_command)

        recp = recipient.Agent('key', 'shard')
        body = 'file body'
        self.agent._get_state().nagios_configs['key'] = body
        # simulate receiving the config, the update task should be triggered
        yield self.agent.config_changed(recp, body)
        self.assertEqual(['singleton-update-nagios'],
                         [x.factory.protocol_id
                          for x in self.medium.protocols])
        self.medium.reset()

        # now run the task itself
        task = nagios_agent.UpdateNagios(self.agent, self.medium)
        d = task.initiate(recp, update_command)

        def check():
            return len(self.medium.protocols) == 1
        yield self.wait_for(check, 5, freq=0.05)
        self.assertEqual(recp, self.medium.protocols[-1].args[0])
        self.assertEqual('push_notifications',
                         self.medium.protocols[-1].args[1])
        self.assertIsInstance(self.medium.protocols[-1].factory,
                              rpc.RPCRequesterFactory)

        self.medium.protocols[-1].deferred.callback(None)

        yield d
        self.assertTrue(os.path.exists(target))
        with open(target) as f:
            self.assertEqual(body, f.read())
        self.medium.reset()
