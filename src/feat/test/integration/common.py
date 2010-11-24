# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import socket
import errno
import os

from twisted.internet import protocol, defer
from twisted.trial import unittest
from feat.common import log
from feat.test import common


class IntegrationTest(common.TestCase):

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
            raise unittest.SkipTest("Required component is not installed, "
                                    "expected %s to be present." % component)


class ControlProtocol(protocol.ProcessProtocol, log.Logger):

    def __init__(self, test_case, success_test):
        log.Logger.__init__(self, test_case)

        assert callable(success_test)

        self.success_test = success_test
        self.out_buffer = ""
        self.err_buffer = ""
        self.ready = defer.Deferred()
        self.exited = defer.Deferred()

    def outReceived(self, data):
        self.out_buffer += data
        self.log("Process buffer so far:\n%s", self.out_buffer)
        if self.success_test(self.out_buffer):
            if not self.ready.called:
                self.ready.callback(self.out_buffer)

    def errReceived(self, data):
        self.err_buffer += data
        self.error("Receivced on err_buffer, so far:\n%s", self.err_buffer)

    def processExited(self, status):
        self.log("Process exites with status: %r", status)
        self.exited.callback(None)
