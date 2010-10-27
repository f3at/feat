# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import messaging
import database
from twisted.python import log
from feat.interface.agent import IAgencyAgent, IAgentFactory
from feat.interface.agency import IAgency
from zope.interface import implements

class Agency(object):
    implements(IAgency)
    
    def __init__(self):
        self._agents = []
        # shard -> [ agents ]
        self._shards = {}

        self._messaging = messaging.Messaging()
        self._database = database.Database()

    def start_agent(self, factory, descriptor):
        factory = IAgentFactory(factory)
        medium = AgencyAgent(self, factory, descriptor)
        self._agents.append(medium)
        return medium

    def unregisterAgent(self, agent):
        self._agents.remove(agent)
        agent._messaging.disconnect()

    def joinedShard(self, agent, shard):
        shard_list = self._shards.get(shard, [])
        shard_list.append(agent)
        self._shards[shard] = shard_list

    def leftShard(self, agent, shard):
        shard_list = self._shards.get(shard, [])
        if agent in shard_list:
            shard_list.remove(agent)
        else:
            log.err('Was supposed to leave shard %r, but it was not there!' %\
                        shard)
        self._shards[shard] = shard_list


class AgencyAgent(object):
    implements(IAgencyAgent)

    def __init__(self, agency, factory, descriptor):
        
        self.agency = IAgency(agency)
        self.descriptor = descriptor
        self.agent = factory(self)

        self._messaging = agency._messaging.createConnection(self)
        self._database = agency._database

        self.joinShard()
        self.agent.initiate()
        
    def joinShard(self):
        shard = self.descriptor.shard
        self._messaging.createPersonalInterest(self.descriptor.uuid, shard)
        self.agency.joinedShard(self, shard)

    def leaveShard(self):
        interests = self._messaging.getInterestForShard(self.descriptor.shard)
        map(lambda interest: interest.revoke(), interests)
        self.agency.leftShard(self, self.descriptor.shard)
        self.descriptor.shard = None
        
    def on_message(self, message):
        pass
