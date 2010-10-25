# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
#
# Flumotion - a streaming media server
# Copyright (C) 2004,2005,2006,2007 Fluendo, S.L. (www.fluendo.com).
# All rights reserved.

# This file may be distributed and/or modified under the terms of
# the GNU General Public License version 2 as published by
# the Free Software Foundation.
# This file is distributed without any warranty; without even the implied
# warranty of merchantability or fitness for a particular purpose.
# See "LICENSE.GPL" in the source distribution for more information.

# Licensees having purchased or holding a valid Flumotion Advanced
# Streaming Server license may use this file in accordance with the
# Flumotion Advanced Streaming Server Commercial License Agreement.
# See "LICENSE.Flumotion" in the source distribution for more information.

# Headers in this file shall remain intact.

import messaging
import database


class IAgent(Interface):
    
    def getId(self):
        """Get the UUID of the agent"""

    def onMessage(self, message):
        """Implement to get messages"""


class Wrapper(object):
    
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
