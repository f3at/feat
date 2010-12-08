# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import socket
import errno
import os
import uuid

from twisted.internet import error, protocol, defer, reactor

from feat.common import log, enum
from feat.agencies.common import StateMachineMixin


class ProcessState(enum.Enum):
    '''
    initiated - class is created, process is not ready yet
    started - the STDOUT passed the started_test()
    failed - process exited with nonzero status
    finished - process exited with status 0
    terminating - termination has been ordered (we will send TERM)
    '''

    (initiated, started, failed, finished, terminating) = range(5)


class ControlProtocol(protocol.ProcessProtocol, log.Logger):

    def __init__(self, owner, success_test):
        log.Logger.__init__(self, owner)

        assert callable(success_test)

        self.success_test = success_test
        self.out_buffer = ""
        self.err_buffer = ""
        self.ready = defer.Deferred()
        self.owner = owner

    def outReceived(self, data):
        self.out_buffer += data
        if self.success_test():
            self.log("Process start successful. "
                     "Process stdout buffer so far:\n%s", self.out_buffer)
            if not self.ready.called:
                self.ready.callback(self.out_buffer)

    def errReceived(self, data):
        self.err_buffer += data
        self.error("Receivced on err_buffer, so far:\n%s", self.err_buffer)

    def processExited(self, status):
        self.log("Process exited with a status: %r", status)
        self.transport.loseConnection()

        self.owner.on_process_exited(status.value)


class Base(log.Logger, log.FluLogKeeper, StateMachineMixin):

    log_category = 'process'

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)
        StateMachineMixin.__init__(self,
                                   ProcessState.initiated)

        self.config = dict()
        self.args = list()
        self.command = None
        self.env = dict()

        self.control = ControlProtocol(self, self.started_test)
        self.initiate()
        self.validate_setup()

    def restart(self):
        self._ensure_state([ProcessState.initiated,
                            ProcessState.finished,
                            ProcessState.failed])

        self.process = reactor.spawnProcess(
            self.control, self.command, args=self.args,
            env=self.env)

        self.control.ready.addCallback(self.on_ready)
        return self.control.ready

    def terminate(self):
        self._ensure_state([ProcessState.initiated,
                            ProcessState.started])
        self._set_state(ProcessState.terminating)
        self.process.signalProcess("TERM")
        return self.wait_for_state(ProcessState.finished)

    def on_ready(self, out_buffer):
        self._set_state(ProcessState.started)

    def on_finished(self, exception):
        self._set_state(ProcessState.finished)

    def on_failed(self, exception):
        self._set_state(ProcessState.failed)

    def on_process_exited(self, exception):
        mapping = {
            error.ProcessDone:\
                {'state_before': [ProcessState.initiated,
                                  ProcessState.started],
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
        self._event_handler(mapping, exception)

    def started_test(self):
        raise NotImplementedError('This method should be overloaded')

    def initiate(self):
        '''
        This method should set the following variables:
        self.config - configuration
        self.args - list of command arguments
        self.command - command to run
        self.env - dict environment to run
        '''
        raise NotImplementedError('This method should be overloaded')

    def validate_setup(self):
        self.check_installed(self.command)
        self.args = [self.command] + self.args

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

    def check_installed(self, component):
        if not os.path.isfile(component):
            raise DependencyError("Required component is not installed, "
                                    "expected %s to be present." % component)

    def get_tmp_dir(self):

        def gen_path():
            return os.path.join('/tmp', str(uuid.uuid1()))

        path = gen_path()
        while os.path.isfile(path):
            path = gen_path()

        os.makedirs(path)
        return path

    def _call(self, method, *args, **kwargs):
        '''
        Required by StateMachineMixin._event_handler
        '''
        return method(*args, **kwargs)


class DependencyError(Exception):
    pass
