# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy

from feat.common import serialization, formatable


@serialization.register
class BaseMessage(formatable.Formatable):

    formatable.field('reply_to', None)
    formatable.field('message_id', None)
    formatable.field('protocol_id', None)
    formatable.field('protocol_type', None)
    formatable.field('expiration_time', None)
    formatable.field('sender_id', None)
    formatable.field('receiver_id', None)
    formatable.field('payload', dict())

    def clone(self):
        return copy.deepcopy(self)

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        for field in self._fields:
            if getattr(self, field.name) != getattr(other, field.name):
                return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        d = dict()
        for field in self._fields:
            d[field.name] = getattr(self, field.name)
        return "<%r, %r>" % (type(self), d)


@serialization.register
class ContractMessage(BaseMessage):

    formatable.field('protocol_type', 'Contract')


@serialization.register
class RequestMessage(BaseMessage):

    formatable.field('protocol_type', 'Request')


@serialization.register
class ResponseMessage(BaseMessage):

    formatable.field('protocol_type', 'Request')


# messages send by menager to contractor


@serialization.register
class Announcement(ContractMessage):
    pass


@serialization.register
class Rejection(ContractMessage):
    pass


@serialization.register
class Grant(ContractMessage):

     # set it to number to receive frequent reports
    formatable.field('update_report', None)


@serialization.register
class Cancellation(ContractMessage):

    # why do we cancel?
    formatable.field('reason', None)


@serialization.register
class Acknowledgement(ContractMessage):
    pass


# messages sent by contractor to manager


@serialization.register
class Bid(ContractMessage):

    @staticmethod
    def pick_best(bids):
        assert len(bids) > 0
        for bid in bids:
            assert isinstance(bid, Bid)

        costs = map(lambda x: x.payload['cost'], bids)
        best = min(costs)
        return filter(lambda x: x.payload['cost'] == best, bids)[0]


@serialization.register
class Refusal(ContractMessage):
    pass


@serialization.register
class UpdateReport(ContractMessage):
    pass


@serialization.register
class FinalReport(ContractMessage):
    pass
