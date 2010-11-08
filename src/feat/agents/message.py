# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4


class BaseMessage(object):
    
    reply_to = None
    message_id = None
    protocol_id = None
    protocol_type = None
    expiration_time = None
    session_id = None
    payload = {}

    def __init__(self, **kwargs):
        for key in kwargs:
            self.__getattribute__(key) # this can throw AttributeError
            self.__setattr__(key, kwargs[key])



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

    bid_index = None # index of the bid we are granting
    update_report = None # set it to number to receive frequent reports


class Cancellation(ContractMessage):

    reason = None # why do we cancel?


class Acknowledgement(ContractMessage):
    pass


# messages send by contractor to manager

class Bid(ContractMessage):
    
    # list of bids (usual single element)
    bids = []


class Refusal(ContractMessage):
    pass


class UpdateReport(ContractMessage):
    pass


class FinalReport(ContractMessage):
    pass


