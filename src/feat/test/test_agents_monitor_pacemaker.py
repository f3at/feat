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
from zope.interface import implements

from feat.agents.monitor import pacemaker
from feat.common import journal, log, time

from feat.interface.agent import IAgent

from feat.test import common


class DummyDescriptor(object):

    def __init__(self, aid, iid):
        self.doc_id = aid
        self.instance_id = iid


class DummyPatron(journal.DummyRecorderNode, log.LogProxy, log.Logger):

    implements(IAgent)

    def __init__(self, logger, descriptor):
        journal.DummyRecorderNode.__init__(self)
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, logger)

        self.descriptor = descriptor
        self.calls = {}
        self.cid = 0

        self.messages = []

        self.poster = None

        self.time = time.time()

    ### Public Methods ###

    def do_calls(self):
        calls = self.calls.values()
        self.calls.clear()
        for _time, fun, args, kwargs in calls:
            fun(*args, **kwargs)

    ### IAgent Methods ###

    def initiate_protocol(self, factory, *args, **kwargs):
        if factory is pacemaker.HeartBeatPoster:
            self.poster = pacemaker.HeartBeatPoster(self, self)
            # Remove recipient
            args = args[1:]
            self.poster.initiate(*args, **kwargs)
            return self.poster

        if factory is pacemaker.HeartBeatTask:
            self.task = pacemaker.HeartBeatTask(self, self)
            self.task.initiate(*args, **kwargs)
            return self.task

        raise Exception("Unexpected protocol %r" % factory)

    def get_full_id(self):
        return "%s/%s" % (self.descriptor.doc_id, self.descriptor.instance_id)

    def get_descriptor(self):
        return self.descriptor

    def get_time(self):
        return self.time

    def _terminate(self, result):
        pass

    ### Mediums Methods ###

    def call_next(self, fun, *args, **kwargs):
        self.cid += 1
        self.calls[self.cid] = (0, fun, args, kwargs)
        return self.cid

    def call_later_ex(self, time, fun, args=(), kwargs={}, busy=True):
        self.cid += 1
        self.calls[self.cid] = (time, fun, args, kwargs)
        return self.cid

    def cancel_delayed_call(self, dc):
        if dc in self.calls:
            del self.calls[dc]

    def post(self, msg):
        self.messages.append(msg)


class TestPacemaker(common.TestCase):

    def testPacemaker(self):
        descriptor = DummyDescriptor("aid", "iid")
        patron = DummyPatron(self, descriptor)
        labour = pacemaker.Pacemaker(patron, "monitor", 3)
        labour.startup()

        self.assertEqual(len(patron.messages), 1)
        msg = patron.messages.pop()
        self.assertEqual(msg.payload, ("aid", patron.time, 0))
        call = patron.calls.itervalues().next()
        self.assertEqual(call[0], 3)

        patron.do_calls()

        self.assertEqual(len(patron.messages), 1)
        msg = patron.messages.pop()
        self.assertEqual(msg.payload, ("aid", patron.time, 1))
        self.assertEqual(len(patron.calls), 1)

        labour.cleanup()
