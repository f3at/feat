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
from twisted.internet import defer

from feat.simulation import driver
from feat.common import manhole, log
from feat.common.text_helper import format_block
from feat.test import common


class TestInheritance(common.TestCase):

    timeout = 2

    def setUp(self):
        self.output = driver.Output()
        self.commands = InheritingManhole()
        self.parser = manhole.Parser(DummyDriver(self),
                                    self.output, self.commands)

    @defer.inlineCallbacks
    def testWorksCorrectly(self):
        test = format_block("""
        echo('from super-class')
        sth('from children-class')
        """)

        d = self.cb_after(None, self.parser, 'on_finish')
        self.parser.dataReceived(test)
        yield d

        self.assertEqual('from super-class\nfrom children-class\n',
                         self.output.getvalue())


class TestParser(common.TestCase):

    timeout = 2

    def setUp(self):
        self.output = driver.Output()
        self.commands = Commands()
        self.parser = manhole.Parser(DummyDriver(self),
                                    self.output, self.commands)

    def testPBRemotes(self):
        self.assertTrue(callable(self.commands.remote_spam))
        self.assertTrue(callable(self.commands.remote_eggs))

    @defer.inlineCallbacks
    def testSimpleParsing(self):
        test = format_block("""
        spam(2, 'text')

        eggs(1.1, 'spam')
        """)
        self.log("%r", test)
        d = self.cb_after(None, self.parser, 'on_finish')
        self.parser.dataReceived(test)
        yield d

        self.assertCalled(self.commands, 'spam')
        call = self.commands.find_calls('spam')[0]
        self.assertEqual(2, call.args[0])
        self.assertEqual('text', call.args[-1])

        self.assertCalled(self.commands, 'eggs')
        call = self.commands.find_calls('eggs')[0]
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
    def testKeywords(self):
        test = format_block("""
        echo(echo='some text')
        """)
        d = self.cb_after(None, self.parser, 'on_finish')
        self.parser.dataReceived(test)
        yield d
        self.assertEqual('some text\n', self.output.getvalue())

    @defer.inlineCallbacks
    def testUnknownMethod(self):
        test = format_block("""
        spam('all', 'ok')

        something_odd()
        """)
        d = self.cb_after(None, self.output, 'write')
        self.parser.dataReceived(test)
        yield d

        self.assertEqual('Unknown command: Commands.something_odd\n',
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
    def testAssignNone(self):
        test = "var = None\n"
        d = self.cb_after(None, self.parser, 'on_finish')
        self.parser.dataReceived(test)
        yield d
        self.assertEqual(None, self.parser._locals['var'])

    @defer.inlineCallbacks
    def testAssignTrueAndFalse(self):
        test = "var1 = True\nvar2=False\n"
        d = self.cb_after(None, self.parser, 'on_finish')
        self.parser.dataReceived(test)
        yield d
        self.assertEqual(True, self.parser._locals['var1'])
        self.assertEqual(False, self.parser._locals['var2'])

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

        m = self.parser.re['assignment'].search('object.variable = 1')
        self.assertFalse(m)

        # async calls
        m = self.parser.re['async'].search('async agent.start_agent(aaa)')
        self.assertTrue(m)
        self.assertEqual('agent.start_agent(aaa)', m.group(1))

        # async yielding
        m = self.parser.re['yielding'].search('yield defer')
        self.assertTrue(m)
        self.assertEqual('defer', m.group(1))

        m = self.parser.re['yielding'].search('yield defer sthelse')
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

        # none
        m = self.parser.re['none'].search("None")
        self.assertTrue(m)

        # variable
        m = self.parser.re['variable'].search("this")
        self.assertTrue(m)
        self.assertEqual('this', m.group(0))

        m = self.parser.re['variable'].search("_")
        self.assertTrue(m)
        self.assertEqual('_', m.group(0))

        m = self.parser.re['variable'].search("this.and.that")
        self.assertTrue(m)
        self.assertEqual('this.and.that', m.group(0))

        m = self.parser.re['variable'].search("this and.that")
        self.assertFalse(m)

        # simple calls
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

        m = self.parser.re['call'].search("someobj.this(some more args)")
        self.assertFalse(m)

        m = self.parser.re['call'].search("this(that())")
        self.assertTrue(m)
        self.assertEqual('this', m.group(1))
        self.assertEqual('that()', m.group(2))

        # method calls on stored objects

        m = self.parser.re['method_call'].search(
            "someobj.this(some more args)")
        self.assertTrue(m)
        self.assertEqual('someobj', m.group(1))
        self.assertEqual('this', m.group(2))
        self.assertEqual('some more args', m.group(3))

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

        self.assertRaises(manhole.BadSyntax,
                          self.parser.split,
                          "this, func_call(some, argsaaa)), that")

        m = self.parser.split("this, keyword=and, that, keyword2='some text'")
        self.assertEqual(
            ['this', 'keyword=and', 'that', "keyword2='some text'"], m)

        m = self.parser.split("this, keyword=and(var)")
        self.assertEqual(
            ['this', 'keyword=and(var)'], m)


class Commands(common.Mock, manhole.Manhole):
    '''
    Test commands used in parser test.
    '''

    @manhole.expose()
    @common.Mock.stub
    def spam(self, arg1, arg2):
        pass

    @manhole.expose()
    @common.Mock.stub
    def eggs(self, arg1, arg2):
        pass

    @manhole.expose()
    def not_mocked(self, arg1, arg2):
        '''
        doc string
        '''

    @manhole.expose()
    def return_5(self):
        return 5

    @manhole.expose()
    def echo(self, echo):
        return echo


class InheritingManhole(Commands):

    @manhole.expose()
    def sth(self, echo):
        return echo


class DummyDriver(log.Logger, log.LogProxy):
    '''
    Used in parser tests.
    '''

    def __init__(self, testcase):
        log.Logger.__init__(self, testcase)
        log.LogProxy.__init__(self, testcase)

    def finished_processing(self):
        pass
