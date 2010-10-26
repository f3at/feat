# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import messaging
import database


class Agency(object):
    
    def __init__(self):
        self._agents = []
        self._hosts = []
        self._shards = []

        self._messaging = messaging.Messaging()
        self._database = database.Database()

    def registerAgent(self, agent):
        self._agents.append(agent)
        agent._messaging = self._messaging.createConnection(agent)
        agent._database = self._database

    def unregisterAgent(self, agent):
        self._agents.remove(agent)
        agent._messaging.disconnect()
