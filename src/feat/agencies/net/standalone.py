import os

from twisted.internet import reactor

from feat.agencies.net import agency
from feat.common import manhole


add_options = agency.add_options


class Agency(agency.Agency):

    spawns_processes = False

    def __init__(self, options=None):
        # Initialize default configuration
        self._init_config()
        # Add standalone-specific values
        self.config["agent"] = {"id": None}
        # Load configuration from environment and options
        self._load_config(os.environ, options)
        if self.config['agent']['id'] is None:
            raise RuntimeError("No agent identifier specified.")

        reactor.callWhenRunning(self._run)

    def _run(self):
        d = self._init_networking()
        d.addCallback(lambda _: self._database.get_connection(None))
        d.addCallback(lambda conn:
                      conn.get_document(self.config['agent']['id']))
        d.addCallback(self.start_agent_locally)
        d.addCallbacks(self.notify_running, self._error_handler)
        return d

    def notify_running(self, *_):
        return self._broker.push_event(self.config['agent']['id'], 'started')

    def get_agent(self):
        return self._agents[0]

    @manhole.expose()
    def kill(self):
        '''kill() -> Terminate the process of the standalone.'''
        reactor.stop()
