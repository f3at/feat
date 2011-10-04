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
from twisted.spread import pb

from feat.common import decorator, fiber, first
from feat.agents.base import document, registry, resource


field = document.field


@decorator.parametrized_class
def register(klass, name):
    klass.type_name = name
    klass.document_type = name
    return document.register(klass)


def lookup(name):
    return document.lookup(name)


@document.register
class Descriptor(document.Document, pb.Copyable):

    document_type = 'descriptor'
    # Shard identifier (unicode)
    document.field('shard', None)
    # List of allocations
    document.field('allocations', dict())
    # List of partners
    document.field('partners', list())
    # The counter incremented at the agents startup
    document.field('instance_id', 0)
    # Field set by monitor agent while restarting the agent
    document.field('under_restart', None)
    # Resources allocated by host agent for this agent
    document.field('resources', None)

    ### methods usefull for descriptor manipulations done ###
    ### by agents who don't own them                      ###

    def remove_host_partner(self, agent):
        '''
        Helper method generating fiber which will remove host partner from the
        descriptor. This is used by different agents before triggering the
        restart of the agent. Because the agent died violently he had no time
        to apply changes to his descriptor and this job needs to be done for
        him before restart.
        '''
        find = first(x for x in self.partners if x.role == 'host')
        if find is not None:
            self.partners.remove(find)
            return agent.save_document(self)
        else:
            agent.warning(
                "Agent %r didn't have a partner with a role='host' in his "
                "descriptor. This is kind of weird. His partners: %r",
                self.document_type, self.partners)
            return fiber.succeed(self)

    def set_shard(self, agent, shard):
        self.shard = shard
        return agent.save_document(self)

    def extract_resources(self):
        if self.resources:
            resp = dict()
            for name, value in self.resources.iteritems():
                if resource.IAllocatedResource.providedBy(value):
                    value = value.extract_init_arguments()
                resp[name] = value
            return resp
        else:
            return registry.registry_lookup(self.document_type).resources
