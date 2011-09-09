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
from zope.interface import Interface

__all__ = ["IDNSServerLabourFactory", "IDNSServerLabour"]


class IDNSServerLabourFactory(Interface):

    def __call__(patron, resolver, slaves, suffix):
        '''
        @returns: L{IManagerLabour}
        '''


class IDNSServerLabour(Interface):

    def initiate():
        '''Initialises the labour.'''

    def startup(port):
        '''Startups the labour, starting to listen
        on specified port for DNS queries.'''

    def cleanup():
        '''Cleanup the labour, stop listening for DNS queries.'''

    def notify_slaves(self):
        '''Notify slaves for zones updates'''
