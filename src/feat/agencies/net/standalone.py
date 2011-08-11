import os

from twisted.internet import reactor

from feat.agencies.net import agency, broker
from feat.common import manhole, defer

from feat.interface.recipient import IRecipient


class Agency(agency.Agency):

    broker_factory = broker.StandaloneBroker

    def __init__(self, options=None):
        agency.Agency.__init__(self)
        # Add standalone-specific values
        self.config["agent"] = {"kwargs": None}
        # Load configuration from environment and options
        self._load_config(os.environ, options)

        self._notifications = defer.Notifier()

    def initiate(self):
        reactor.callWhenRunning(self._initiate)
        return defer.succeed(self)

    def _initiate(self):
        d = agency.Agency.initiate(self)
        d.addCallback(defer.drop_param, self._notifications.callback,
                      "running", self)
        return d

    def unregister_agent(self, medium):
        agency.Agency.unregister_agent(self, medium)
        self.kill()

    def wait_running(self):
        return self._notifications.wait("running")

    def _start_host_agent_if_necessary(self):
        # Disable host agent startup for standalone agencies.
        pass

    def _flush_agents_body(self):
        if self._to_spawn:
            aid, kwargs = self._to_spawn.pop(0)
            d = self.wait_running()
            d.addCallback(lambda _: self._database.get_connection())
            d.addCallback(defer.call_param, 'get_document', aid)
            d.addCallback(self.start_agent_locally, **kwargs)
            d.addCallbacks(self.notify_running, self.notify_failed,
                           errbackArgs=(aid, ))
            return d

    def notify_running(self, medium):
        recp = IRecipient(medium)
        return self._broker.push_event(recp.key, 'started')

    def notify_failed(self, failure, agent_id):
        self._error_handler(failure)
        return self._broker.fail_event(failure, agent_id, 'started')

    @manhole.expose()
    def kill(self):
        '''kill() -> Terminate the process of the standalone.'''
        self.info('kill() called. Shuting down')
        d = self.shutdown()
        d.addCallback(lambda _: self._stop_process())
        return d

    def _stop_process(self):
        reactor.stop()
