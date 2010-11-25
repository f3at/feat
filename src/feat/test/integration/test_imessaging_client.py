# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import shutil
import os

from twisted.internet import reactor, defer
from twisted.trial.unittest import SkipTest

try:
    from feat.agencies.net import messaging
except ImportError as e:
    messaging = None
    import_error = e

from . import common


class TestCase(object):

    @defer.inlineCallbacks
    def testDelay(self):
        d = defer.Deferred()
        reactor.callLater(1, d.callback, None)
        yield d


class RabbitIntegrationTest(common.IntegrationTest, TestCase):

    timeout = 3

    def configure(self):
        self.config = dict()
        self.config['port'] = self.get_free_port()
        self.config['mnesia_dir'] = '/tmp/rabbitmq-rabbit-mnesia'

    def prepare_workspace(self):
        shutil.rmtree(self.config['mnesia_dir'], ignore_errors=True)

    @defer.inlineCallbacks
    def setUp(self):
        if messaging is None:
            raise SkipTest('Skipping the test because of missing '
                           'dependecies: %r' % import_error)

        rabbitmq = '/usr/lib/rabbitmq/bin/rabbitmq-server'
        start_script = os.path.normpath(os.path.join(
            os.path.dirname(__file__), '..', '..', '..', '..',
            'tools', 'start_rabbit.sh'))
        self.check_installed(rabbitmq)
        self.check_installed(start_script)

        self.configure()
        self.prepare_workspace()

        self.control = common.ControlProtocol(self, self._started_test)
        self.process = reactor.spawnProcess(
            self.control, start_script, args=[start_script], env={
                'HOME': os.environ['HOME'],
                'RABBITMQ_NODE_PORT': str(self.config['port']),
                'RABBITMQ_MNESIA_DIR': self.config['mnesia_dir']})

        yield self.control.ready

        self.messaging = messaging.Messaging('127.0.0.1', self.config['port'])

    def _started_test(self, buffer):
        self.log("Checking buffer: %s", buffer)
        return "broker running" in buffer

    def tearDown(self):
        self.messaging.disconnect()
        self.process.signalProcess("TERM")
        return self.control.exited
