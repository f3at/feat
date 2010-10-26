# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import messaging
import database
from twisted.python import log


class Agency(object):
    
    def __init__(self):
        self._agents = []
        # shard -> [ agents ]
        self._shards = {}

        self._messaging = messaging.Messaging()
        self._database = database.Database()

    def registerAgent(self, plain_agent):
        agent = AgencyAgent(plain_agent, self)
        self._agents.append(agent)

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
    '''methods that agency may want to run upon agent and vice versa'''

    def __init__(self, agent, agency):
        self.agent = agent
        self.agency = agency

        self._messaging = agency._messaging.createConnection(self)
        self._database = agency._database

        agent.init(self)
        
    def joinShard(self, shard):
        self._messaging.createPersonalInterest(self.agent.uuid, shard)
        self.agency.joinedShard(self, shard)

    def leaveShard(self, shard):
        interests = self._messaging.getInterestForShard(shard)
        map(lambda interest: interest.revoke(), interest)
        self.agency.leftShard(self, shard)

        
    def getId(self):
        '''called by messaging layer to resolve queue name'''
        return self.agent.uuid

    def onMessage(self, message):
        pass
