# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import uuid


class Descriptor(object):
    
    def __init__(self, uid=None):
        self.uuid = uid or uuid.uuid1()


class BaseAgent(object):
    
    def __init__(self, descriptor, shard='lobby'):
        self.uuid = descriptor.uuid
        self.shard = shard

    def init(self, agency):
        self.agency = agency
        agency.joinShard(self.shard)
        

#class ShardAgent(BaseAgent):
    
