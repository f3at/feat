
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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import tempfile
from feat.common import fcntl

from . import common


class TestFileLock(common.TestCase):

    def setUp(self):
        _, self.lock_path = tempfile.mkstemp()
        self.lock1 = open(self.lock_path, 'rb+')
        self.lock2 = open(self.lock_path, 'rb+')

    def testflockLock(self):
        self.assertTrue(fcntl.lock(self.lock1))
        self.assertFalse(fcntl.lock(self.lock2))

    def testflockUnlock(self):
        self.assertTrue(fcntl.lock(self.lock1))
        self.assertFalse(fcntl.lock(self.lock2))
        self.assertTrue(fcntl.unlock(self.lock1))
        self.assertTrue(fcntl.lock(self.lock2))

    def testflockUnlockedAfterClose(self):
        self.assertTrue(fcntl.lock(self.lock1))
        self.lock1.close()
        self.lock1 = open(self.lock_path, 'rb+')
        self.assertTrue(fcntl.lock(self.lock1))

    def testlockfLock(self):
        fcntl.LOCK_FN=fcntl.lockf
        # The lockf lock is per process, so trying to get a lock from the same
        # process will always succeed
        self.assertTrue(fcntl.lock(self.lock1))
        self.assertTrue(fcntl.lock(self.lock2))
        fcntl.LOCK_FN=fcntl.flock
