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
import inspect
import sys
import re

from feat import applications


def build(document_type, **options):
    '''Builds document of selected class with default parameters for testing'''

    doc_class = applications.lookup_descriptor(document_type)
    if not doc_class:
        raise AttributeError("Unknown document type: %r", document_type)

    name = "%s_factory" % re.sub(r'-', '_', document_type.lower())
    module = sys.modules[__name__]
    members = inspect.getmembers(module, lambda x: inspect.isfunction(x) and\
                                 x.__name__ == name)
    if len(members) != 1:
        factory = descriptor_factory
    else:
        _, factory = members[0]
    return doc_class(**factory(**options))


def descriptor_factory(**options):
    options['shard'] = options.get('shard', u'lobby')
    return options


def shard_agent_factory(**options):
    options = descriptor_factory(**options)
    return options


def host_agent_factory(**options):
    options = descriptor_factory(**options)
    return options


def base_agent_factory(**options):
    options = descriptor_factory(**options)
    return options
