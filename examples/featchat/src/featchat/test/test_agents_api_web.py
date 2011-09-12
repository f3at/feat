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
from twisted.web.client import getPage
from twisted.web.error import Error

from feat.test import common
from feat.common import defer
from feat.common.serialization import json

from featchat.agents.api import web

from featchat.agents.api.interface import IWebAgent


class DummyAgent(object):
    implements(IWebAgent)

    def __init__(self):
        self.stop_failing()

    def start_failing(self):
        self._should_work = False

    def stop_failing(self):
        self._should_work = True

    def get_list_for_room(self, name):
        if self._should_work:
            res = {'session1': u'some.ip', 'session2': u'other.ip'}
            return defer.succeed(res)
        else:
            return defer.fail(ValueError('blah!'))

    def get_url_for_room(self, name):
        if self._should_work:
            res = {'url': u'20.30.10.30:1003', 'session_id': u'sth'}
            return defer.succeed(res)
        else:
            return defer.fail(ValueError('blah!'))

    def get_room_list(self):
        return defer.succeed([u'room1', u'room2'])


class TestRealWeb(common.TestCase):

    def setUp(self):
        self.agent = DummyAgent()
        self.server = web.ServerWrapper(self.agent, 0)
        self.server.start()
        self.url_temp = 'http://localhost:%d/%%s' % self.server.listening_port

    @defer.inlineCallbacks
    def testURLs(self):
        res = yield self._get_page('rooms')
        self.assertEqual(['room1', 'room2'], res)

        res = yield self._get_page('rooms/some_room')
        expected = {'session1': u'some.ip', 'session2': u'other.ip'}
        self.assertEqual(expected, res)

        self.agent.start_failing()
        d = self._get_page('rooms/some_room')
        self.assertFailure(d, Error)
        yield d

        self.agent.stop_failing()
        res = yield self._get_page('rooms/some_room', method='POST')
        exp = {'url': u'20.30.10.30:1003', 'session_id': 'sth'}
        self.assertEqual(exp, res)

    def _get_page(self, path, *args, **kwargs):
        d = getPage(self._url(path), *args, **kwargs)
        d.addCallback(json.unserialize)
        return d

    def _url(self, path):
        return self.url_temp % (path)

    def tearDown(self):
        self.server.stop()
