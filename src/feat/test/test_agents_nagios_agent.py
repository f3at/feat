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
    def testReceiveNewConfig(self):
        target = tempfile.mktemp('_nagios.cfg')
        target = os.path.abspath(target)
        self.addCleanup(os.unlink, target)

        yield self.agent.initiate(
            update_command='cp %%(path)s %s' % (target, ))


        recp = recipient.Agent('key', 'shard')
        body = 'file body'

        d = self.agent.config_changed(recp, body)

        def check():
            return len(self.medium.protocols) > 0
        yield self.wait_for(check, 5)
        self.assertEqual(recp, self.medium.protocols[0].args[0])
        self.assertEqual('push_notifications',
                         self.medium.protocols[0].args[1])
        self.assertIsInstance(self.medium.protocols[0].factory,
                              rpc.RPCRequesterFactory)

        self.medium.protocols[0].deferred.callback(None)

        yield d
        self.assertTrue(os.path.exists(target))
        with open(target) as f:
            self.assertEqual(body, f.read())
