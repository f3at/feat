# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from zope.interface import classProvides
from twisted.internet import defer

from feat.common import format_block, log
from feat.test import common
from feat.simulation import driver
from feat.agents.base import agent, descriptor
from feat.interface.agent import IAgentFactory


class TestDriver(common.TestCase):

    timeout = 2

    def setUp(self):
        self.driver = driver.Driver()

    @defer.inlineCallbacks
    def testSpawnAgency(self):
        test = 'agency = spawn_agency()\n'
        d = self.cb_after(None, self.driver, 'finished_processing')
        self.driver.process(test)
        yield d

        self.assertEqual(1, len(self.driver._agencies))
        self.assertEqual(self.driver._agencies[0],
                         self._get_local_var('agency'))

    @defer.inlineCallbacks
    def testCreateDescriptor(self):
        test = "desc = descriptor_factory('descriptor')\n"
        d = self.cb_after(None, self.driver, 'finished_processing')
        self.driver.process(test)
        yield d

        desc = self._get_local_var('desc')
        self.assertTrue(isinstance(desc, descriptor.Descriptor))
        self.log(desc.doc_id)
        fetched = yield self.driver._database_connection.get_document(
            desc.doc_id)
        self.assertEqual(desc.doc_id, fetched.doc_id)

    @defer.inlineCallbacks
    def testStartAgent(self):
        test = format_block("""
        agency = spawn_agency()
        start_agent(agency, descriptor_factory('descriptor'))
        """)
        d = self.cb_after(None, self.driver, 'finished_processing')
        self.driver.process(test)
        yield d

        ag = self.driver._agencies[0]
        self.assertEqual(1, len(ag._agents))
        agent = ag._agents[0]
        self.assertIsInstance(agent.agent, common.DummyAgent)
        self.assertCalled(agent.agent, 'initiate')

    def testBreakpoints(self):

        def asserts1(_):
            self.assertTrue(self._get_local_var('desc1') is not None)
            self.assertFalse(self._local_var_exists('desc2'))

        def asserts2(_):
            self.assertTrue(self._get_local_var('desc2') is not None)

        test = format_block("""
        desc1 = descriptor_factory('descriptor')
        breakpoint('break')
        desc2 = descriptor_factory('descriptor')
        """)

        d1 = self.driver.register_breakpoint('break')
        d1.addCallback(asserts1)
        d2 = self.cb_after(None, self.driver, 'finished_processing')
        d2.addCallback(asserts2)

        self.driver.process(test)

        return defer.DeferredList([d1, d2])

    def _get_local_var(self, name):
        return self.driver._parser.get_local(name)

    def _local_var_exists(self, name):
        return name in self.driver._parser._locals


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
        test = format_block("""
        spam(2, 'text')

        eggs(1.1, 'spam')
        """)
        self.log("%r", test)
        d = self.cb_after(None, self.commands, 'cmd_eggs')
        self.parser.dataReceived(test)
        yield d

        self.assertCalled(self.commands, 'cmd_spam')
        call = self.commands.find_calls('cmd_spam')[0]
        self.assertEqual(2, call.args[0])
        self.assertEqual('text', call.args[-1])

        self.assertCalled(self.commands, 'cmd_eggs')
        call = self.commands.find_calls('cmd_eggs')[0]
        self.assertEqual(1.1, call.args[0])
        self.assertEqual('spam', call.args[-1])

    @defer.inlineCallbacks
    def testNestedCommands(self):
        test = format_block("""
        echo(return_5())
        """)

        d = self.cb_after(None, self.parser, 'on_finish')
        self.parser.dataReceived(test)
        yield d
        self.assertEqual('5\n', self.output.getvalue())

    @defer.inlineCallbacks
    def testUnknownMethod(self):
        test = format_block("""
        spam('all', 'ok')

        something_odd()
        """)
        d = self.cb_after(None, self.output, 'write')
        self.parser.dataReceived(test)
        yield d

        self.assertEqual('Unknown command: something_odd\n',
                         self.output.getvalue())

    @defer.inlineCallbacks
    def testBadSyntax(self):
        test = format_block("""
        var = 3 2
        """)
        d = self.cb_after(None, self.output, 'write')
        self.parser.dataReceived(test)
        yield d

        self.assertEqual('Syntax error processing line: var = 3 2\n',
                         self.output.getvalue())

    @defer.inlineCallbacks
    def testBadSyntax2(self):
        test = format_block("""
        echo(3 + 2)
        """)
        d = self.cb_after(None, self.output, 'write')
        self.parser.dataReceived(test)
        yield d

        self.assertTrue('Could not detect type of element: +' in\
                         self.output.getvalue())

    @defer.inlineCallbacks
    def testUnknownVariable(self):
        test = format_block("""
        echo(some_var)
        """)

        d = self.cb_after(None, self.output, 'write')
        self.parser.dataReceived(test)
        yield d

        self.assertEqual('Unknown variable some_var\n',# in\
                         self.output.getvalue())

    @defer.inlineCallbacks
    def testWrongParams(self):
        test = "not_mocked('to', 'many', 'params')\n"

        d = self.cb_after(None, self.output, 'write')
        self.parser.dataReceived(test)
        yield d

        self.assertTrue('exactly 3 arguments (4 given)' in\
                        self.output.getvalue())

    @defer.inlineCallbacks
    def testAssigment(self):
        test = "varname = return_5()\n"

        d = self.cb_after(None, self.output, 'write')
        self.parser.dataReceived(test)
        yield d
        self.assertEqual('5\n', self.output.getvalue())
        self.assertEqual(5, self.parser._locals['varname'])

    @defer.inlineCallbacks
    def testAssigmentConstant(self):
        test = "varname = 5\n"

        d = self.cb_after(None, self.output, 'write')
        self.parser.dataReceived(test)
        yield d
        self.assertEqual('5\n', self.output.getvalue())
        self.assertEqual(5, self.parser._locals['varname'])

    @defer.inlineCallbacks
    def testGettingVariable(self):
        test = format_block('''
        varname = return_5()
        echo(varname)
        ''')

        d = self.cb_after(None, self.parser, 'on_finish')
        self.parser.dataReceived(test)
        yield d
        self.assertEqual('5\n5\n', self.output.getvalue())
        self.assertEqual(5, self.parser._locals['varname'])

    def testRegexps(self):
        # assignment
        m = self.parser.re['assignment'].search('variable = rest of expresion')
        self.assertTrue(m)
        self.assertEqual('variable', m.group(1))
        self.assertEqual('rest of expresion', m.group(2))

        m = self.parser.re['assignment'].search('variable = 5')
        self.assertTrue(m)
        self.assertEqual('variable', m.group(1))
        self.assertEqual('5', m.group(2))

        m = self.parser.re['assignment'].search('variable =rest of expresion')
        self.assertTrue(m)
        self.assertEqual('variable', m.group(1))
        self.assertEqual('rest of expresion', m.group(2))

        m = self.parser.re['assignment'].search(
            'var iable = rest of expresion')
        self.assertFalse(m)

        m = self.parser.re['assignment'].search('variable = ')
        self.assertFalse(m)

        # number
        m = self.parser.re['number'].search('1')
        self.assertTrue(m)
        self.assertEqual('1', m.group(0))

        m = self.parser.re['number'].search('1.1')
        self.assertTrue(m)
        self.assertEqual('1.1', m.group(0))

        m = self.parser.re['number'].search('.12')
        self.assertFalse(m)

        m = self.parser.re['number'].search('a1.12')
        self.assertFalse(m)

        # string
        m = self.parser.re['string'].search("'this is string'")
        self.assertTrue(m)
        self.assertEqual('this is string', m.group(1))

        m = self.parser.re['string'].search("'this is string")
        self.assertFalse(m)

        m = self.parser.re['string'].search("'this is string''")
        self.assertFalse(m)

        # variable
        m = self.parser.re['variable'].search("this")
        self.assertTrue(m)
        self.assertEqual('this', m.group(0))

        m = self.parser.re['variable'].search("this.and.that")
        self.assertTrue(m)
        self.assertEqual('this.and.that', m.group(0))

        m = self.parser.re['variable'].search("this and.that")
        self.assertFalse(m)

        # calls
        m = self.parser.re['call'].search("this()")
        self.assertTrue(m)
        self.assertEqual('this', m.group(1))
        self.assertEqual('', m.group(2))

        m = self.parser.re['call'].search("this(some more args)")
        self.assertTrue(m)
        self.assertEqual('this', m.group(1))
        self.assertEqual('some more args', m.group(2))

        m = self.parser.re['call'].search("this(some more args")
        self.assertFalse(m)

        m = self.parser.re['call'].search("this(that())")
        self.assertTrue(m)
        self.assertEqual('this', m.group(1))
        self.assertEqual('that()', m.group(2))

        # splitter
        m = self.parser.split("this, and, that")
        self.assertEqual(['this', 'and', 'that'], m)

        m = self.parser.split("this, 'and that also', that")
        self.assertEqual(['this', "'and that also'", 'that'], m)

        m = self.parser.split("this, 'and that, also', that")
        self.assertEqual(['this', "'and that, also'", 'that'], m)

        m = self.parser.split("this, 'and that, also', that")
        self.assertEqual(['this', "'and that, also'", 'that'], m)

        m = self.parser.split("this, func_call(some, args(aaa)), that")
        self.assertEqual(['this', 'func_call(some, args(aaa))', 'that'], m)

        m = self.parser.split("1.23, func_call(some, args(aaa)), that")
        self.assertEqual(['1.23', 'func_call(some, args(aaa))', 'that'], m)

        self.assertRaises(driver.BadSyntax,
                          self.parser.split,
                          "this, func_call(some, argsaaa)), that")
