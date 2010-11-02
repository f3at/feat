# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4


class BaseMessage(object):
    
    reply_to_shard = None
    reply_to_key = None
    message_id = None
    protocol_id = None
    protocol_type = None
    expiration_time = None
    payload = {}

    def __init__(self, **kwargs):
        for key in kwargs:
            if key in self:
                self[key] = kwargs[key]
            else:
                raise AttributeError("Attribute %r not defined!" % key)


class ContractMessage(BaseMessage):
    
    protocol_type = 'Contract'


class RequestMessage(BaseMessage):
    
    protocol_type = 'Request'


class ResponseMessage(BaseMessage):
    
    protocol_type = 'Request'


# messages send by menager to contractor


class Announcement(ContractMessage):
    pass


class Rejection(ContractMessage):
    pass


class Grant(ContractMessage):
    pass


class Cancellation(ContractMessage):
    pass


class Acknowledgement(ContractMessage):
    pass


# messages send by contractor to manager

class Bid(ContractMessage):
    pass


class Refusal(ContractMessage):
    pass


class UpadeReport(ContractMessage):
    pass


class FinalReport(ContractMessage):
    pass


