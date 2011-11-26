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

import os

from feat.common import log

from _noarch_run import *


DEFAULT_RUN_DIR = os.environ["TEMP"]


def status(processName, rundir=DEFAULT_RUN_DIR, process_type=PROCESS_TYPE):
    pass


def stop(processName, rundir='/tmp', process_type=PROCESS_TYPE):
    pass


def daemonize(stdin=os.devnull, stdout=os.devnull, stderr=os.devnull):
    raise NotImplementedError("Daemonizing not supported on win32")


def get_pid(rundir, process_type=PROCESS_TYPE, name=None):
    raise NotImplementedError("Signaling not supported on win32")


def signal_pid(pid, signum):
    raise NotImplementedError("Signaling not supported on win32")


def term_pid(pid):
    raise NotImplementedError("Signaling not supported on win32")


def kill_pid(pid):
    raise NotImplementedError("Signaling not supported on win32")


def check_pid_running(pid):
    raise NotImplementedError("Signaling not supported on win32")


def get_pidpath(rundir, process_type, name=None):
    """
    Get the full path to the pid file for the given process type and name.
    """
    path = os.path.join(rundir, '%s.pid' % process_type)
    if name:
        path = os.path.join(rundir, '%s.%s.pid' % (process_type, name))
    log.debug('common', 'get_pidpath for type %s, name %r: %s'
              % (process_type, name, path))
    return path
