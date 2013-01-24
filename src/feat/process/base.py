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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import socket
import errno
import os
import uuid
import copy

from twisted.internet import error, protocol, reactor

from feat.common import log, enum, serialization, defer
from feat.agents.base import replay
from feat.agencies.common import StateMachineMixin


def which(component, path_str):
    '''helper method having same behaviour as "which" os command.'''

    def is_exe(fpath):
        return os.path.exists(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(component)
    if fpath:
        if is_exe(component):
            return component
    else:
        for path in path_str.split(os.pathsep):
            exe_file = os.path.join(path, component)
            if is_exe(exe_file):
                return exe_file


class ProcessState(enum.Enum):
    '''
    initiated - class is created, process is not ready yet
    starting - restart() was called, started_test() didnt pass yet
    started - the STDOUT passed the started_test()
    failed - process exited with nonzero status
    finished - process exited with status 0
    terminating - termination has been ordered (we will send TERM)
    '''

    (initiated, starting, started, failed, finished, terminating) = range(6)


class ControlProtocol(protocol.ProcessProtocol, log.Logger):

    def __init__(self, owner, success_test, ready_cb, name):
        log.Logger.__init__(self, owner)

        assert callable(success_test)
        assert callable(ready_cb)

        self.success_test = success_test
        self.ready_cb = ready_cb
        self.ready = False
        self.out_buffer = ""
        self.err_buffer = ""
        self.owner = owner
        self.name = name

    def connectionMade(self):
        self._check_for_ready()

    def outReceived(self, data):
        self.out_buffer += data
        self._check_for_ready()

    def errReceived(self, data):
        self.err_buffer += data

    def processExited(self, status):
        self.debug("Process %s exited with a status: %r", self.name,
                   status.value.status)
        self.transport.loseConnection()

        self.owner.on_process_exited(status.value)

    def _check_for_ready(self):
        if not self.ready and self.success_test():
            self.debug("Process %s started successfully", self.name)
            self.log("Process %s stdout so far:\n%s",
                     self.name, self.out_buffer)
            self.ready_cb(self.out_buffer)
            self.ready = True


class Base(log.Logger, log.LogProxy, StateMachineMixin,
           serialization.Serializable):

    log_category = 'process'

    def __init__(self, logger, *args, **kwargs):
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, logger)
        StateMachineMixin.__init__(self, ProcessState.initiated)

        self.config = dict()
        self.args = list()
        self.command = None
        self.env = dict()

        self._control = None

        self.initiate(*args, **kwargs)
        self.validate_setup()

        self.log_name = self.command

    def restart(self):
        self._ensure_state([ProcessState.initiated,
                            ProcessState.finished,
                            ProcessState.failed])
        self._set_state(ProcessState.starting)
        self._control = ControlProtocol(self, self.started_test,
                                        self.on_ready, self.command)
        args = [self.command] + self.args
        self.info("Running command:  %s", self.command)
        self.debug("With arguments:   %s", self._format_log_command())
        self.log("With environment: %s", self._format_log_env())
        self._process = reactor.spawnProcess(
            self._control, self.command,
            args=args, env=self.env)

        return self.wait_for_state(
            ProcessState.failed, ProcessState.finished, ProcessState.started)

    def _format_log_command(self):
        args = [self.command] + self.args
        return " ".join("'%s'" % (a, ) for a in args)

    def _format_log_env(self):
        return " ".join("%s='%s'" % (n, v) for n, v in self.env.iteritems())

    def terminate(self):
        if self._cmp_state(ProcessState.initiated):
            return defer.succeed(self)
        elif self._cmp_state([ProcessState.starting,
                                 ProcessState.started,
                                 ProcessState.terminating]):
            self._set_state(ProcessState.terminating)
            self._process.signalProcess("TERM")
            return self.wait_for_state(ProcessState.finished)

    def on_ready(self, out_buffer):
        self._set_state(ProcessState.started)

    def on_finished(self, exception):
        pass

    def on_failed(self, exception):
        self.error("Process %s ended with %d status. \nSTDERR: \n%s\n"
                   "STDOUT:\n%s\nCOMMAND: %s\nENV: %s",
                   self.command, exception.status, self._control.err_buffer,
                   self._control.out_buffer, self._format_log_command(),
                   self._format_log_env())

    def on_process_exited(self, exception):
        mapping = {
            error.ProcessDone:\
                {'state_before': [ProcessState.initiated,
                                  ProcessState.started,
                                  ProcessState.terminating],
                 'state_after': ProcessState.finished,
                 'method': self.on_finished},
            error.ProcessTerminated:\
                [{'state_before': [ProcessState.initiated,
                                  ProcessState.started],
                  'state_after': ProcessState.failed,
                  'method': self.on_failed},
                 {'state_before': ProcessState.terminating,
                  'state_after': ProcessState.finished,
                  'method': self.on_finished}]}
        handler = self._event_handler(mapping, exception)
        if callable(handler):
            handler(exception)

    def started_test(self):
        raise NotImplementedError('This method should be overloaded')

    def initiate(self):
        '''
        This method should set the following variables:
        state.config - configuration
        state.args - list of command arguments
        state.command - command to run
        state.env - dict environment to run
        '''
        raise NotImplementedError('This method should be overloaded')

    def validate_setup(self):
        self.check_installed(self.command)

    @replay.side_effect
    def get_free_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        port = 0

        try:
            while not port:
                try:
                    s.bind(('', port))
                    port = s.getsockname()[1]
                except socket.error, e:
                    if e.args[0] != errno.EADDRINUSE:
                        raise
                    port = 0
        finally:
            s.close()

        return port

    @replay.side_effect
    def check_installed(self, component):
        path_str = self.env.get("PATH", "")
        if not which(component, path_str):
            raise DependencyError("Required component is not installed, "
                                  "expected %s to be present." % component)

    @replay.side_effect
    def get_tmp_dir(self):

        def gen_path():
            return os.path.join('/tmp', str(uuid.uuid1()))

        path = gen_path()
        while os.path.isfile(path):
            path = gen_path()

        os.makedirs(path)
        return path

    def get_config(self):
        return copy.deepcopy(self.config)


class DependencyError(Exception):
    pass
