# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import socket
import errno
import os
import uuid
import copy

from twisted.internet import error, protocol, reactor

from feat.common import log, enum, serialization
from feat.agents.base import replay
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

    log_category = "process-protocol"

    def __init__(self, owner, success_test, ready_cb):
        log.Logger.__init__(self, owner)

        assert callable(success_test)
        assert callable(ready_cb)

        self.success_test = success_test
        self.ready_cb = ready_cb
        self.ready = False
        self.out_buffer = ""
        self.err_buffer = ""
        self.owner = owner

    def outReceived(self, data):
        self.out_buffer += data
        if not self.ready and self.success_test():
            self.log("Process start successful. "
                     "Process stdout buffer so far:\n%s", self.out_buffer)
            self.ready_cb(self.out_buffer)
            self.ready = True

    def errReceived(self, data):
        self.err_buffer += data
        self.error("Receivced on err_buffer, so far:\n%s", self.err_buffer)

    def processExited(self, status):
        self.log("Process exited with a status: %r", status)
        self.transport.loseConnection()

        self.owner.on_process_exited(status.value)


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

    def restart(self):
        self._ensure_state([ProcessState.initiated,
                            ProcessState.finished,
                            ProcessState.failed])

        self._control = ControlProtocol(self, self.started_test, self.on_ready)
        self._process = reactor.spawnProcess(
            self._control, self.command,
            args=[self.command] + self.args, env=self.env)

        return self.wait_for_state(ProcessState.started)

    def terminate(self):
        self._ensure_state([ProcessState.initiated,
                            ProcessState.started,
                            ProcessState.terminating])
        self._set_state(ProcessState.terminating)
        self._process.signalProcess("TERM")
        return self.wait_for_state(ProcessState.finished)

    def on_ready(self, out_buffer):
        self._set_state(ProcessState.started)

    def on_finished(self, exception):
        pass

    def on_failed(self, exception):
        pass

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
        self._event_handler(mapping, exception)

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
        if not os.path.isfile(component):
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

    def _call(self, method, *args, **kwargs):
        '''
        Required by StateMachine._event_handler
        '''
        return method(*args, **kwargs)


class DependencyError(Exception):
    pass
