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
import os

from twisted.internet import reactor

from feat.agencies.net import agency, broker
from feat.common import manhole, defer, time, fcntl

from feat.interface.recipient import IRecipient


class Startup(agency.Startup):

    def stage_finish(self):
        self.friend._notifications.callback("running", self)


class Shutdown(agency.Shutdown):

    def stage_internals(self):
        self.friend._release_lock()


class Agency(agency.Agency):

    broker_factory = broker.StandaloneBroker
    startup_factory = Startup
    shutdown_factory = Shutdown

    def __init__(self, options=None):
        agency.Agency.__init__(self)
        # Add standalone-specific values
        self.config["agent"] = {"kwargs": None}
        # Load configuration from environment and options
        self._load_config(os.environ, options)
        self.options = options

        self._notifications = defer.Notifier()
        self._lock_path = self.config['agency']['lock_path']
        self._lock_fd = open(self._lock_path, 'rb+')
        self._starting_master = False
        self._release_lock_cl = None

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
        return self._shutdown(stop_process=True)

    def wait_running(self):
        return self._notifications.wait("running", self.options)

    def on_master_missing(self):
        '''
        Tries to spawn a master agency if the slave agency failed to connect for
        several times. To avoid several slave agencies spawning the master
        agency a file lock is used
        @param master: Remote reference to the broker object
        '''
        self.info("We could not contact the master agency, starting a new one")
        if self._starting_master:
            self.info("Master already started, waiting for it")
            return
        if self._shutdown_task is not None:
            self.info("In shutdow, not spawning the missing master")
            return
        # Try the get an exclusive lock on the master agency startup
        if self._acquire_lock():
            self._starting_master = True
            # Allow restarting a master if we didn't succeed after 10 seconds
            self._release_lock_cl = time.callLater(10, self._release_lock)
            return self._spawn_agency("master")

    def on_become_slave(self):
        if self._release_lock_cl is not None:
            self._release_lock()
        return agency.Agency.on_become_slave(self)

    def _acquire_lock(self):
        self.debug("Trying to take a lock on %s to start the master agency",
                   self._lock_path)
        if fcntl.lock(self._lock_fd):
            self.debug("Lock taken sucessfully, we will start the master agency")
            return True
        self.debug("Could not take the lock to spawn the master agency")
        return False

    def _release_lock(self):
        self.debug("Releasing master agency lock")
        if self._release_lock_cl is not None and \
                self._release_lock_cl.active():
            self._release_lock_cl.cancel()
        self._release_lock_cl = None
        fcntl.unlock(self._lock_fd)
        self._starting_master = False

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
