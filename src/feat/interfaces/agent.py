# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from zope.interface import Interface


class IAgentMessaging(Interface):
   '''Methods necessary to implement to be part of messaging infrastracture'''

   def getId():
       '''Should return the id of the agent'''

   def getShardId():
       '''Should return the id of the shard the agent leaves in or None'''

   def onMessage():
       '''Called when the agent received the message'''



