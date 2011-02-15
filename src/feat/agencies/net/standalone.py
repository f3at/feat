import sys
import os

from twisted.internet import reactor

from feat.agencies.net import agency


class Agency(agency.Agency):

    spawns_processes = False

    def __init__(self):
        self._load_config(os.environ)
        if 'agent' not in self.config or 'id' not in self.config['agent']:
            raise RuntimeError(
                'FEAT_AGENT_ID environment variable is missing!')

        self._init_networking()
        self.info('Loaded configuration: %r', self.config)

        reactor.callWhenRunning(self._run)

    def _run(self):
        conn = self._database.get_connection(None)
        d = conn.get_document(self.config['agent']['id'])
        d.addCallback(self.start_agent)
        d.addCallbacks(self.notify_running, self._error_handler)
        return d

    def notify_running(self, *_):
        self.info('Agent is running.')
        print "Agency is ready. Agent started."
        sys.stdout.flush()

    def get_agent(self):
        return self._agents[0]
