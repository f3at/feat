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


# Dummy constants overridden by platform implementation
SIGABRT = None
SIGALRM = None
SIGBUS = None
SIGCHLD = None
SIGCLD = None
SIGCONT = None
SIGFPE = None
SIGHUP = None
SIGILL = None
SIGINT = None
SIGIO = None
SIGIOT = None
SIGKILL = None
SIGPIPE = None
SIGPOLL = None
SIGPROF = None
SIGPWR = None
SIGQUIT = None
SIGRTMAX = None
SIGRTMIN = None
SIGSEGV = None
SIGSTOP = None
SIGSYS = None
SIGTERM = None
SIGTRAP = None
SIGTSTP = None
SIGTTIN = None
SIGTTOU = None
SIGURG = None
SIGUSR1 = None
SIGUSR2 = None
SIGVTALRM = None
SIGWINCH = None
SIGXCPU = None
SIGXFSZ = None
SIG_DFL = None
SIG_IG = None


def signal(sig, action):
    """Dummy declaration overridden in platform specific implementation."""


def unregister(sig, action):
    """Dummy declaration overridden in platform specific implementation."""


def reset():
    """Dummy declaration overridden in platform specific implementation."""
