# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.spread import pb, jelly

from feat.common import decorator, fiber, first
from feat.agents.base import document


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


jelly.globalSecurity.allowInstancesOf(Descriptor)
