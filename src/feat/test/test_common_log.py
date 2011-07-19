# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import implements

from feat.common import log
from feat.interface.log import *

from . import common


class DummyLogKeeper(object):

    implements(ILogKeeper)

    def __init__(self):
        self.entries = []

    def do_log(self, level, object, category, format, args,
               depth=1, file_path=None, line_num=None):
        entry = (level, object, category, format, args, depth)
        self.entries.append(entry)


class BasicDummyLogger(log.Logger):
    pass


class CategorizedDummyLogger(log.Logger):
    log_category = "dummy"


class NamedDummyLogger(log.Logger):
    log_name = "spam"


class NamedAndCategorizedDummyLogger(log.Logger):
    log_category = "dummy"
    log_name = "spam"


class DummyLogProxy(log.LogProxy):
    pass


class TestLogging(common.TestCase):

    def testDefaultLogging(self):
        keeper = DummyLogKeeper()
        log.set_default(keeper)

        log.log("foo", "1")
        log.debug("bar", "2", 42)
        log.info("spam", "3")
        log.warning("bacon", "4", 2, 3, 5)
        log.error("eggs", "4")

        self.assertEqual(keeper.entries,
                         [(LogLevel.log, None, 'foo', '1', (), 1),
                          (LogLevel.debug, None, 'bar', '2', (42, ), 1),
                          (LogLevel.info, None, 'spam', '3', (), 1),
                          (LogLevel.warning, None, 'bacon', '4', (2, 3, 5), 1),
                          (LogLevel.error, None, 'eggs', '4', (), 1)])

    def testBasicLogging(self):
        keeper = DummyLogKeeper()
        obj = BasicDummyLogger(keeper)

        obj.log("1")
        obj.debug("2", 42)
        obj.info("3")
        obj.warning("4", 2, 3, 5)
        obj.error("4")

        self.assertEqual(keeper.entries,
                         [(LogLevel.log, None, None, '1', (), 1),
                          (LogLevel.debug, None, None, '2', (42, ), 1),
                          (LogLevel.info, None, None, '3', (), 1),
                          (LogLevel.warning, None, None, '4', (2, 3, 5), 1),
                          (LogLevel.error, None, None, '4', (), 1)])

    def testLogEntryWithCategory(self):
        keeper = DummyLogKeeper()
        obj = CategorizedDummyLogger(keeper)

        obj.log("1")
        obj.debug("2")
        obj.info("3")
        obj.warning("4")
        obj.error("4")

        self.assertEqual(keeper.entries,
                         [(LogLevel.log, None, 'dummy', '1', (), 1),
                          (LogLevel.debug, None, 'dummy', '2', (), 1),
                          (LogLevel.info, None, 'dummy', '3', (), 1),
                          (LogLevel.warning, None, 'dummy', '4', (), 1),
                          (LogLevel.error, None, 'dummy', '4', (), 1)])

    def testNamedLogEntry(self):
        keeper = DummyLogKeeper()
        obj = NamedDummyLogger(keeper)

        obj.log("1")
        obj.log_name = "beans"
        obj.debug("2")
        obj.log_name = "foo"
        obj.info("3")
        obj.log_name = "bar"
        obj.warning("4")
        obj.log_name = "bacon"
        obj.error("4")

        obj = NamedAndCategorizedDummyLogger(keeper)
        obj.log("1")
        obj.log_name = "beans"
        obj.debug("2")
        obj.log_name = "foo"
        obj.info("3")
        obj.log_name = "bar"
        obj.warning("4")
        obj.log_name = "bacon"
        obj.error("4")

        self.assertEqual(keeper.entries,
                         [(LogLevel.log, 'spam', None, '1', (), 1),
                          (LogLevel.debug, 'beans', None, '2', (), 1),
                          (LogLevel.info, 'foo', None, '3', (), 1),
                          (LogLevel.warning, 'bar', None, '4', (), 1),
                          (LogLevel.error, 'bacon', None, '4', (), 1),
                          (LogLevel.log, 'spam', 'dummy', '1', (), 1),
                          (LogLevel.debug, 'beans', 'dummy', '2', (), 1),
                          (LogLevel.info, 'foo', 'dummy', '3', (), 1),
                          (LogLevel.warning, 'bar', 'dummy', '4', (), 1),
                          (LogLevel.error, 'bacon', 'dummy', '4', (), 1)])

    def testLogKeeperProxy(self):
        keeper = DummyLogKeeper()
        proxy1 = DummyLogProxy(keeper)
        proxy2 = DummyLogProxy(proxy1)

        obj1 = NamedAndCategorizedDummyLogger(keeper)
        obj2 = NamedAndCategorizedDummyLogger(proxy1)
        obj3 = NamedAndCategorizedDummyLogger(proxy2)

        obj1.log("1")
        obj2.log("2")
        obj3.log("3")

        self.assertEqual(keeper.entries,
                         [(LogLevel.log, 'spam', 'dummy', '1', (), 1),
                          (LogLevel.log, 'spam', 'dummy', '2', (), 2),
                          (LogLevel.log, 'spam', 'dummy', '3', (), 3)])
