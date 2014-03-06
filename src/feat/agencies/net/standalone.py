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

from feat.agencies.net import agency, broker
from feat.common import defer, time, fcntl, error
from feat.configure import configure

from feat.interface.recipient import IRecipient
from feat.interface.agent import IDocument


class Startup(agency.Startup):
    pass


class Shutdown(agency.Shutdown):

    def stage_internals(self):
        self.friend._release_lock()


class Agency(agency.Agency):

    broker_factory = broker.StandaloneBroker
    startup_factory = Startup
    shutdown_factory = Shutdown

    def __init__(self, config):
        agency.Agency.__init__(self, config)

        self._starting_master = False
        self._release_lock_cl = None
        self._lock_file = None

    def unregister_agent(self, medium):
        agency.Agency.unregister_agent(self, medium)
        time.callLater(1, self._shutdown, stop_process=True)

    def wait_running(self):
        d = defer.succeed(None)
        if self._startup_task:
            d.addCallback(defer.drop_param, self._startup_task.notify_finish)
        return d

    def on_master_missing(self):
        '''
        Tries to spawn a master agency if the slave agency failed to connect
        for several times. To avoid several slave agencies spawning the master
        agency a file lock is used
        '''
        self.info("We could not contact the master agency, starting a new one")
        if self._starting_master:
            self.info("Master already starting, waiting for it")
            return
        if self._shutdown_task is not None:
            self.info("Not spwaning master because we are about to terminate "
                      "ourselves")
            return
        if self._startup_task is not None:
            raise error.FeatError("Standalone started without a previous "
                                  "master agency already running, terminating "
                                  "it")

        # Try the get an exclusive lock on the master agency startup
        if self._acquire_lock():
            self._starting_master = True
            # Allow restarting a master if we didn't succeed after 10 seconds
            self._release_lock_cl = time.callLater(10, self._release_lock)
            return self._spawn_agency('master')

    def on_become_slave(self):
        if self._release_lock_cl is not None:
            self._release_lock()
        return agency.Agency.on_become_slave(self)

    def _acquire_lock(self):
        if not self._lock_file:
            self._lock_file = open(self.config.agency.lock_path, 'wb+')
        self.debug("Trying to take a lock on %s to start the master agency",
                   self._lock_file.name)

        if fcntl.lock(self._lock_file.fileno()):
            self.debug("Lock taken sucessfully, "
                       "we will start the master agency")
            return True
        self.debug("Could not take the lock to spawn the master agency")
        return False

    def _release_lock(self):
        self.debug("Releasing master agency lock")
        if self._release_lock_cl is not None and \
                self._release_lock_cl.active():
            self._release_lock_cl.cancel()
        self._release_lock_cl = None
        if self._lock_file is None:
            return
        fcntl.unlock(self._lock_file.fileno())
        self._starting_master = False
        self._lock_file.close()
        self._lock_file = None

    def spawn_agent(self, aid, **kwargs):
        # spawn_agent() from base agency asks host agent to start the agent.
        # Here we need to do something different as this agency will never
        # run a host agent. Instead we just download the descriptor and
        # run the agent locally.
        d = self.wait_running()
        if IDocument.providedBy(aid):
            d.addCallback(defer.override_result, aid)
        else:
            d.addCallback(lambda _: self._database.get_connection())
            d.addCallback(defer.call_param, 'get_document', aid)
        d.addCallback(defer.keep_param, self.create_log_link)
        d.addCallback(self.start_agent_locally, **kwargs)
        d.addCallbacks(self.notify_running, self.notify_failed,
                       errbackArgs=(aid, ))
        return d

    def create_log_link(self, desc):
        if desc.symlink_log:
            path = desc.symlink_log
            if not os.path.isabs(path):
                path = os.path.join(configure.logdir, path)
                self.link_log_file(path)

    def notify_running(self, medium):
        recp = IRecipient(medium)
        if medium.startup_failure:
            # we access this branch of code when the agent raises from
            # initiate_agent()
            self.info("Pushing failed notification to master.")
            return self._broker.fail_event(medium.startup_failure,
                                           recp.key, 'started')
        else:
            self.info("Pushing successful notification to master.")
            return self._broker.push_event(recp.key, 'started')

    def notify_failed(self, failure, agent_id):
        error.handle_failure(self, failure,
                             "Failed to spawn the agent. I will terminate")
        time.call_next(self._shutdown, stop_process=True)
        self.info("Pushing failed notification to master.")
        return self._broker.fail_event(failure, agent_id, 'started')
