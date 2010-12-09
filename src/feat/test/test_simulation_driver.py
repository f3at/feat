# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.internet import defer

from feat.common import format_block
from feat.test import common
from feat.simulation import driver


class Commands(common.Mock):

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
        self.parser = driver.Parser(self, self.output, self.commands)

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
        
