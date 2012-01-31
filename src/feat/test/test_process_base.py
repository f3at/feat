import os

from feat.common import log, first, defer, run
from feat.test import common, dummy_process
from feat.process import standalone, base

from feat.interface.log import LogLevel


class TestLogBuffer(log.LogBuffer):

    def __init__(self, testcase, limit):
        self.testcase = testcase
        log.LogBuffer.__init__(self, limit)

    def assert_has_log(self, level, message_part):
        found = first(x for x in self._buffer
                      if (x[0] == level and
                          message_part in x[3] % x[4]))
        msg = ("Log line matching %r with lvl=%r not found!" %
               (message_part, level))
        self.testcase.assertIsNot(None, found, msg)


class TestRunningProcess(common.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        tee = log.get_default()
        self.keeper = TestLogBuffer(self, limit=10000)
        tee.add_keeper('test-buffer', self.keeper)
        self.cmd = os.path.join(os.path.dirname(dummy_process.__file__),
                                'dummy_process.py')

    @defer.inlineCallbacks
    def testFailingStandalone(self):
        process = standalone.Process(self, self.cmd, ['--fail'], os.environ)
        yield process.restart()
        yield process.wait_for_state(base.ProcessState.failed)
        yield common.delay(None, 0.01) #break the execution chain
        self.keeper.assert_has_log(
            LogLevel.error, "CustomException: I'm failing as you have asked.")

    @defer.inlineCallbacks
    def testExitingSuccessfully(self):
        process = standalone.Process(self, self.cmd, [], os.environ)
        yield process.restart()
        yield process.wait_for_state(base.ProcessState.started)
        d = process.wait_for_state(base.ProcessState.finished)
        self._sigusr1_process()
        yield d

    def _sigusr1_process(self):
        pid = run.wait_pidfile(os.path.curdir, 'dummy_process')
        run.signal_pid(pid, 10)

    @defer.inlineCallbacks
    def testDaemonizingProcess(self):
        process = standalone.Process(self, self.cmd, ['--daemonize'],
                                     os.environ)
        self.addCleanup(self._sigusr1_process)
        yield process.restart()
        yield process.wait_for_state(base.ProcessState.finished)

    @defer.inlineCallbacks
    def tearDown(self):
        tee = log.get_default()
        tee.remove_keeper('test-buffer')
        self.keeper.clean()
        try:
            os.remove(run.get_pidpath(os.path.curdir, 'dummy_process'))
        except OSError:
            pass

        yield common.TestCase.tearDown(self)
