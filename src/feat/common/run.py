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


def status(processName, rundir=None, process_type=None):
    """Dummy declaration overridden in platform specific implementation."""


def stop(processName, rundir=None, process_type=None):
    """Dummy declaration overridden in platform specific implementation."""


def daemonize(stdin=None, stdout=None, stderr=None):
    """Dummy declaration overridden in platform specific implementation."""


def get_pid(rundir, process_type=None, name=None):
    """Dummy declaration overridden in platform specific implementation."""


def signal_pid(pid, signum):
    """Dummy declaration overridden in platform specific implementation."""


def term_pid(pid):
    """Dummy declaration overridden in platform specific implementation."""


def kill_pid(pid):
    """Dummy declaration overridden in platform specific implementation."""


def check_pid_running(pid):
    """Dummy declaration overridden in platform specific implementation."""


def get_pidpath(rundir, process_type, name=None):
    """Dummy declaration overridden in platform specific implementation."""


def acquire_pidfile(rundir, process_type=None, name=None):
    """Dummy declaration overridden in platform specific implementation."""


def write_pidfile(rundir, process_type=None,
                  name=None, file=None): #@ReservedAssignment
    """Dummy declaration overridden in platform specific implementation."""


def delete_pidfile(rundir, process_type=None, name=None, force=False):
    """Dummy declaration overridden in platform specific implementation."""


def wait_pidfile(rundir, process_type=None, name=None):
    """Dummy declaration overridden in platform specific implementation."""


def wait_for_term():
    """Dummy declaration overridden in platform specific implementation."""
