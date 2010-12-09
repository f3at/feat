# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from zope.interface import classProvides
from twisted.internet import defer

from feat.common import format_block, log
from feat.test import common
from feat.simulation import driver
from feat.agents.base import agent, descriptor
from feat.interface.agent import IAgentFactory


@agent.register
class DummyAgent(agent.BaseAgent):
    classProvides(IAgentFactory)


class TestDriver(common.TestCase):

    timeout = 10

    def setUp(self):
        self.driver = driver.Driver()

    @defer.inlineCallbacks
    def testSpawnAgency(self):
        test = 'agency = spawn_agency\n'
        d = self.cb_after(None, self.driver, 'finished_processing')
        self.driver.process(test)
        yield d

        self.assertEqual(1, len(self.driver._agencies))
        self.assertEqual(self.driver._agencies[0],
                         self._get_local_var('agency'))

    @defer.inlineCallbacks
    def testCreateDescriptor(self):
        test = 'desc = descriptor_factory\n'
        d = self.cb_after(None, self.driver, 'finished_processing')
        self.driver.process(test)
        yield d

        desc = self._get_local_var('desc')
        self.assertTrue(isinstance(desc, descriptor.Descriptor))
        self.log(desc.doc_id)
        fetched = yield self.driver._database_connection.get_document(
            desc.doc_id)
        self.assertEqual(desc.doc_id, fetched.doc_id)

    def _get_local_var(self, name):
        return self.driver._parser.get_local(name)


class DummyDriver(log.Logger, log.LogProxy):
    '''
    Used in parser tests.
    '''

    def __init__(self, testcase):
        log.Logger.__init__(self, testcase)
        log.LogProxy.__init__(self, testcase)

    def finished_processing(self):
        pass


class Commands(common.Mock):
    '''
    Test commands used in parser test.
    '''

    @common.Mock.stub
    def cmd_spam(self, arg1, arg2):
        pass

    @common.Mock.stub
    def cmd_eggs(self, arg1, arg2):
        pass

    def cmd_not_mocked(self, arg1, arg2):
        '''
        doc string
        '''

    def cmd_return_5(self):
        return 5

    def cmd_echo(self, echo):
        return echo


class TestParser(common.TestCase):

    timeout = 2

    def setUp(self):
        self.output = driver.Output()
        self.commands = Commands()
        self.parser = driver.Parser(DummyDriver(self),
                                    self.output, self.commands)

    @defer.inlineCallbacks
    def testSimpleParsing(self):
        test = format_block('''
        spam 2 "text"

        eggs 1 "spam"
        ''')
        self.log("%r", test)
        d = self.cb_after(None, self.commands, 'cmd_eggs')
        self.parser.dataReceived(test)
        yield d

        self.assertCalled(self.commands, 'cmd_spam')
        call = self.commands.find_calls('cmd_spam')[0]
        self.assertEqual('2', call.args[0])
        self.assertEqual('text', call.args[-1])

        self.assertCalled(self.commands, 'cmd_eggs')
        call = self.commands.find_calls('cmd_eggs')[0]
        self.assertEqual('1', call.args[0])
        self.assertEqual('spam', call.args[-1])

    @defer.inlineCallbacks
    def testUnknownMethod(self):
        test = format_block('''
        spam "all" "ok"

        something_odd
        ''')
        d = self.cb_after(None, self.output, 'write')
        self.parser.dataReceived(test)
        yield d

        self.assertEqual('Unknown command: something_odd\n',
                         self.output.getvalue())

    @defer.inlineCallbacks
    def testWrongParams(self):
        test = "not_mocked 'to' 'many' 'params'\n"

        d = self.cb_after(None, self.output, 'write')
        self.parser.dataReceived(test)
        yield d

        self.assertTrue('exactly 3 arguments (4 given)' in\
                        self.output.getvalue())

    @defer.inlineCallbacks
    def testAssigment(self):
        test = "varname = return_5\n"

        d = self.cb_after(None, self.output, 'write')
        self.parser.dataReceived(test)
        yield d
        self.assertEqual('5\n', self.output.getvalue())
        self.assertEqual(5, self.parser._locals['varname'])

    @defer.inlineCallbacks
    def testGettingVariable(self):
        test = format_block('''
        varname = return_5
        echo varname
        ''')

        d = self.cb_after(None, self.parser, 'on_finish')
        self.parser.dataReceived(test)
        yield d
        self.assertEqual('5\n5\n', self.output.getvalue())
        self.assertEqual(5, self.parser._locals['varname'])
