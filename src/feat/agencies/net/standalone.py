import os

from twisted.internet import reactor

from feat.agencies.net import agency
from feat.common import log, manhole, defer
from feat.common.serialization import json


add_options = agency.add_options


class Agency(agency.Agency):

    def __init__(self, options=None):
        agency.Agency.__init__(self)
        # Add standalone-specific values
        self.config["agent"] = {"id": None, "args": None, "kwargs": None}
        # Load configuration from environment and options
        self._load_config(os.environ, options)
        if self.config['agent']['id'] is None:
            raise RuntimeError("No agent identifier specified.")

        self._notifications = defer.Notifier()

    def initiate(self):
        reactor.callWhenRunning(self._run)

    def wait_running(self):
        return self._notifications.wait("running")

    def _run(self):
        aid = self.config['agent']['id']
        args = ()
        kwargs = {}
        if self.config['agent']['args']:
            args = json.unserialize(self.config['agent']['args'])
        if self.config['agent']['kwargs']:
            kwargs = json.unserialize(self.config['agent']['kwargs'])

        d = agency.Agency.initiate(self)
        d.addCallback(lambda _: self._database.get_connection(None))
        d.addCallback(lambda conn: conn.get_document(aid))
        d.addCallback(self.start_agent_locally, *args, **kwargs)
        d.addCallbacks(self.notify_running, self.notify_failed)
        return d

    def notify_running(self, *_):
        self._notifications.callback("running", self)
        return self._broker.push_event(self.config['agent']['id'], 'started')

    def notify_failed(self, failure):
        self._notifications.errback("running", failure)
        self._error_handler(failure)
        return self._broker.fail_event(
            failure, self.config['agent']['id'], 'started')

    def get_agent(self):
        return self._agents[0]

    @manhole.expose()
    def kill(self):
        '''kill() -> Terminate the process of the standalone.'''
        self.info('kill() called. Shuting down')
        d = self.shutdown()
        d.addCallback(lambda _: self._stop_process())
        return d

    def _stop_process(self):
        reactor.stop()
