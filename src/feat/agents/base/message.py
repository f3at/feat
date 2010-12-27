# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy
import types

from feat.common import serialization


@serialization.register
class BaseMessage(serialization.Serializable):

    reply_to = None
    message_id = None
    protocol_id = None
    protocol_type = None
    expiration_time = None
    sender_id = None
    receiver_id = None
    payload = {}

    def __init__(self, **kwargs):
        for key, default in self.iter_fields():
            value = kwargs.pop(key, default)
            setattr(self, key, value)

        if len(kwargs) > 0:
            raise AttributeError('Unknown message field: %r', kwargs.keys())

    def clone(self):
        return copy.copy(self)

    def iter_fields(self):
        for key in dir(type(self)):
            if key.startswith('_'):
                continue
            default = getattr(type(self), key)
            if isinstance(default, (types.FunctionType, types.MethodType, )):
                continue
            yield key, copy.copy(default)

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        for key, default in self.iter_fields():
            if getattr(self, key) != getattr(other, key):
                return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        d = dict()
        for key, default in self.iter_fields():
            d[key] = getattr(self, key)
        return "<%r, %r>" % (type(self), d)


@serialization.register
class ContractMessage(BaseMessage):

    protocol_type = 'Contract'


@serialization.register
class RequestMessage(BaseMessage):

    protocol_type = 'Request'


@serialization.register
class ResponseMessage(BaseMessage):

    protocol_type = 'Request'


# messages send by menager to contractor


@serialization.register
class Announcement(ContractMessage):
    pass


@serialization.register
class Rejection(ContractMessage):
    pass


@serialization.register
class Grant(ContractMessage):

    bid_index = None # index of the bid we are granting
    update_report = None # set it to number to receive frequent reports


@serialization.register
class Cancellation(ContractMessage):

    reason = None # why do we cancel?


@serialization.register
class Acknowledgement(ContractMessage):
    pass


# messages sent by contractor to manager


@serialization.register
class Bid(ContractMessage):

    # list of bids (usual single element)
    bids = []


@serialization.register
class Refusal(ContractMessage):
    pass


@serialization.register
class UpdateReport(ContractMessage):
    pass


@serialization.register
class FinalReport(ContractMessage):
    pass
