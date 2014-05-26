# -*- coding: utf-8 -*-.

import json

from zope.interface import implements
from twisted.web import client
from twisted.web.error import Error as WebError

from feat.test import common
from feat.common import error, defer, log
from feat.models import model, action, call
from feat.gateway import gateway
from feat.extern.log import log as xlog

from feat.models.interface import ActionCategories


class Logger(object):

    log_category = 'test-category'
    log_name = 'test-name'

    implements(log.ILogger, log.ILogKeeper)

    def __init__(self):
        # (format, tuple of args)
        self.errors = list()

    def do_log(self, level, object, category, format, args,
               depth=1, file_path=None, line_num=None):
        if level == 1:
            self.errors.append((format, args))


class Error(error.FeatError):
    pass


def do_raise(_=None):
    raise Error("message")


class TestError(common.TestCase):

    def setUp(self):
        common.TestCase.setUp(self)
        self.keeper = Logger()
        self.logger = log.Logger(self.keeper)
        self._saved = xlog.getLogSettings()

    def tearDown(self):
        xlog.setLogSettings(self._saved)
        return common.TestCase.tearDown(self)

    def _errback(self, fail):
        error.handle_failure(self.logger, fail, "Error handler: ")

    def testExceptionUnicode(self):
        a = u'Adrián'
        exp = error.FeatError(a)
        msg = str(exp)
        self.assertIsInstance(msg, str)

    def testHandleException(self):
        xlog.setDebug('4')
        try:
            do_raise()
        except Error as e:
            error.handle_exception(self.logger, e, "Error handler:")

        self.assertEqual(1, len(self.keeper.errors))
        self.assertEqual(2, len(self.keeper.errors[0][1]))
        traceback = self.keeper.errors[0][1][1]
        self.assertIn(
            'feat/test/test_common_error.py',
            traceback)

    @defer.inlineCallbacks
    def testHandleFailure(self):
        xlog.setDebug('4')
        d = defer.succeed(None)
        d.addCallback(do_raise)
        d.addErrback(self._errback)
        yield d

        self.assertEqual(1, len(self.keeper.errors))
        self.assertEqual(2, len(self.keeper.errors[0][1]))
        traceback = self.keeper.errors[0][1][1]
        self.assertIn(
            'feat/test/test_common_error.py',
            traceback)

    @defer.inlineCallbacks
    def testExceptionInGateway(self):
        xlog.setDebug('4')
        root = Root(None)
        gate = gateway.Gateway(root, (5000, 10000), log_keeper=self.keeper,
                               label='Test gateway')
        yield gate.initiate()
        self.addCleanup(gate.cleanup)
        d = request('/_post', gate.port)
        self.assertFailure(d, WebError)
        yield d

        self.assertEqual(1, len(self.keeper.errors))
        self.assertEqual(2, len(self.keeper.errors[0][1]))
        traceback = self.keeper.errors[0][1][1]
        self.assertIn(
            "do_raise() #fail with 500 Internal Server Error",
            traceback)


### things defined for the test with gateway ###


class TestAction(action.Action):

    action.category(ActionCategories.command)
    action.effect(call.action_perform('do_it'))

    def do_it(self, value):
        do_raise() #fail with 500 Internal Server Error


register = model.get_registry().register


@register
class Root(model.Model):

    model.identity('feat.test.test_common_error.root')
    model.action('post', TestAction)


def request(path, port, body=None, method="POST", host='localhost'):
    headers = {'Accept': 'application/json',
               'Content-Type': 'application/json'}
    body = json.dumps(body) if body else ''
    url = 'http://%s:%d%s' % (host, port, path)
    return client.getPage(url, method=method, headers=headers, postdata=body)
