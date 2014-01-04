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
import socket

from feat.common import formatable, enum
from feat.agents.application import feat

from zope.interface import Interface

__all__ = ["IDNSServerLabourFactory", "IDNSServerLabour", "RecordA",
           "RecordCNAME", "RecordType"]


class IDNSServerLabourFactory(Interface):

    def __call__(patron, notify_cfg, suffix, ip, ns, ns_ttl):
        '''
        @returns: L{IManagerLabour}
        '''


class IDNSServerLabour(Interface):

    def startup(port):
        '''Startups the labour, starting to listen
        on specified port for DNS queries.'''

    def cleanup():
        '''Cleanup the labour, stop listening for DNS queries.
        @rtype: Deferred'''

    def update_records(name, records):
        '''
        Update the dns records for the given name.

        @type records: list of L{_BaseRecord}
        '''

    def notify_slave():
        '''
        Order the labour to notify slaves about the modifications. Should
        be done at the end of modifications.
        '''


class RecordType(enum.Enum):
    record_A, record_CNAME = range(2)


class _BaseRecord(formatable.Formatable):

    formatable.field('ttl', None)
    formatable.field('ip', None)


@feat.register_restorator
class RecordA(_BaseRecord):

    type_name = 'dns_record_a'

    def __init__(self, ip=None, **kwargs):
        socket.inet_aton(ip) #this is to validate the IP
        _BaseRecord.__init__(self, ip=ip, **kwargs)

    @property
    def type(self):
        return RecordType.record_A


@feat.register_restorator
class RecordCNAME(_BaseRecord):

    type_name = 'dns_record_cname'

    @property
    def type(self):
        return RecordType.record_CNAME
