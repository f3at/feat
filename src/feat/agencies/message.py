# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.

import copy
import operator

from zope.interface import implements

from feat.common import serialization, formatable

from feat.agencies.interface import *


class FirstMessageMixin(formatable.Formatable):

    implements(IFirstMessage)

    # field used by nested protocols to identify that incoming
    # dialog has already been handled by the shard
    formatable.field('traversal_id', None)


@serialization.register
class BaseMessage(formatable.Formatable):

    formatable.field('message_id', None)
    # IRecipient
    formatable.field('recipient', None)
    formatable.field('protocol_id', None)
    formatable.field('protocol_type', None)
    formatable.field('expiration_time', None)
    formatable.field('payload', dict())

    def clone(self):
        """Returns an exact copy of the message.
        KNOW WAT YOU ARE DOING, some special fields
        SHOULD NOT be the same in different messages."""
        return copy.deepcopy(self)

    def duplicate(self):
        """Returns a duplicate of the message safe to modify
        and use for another message."""
        msg = self.clone()
        msg.message_id = None
        return msg

    def duplication_recipient(self):
        '''Returns a recipient to whom the duplication
        message should be send or None.'''
        return None

    def duplication_message(self):
        '''Returns a duplication message or None'''
        return None

    def get_msg_class(self):
        '''Helper giving formated information about which protocol does
        this message belong to (for logging purpose only).'''
        return "%s.%s.%s" % (self.protocol_type, self.protocol_id,
                             type(self).__name__, )

    def __repr__(self):
        d = dict()
        for field in self._fields:
            d[field.name] = getattr(self, field.name)
        return "<%r, %r>" % (type(self), d)


@serialization.register
class DialogMessage(BaseMessage):

    implements(IDialogMessage)

    formatable.field('reply_to', None)
    formatable.field('sender_id', None)
    formatable.field('receiver_id', None)

    def duplicate(self):
        msg = BaseMessage.duplicate(self)
        msg.reply_to = None
        return msg

    def duplication_recipient(self):
        return self.reply_to

    def duplication_message(self):
        msg = Duplicate()
        msg.protocol_id = self.protocol_id
        msg.protocol_type = self.protocol_type
        msg.expiration_time = self.expiration_time
        msg.receiver_id = self.sender_id
        return msg


@serialization.register
class Duplicate(DialogMessage):
    '''
    Sent as the reply to a contract announcement which the agent have already
    served (matched by traversal_id field).
    '''


@serialization.register
class ContractMessage(DialogMessage):

    formatable.field('protocol_type', 'Contract')


@serialization.register
class RequestMessage(DialogMessage, FirstMessageMixin):

    formatable.field('protocol_type', 'Request')


@serialization.register
class ResponseMessage(DialogMessage):

    formatable.field('protocol_type', 'Request')


# messages send by menager to contractor


@serialization.register
class Announcement(ContractMessage, FirstMessageMixin):

    # Increased every time the contract is nested to the other shard
    formatable.field('level', 0)
    # Used in nested contracts. How many times can contract be nested.
    # None = infinity
    formatable.field('max_distance', None)


@serialization.register
class Rejection(ContractMessage):
    pass


@serialization.register
class Grant(ContractMessage):
    pass


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
    def pick_best(bids, number=1):
        '''
        Picks the cheapest bids from the list provided.
        @param bids: list of bids to choose from
        @param number: number of bids to choose
        @returns: the list of bids
        '''
        for bid in bids:
            assert isinstance(bid, Bid)

        costs = sorted(map(lambda x: (x.payload['cost'], x), bids),
                       key=operator.itemgetter(0))
        picked = list()

        for x in range(number):
            try:
                best, bid = costs.pop(0)
            except IndexError:
                break
            picked.append(bid)

        return picked


@serialization.register
class Refusal(ContractMessage):
    pass


@serialization.register
class UpdateReport(ContractMessage):
    pass


@serialization.register
class FinalReport(ContractMessage):
    pass


# Message for notifications


@serialization.register
class Notification(BaseMessage, FirstMessageMixin):

    formatable.field('protocol_type', 'Notification')
