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
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid

from twisted.python import failure
from zope.interface import implements

from feat.agents.base import replay
from feat.common import log, enum, time, serialization, defer, adapter
from feat.agencies import common, protocols, message, recipient

from feat.agencies.interface import IAgencyListenerInternal
from feat.agencies.interface import IAgencyProtocolInternal
from feat.agencies.interface import IAgencyInitiatorFactory
from feat.agencies.interface import IAgencyInterestedFactory
from feat.agencies.interface import IAgencyInterestInternalFactory
from feat.interface.serialization import ISerializable
from feat.interface.protocols import ProtocolFailed
from feat.interface.contracts import ContractState
from feat.interface.manager import IAgencyManager, IManagerFactory
from feat.interface.contractor import IAgencyContractor, IContractorFactory
from feat.interface.recipient import IRecipients, RecipientType


class ContractorState(enum.Enum):
    '''
    bid - Bid has been received
    refused - Refusal has been received
    rejected - Bid has been rejected
    elected - Bid has been elected to be handed over
    granted - Grant has been sent
    completed - FinalReport has been received
    cancelled - Sent or received Cancellation
    acknowledged - Ack has been sent
    '''

    (bid, refused, rejected, elected, granted,
     completed, cancelled, acknowledged) = range(8)


class ManagerContractor(common.StateMachineMixin, log.Logger):
    '''
    Represents the contractor from the point of view of the manager
    '''

    def __init__(self, manager, bid, state=None):
        log.Logger.__init__(self, manager)
        common.StateMachineMixin.__init__(self)
        self._set_state(state or ContractorState.bid)
        self.bid = bid
        self.report = None
        self.manager = manager
        self.recipient = recipient.IRecipient(bid)

        key = bid.reply_to.key
        if key in self.manager.contractors:
            raise RuntimeError('Contractor for the bid already registered!')
        self.manager.contractors[key] = self

    ### Private Methods ###

    def _send_message(self, msg):
        self.log('Sending message: %r to contractor: %r',
                 msg, self.recipient.key)
        self.manager.send_message(msg, recipients=self.recipient,
                                  remote_id=self.bid.sender_id)

    def _on_report(self, report):
        self.report = report

    def on_event(self, msg):
        mapping = {
            message.Rejection:\
                {'method': self._send_message,
                 'state_before': ContractorState.bid,
                 'state_after': ContractorState.rejected},
            message.Grant:\
                {'method': self._send_message,
                 'state_before': ContractorState.bid,
                 'state_after': ContractorState.granted},
            message.Cancellation:\
                {'method': self._send_message,
                 'state_before': [ContractorState.granted,
                                  ContractorState.completed],
                 'state_after': ContractorState.cancelled},
            message.Acknowledgement:\
                {'method': self._send_message,
                 'state_before': ContractorState.completed,
                 'state_after': ContractorState.acknowledged},
            message.FinalReport:\
                {'method': self._on_report,
                 'state_before': ContractorState.granted,
                 'state_after': ContractorState.completed}}
        handler = self._event_handler(mapping, msg)
        if callable(handler):
            handler(msg)


class ManagerContractors(dict):

    def with_state(self, *states):
        return filter(lambda x: x.state in states, self.values())

    def by_message(self, msg):
        key = msg.reply_to.key
        return self.get(key, None)

    def get_bids(self):
        return self.with_state(ContractorState.bid)

    def get_expiration_time(self):
        return max([x.bid.expiration_time
                    for x in self.with_state(ContractorState.bid)])


class AgencyManager(common.AgencyMiddleBase):

    implements(ISerializable, IAgencyManager,
               IAgencyProtocolInternal, IAgencyListenerInternal)

    type_name = "manager-medium"

    error_state = ContractState.wtf

    def __init__(self, agency_agent, factory, recipients, *args, **kwargs):
        common.AgencyMiddleBase.__init__(self, agency_agent, factory)

        self.recipients = IRecipients(recipients)
        self.expected_bids = self._count_expected_bids(self.recipients)
        self.args = args
        self.kwargs = kwargs

        self.contractors = ManagerContractors()

    # IAgencyManager stuff

    def initiate(self):
        self.manager = self.factory(self.agent.get_agent(), self)
        self.set_protocol_id(self.manager.protocol_id)
        self._set_state(ContractState.initiated)

        timeout = time.future(self.manager.initiate_timeout)
        error = self.create_expired_error(
            "Timeout exceeded waiting for initiate() to send the announcement")
        self.set_timeout(timeout, ContractState.wtf,
                         self.finalize, failure.Failure(error))

        self.call_agent_side(self.manager.initiate, *self.args,
                             ensure_state=ContractState.initiated,
                             **self.kwargs)

        return self.manager

    ### IAgencyManager Methods ###

    @replay.named_side_effect('AgencyManager.announce')
    def announce(self, announce):
        if not self._ensure_state(ContractState.initiated):
            return

        announce = announce.duplicate()
        self.debug("Sending announcement %r", announce)
        assert isinstance(announce, message.Announcement)

        if announce.traversal_id is None:
            announce.traversal_id = str(uuid.uuid1())

        self._set_state(ContractState.announced)

        exp_time = time.future(self.manager.announce_timeout)
        bid = self.send_message(announce, exp_time)

        self.set_timeout(exp_time, None, self._on_announce_expire)

        return bid

    @replay.named_side_effect('AgencyManager.reject')
    def reject(self, bid, rejection=None):
        if not self._ensure_state([ContractState.announced,
                                   ContractState.granted,
                                   ContractState.closed]):
            return

        contractor = self.contractors.by_message(bid)
        if not rejection:
            rejection = message.Rejection()
        else:
            rejection = rejection.duplicate()
        contractor.on_event(rejection)

    @serialization.freeze_tag('AgencyManager.grant')
    @replay.named_side_effect('AgencyManager.grant')
    def grant(self, grants):
        if not self._ensure_state([ContractState.closed,
                                   ContractState.announced]):
            return

        if not isinstance(grants, list):
            grants = [grants]
        # clone the grant messages, not to mess with the
        # state on the agent side
        grants = [(bid, grant.duplicate(), ) for bid, grant in grants]

        self._set_state(ContractState.granted)

        expiration_time = time.future(self.manager.grant_timeout)
        self.set_timeout(expiration_time, ContractState.aborted,
                         self._on_grant_expire)

        # send a grant event to the contractors
        for bid, grant in grants:
            grant.expiration_time = expiration_time
            contractor = self.contractors.by_message(bid)
            contractor.on_event(grant)

        # send the rejections to all the contractors we are not granting
        for contractor in self.contractors.with_state(ContractorState.bid):
            contractor.on_event(message.Rejection())

    @serialization.freeze_tag('AgencyManager.elect')
    @replay.named_side_effect('AgencyManager.elect')
    def elect(self, bid):
        contractor = self.contractors.by_message(bid)
        if not contractor:
            self.debug('Asked to elect() an unknown bid. Ignoring.')
            return
        contractor._set_state(ContractorState.elected)

    @replay.named_side_effect('AgencyManager.cancel')
    def cancel(self, reason=None):
        if not self._ensure_state([ContractState.granted,
                                   ContractState.cancelled]):
            return
        self._set_state(ContractState.cancelled)

        to_cancel = self.contractors.with_state(\
                        ContractorState.granted, ContractorState.completed)
        for contractor in to_cancel:
            cancellation = message.Cancellation(reason=reason)
            contractor.on_event(cancellation)

        self._run_and_terminate(self.manager.cancelled, cancellation,
                                ensure_state=ContractState.cancelled)

    @replay.named_side_effect('AgencyManager.terminate')
    def terminate(self, result=None):
        # send the rejections to all the contractors
        for contractor in self.contractors.with_state(ContractorState.bid):
            contractor.on_event(message.Rejection())

        if not self._cmp_state([ContractState.expired,
                                ContractState.cancelled,
                                ContractState.aborted,
                                ContractState.wtf]):
            self._set_state(ContractState.terminated)
            self.finalize(result)

    @replay.named_side_effect('AgencyManager.get_bids')
    def get_bids(self):
        contractors = self.contractors.with_state(ContractorState.bid)
        return [x.bid for x in contractors]

    @replay.named_side_effect('AgencyManager.get_recipients')
    def get_recipients(self):
        return self.recipients

    ### IAgencyProtocolInternal Methods ###

    def get_agent_side(self):
        return self.manager

    ### IAgencyListenerInternal Methods ###

    def on_message(self, msg):
        mapping = {
            message.Bid:\
                {'method': self._on_bid,
                 'state_after': ContractState.announced,
                 'state_before': ContractState.announced},
            message.Refusal:\
                {'method': self._on_refusal,
                 'state_after': ContractState.announced,
                 'state_before': ContractState.announced},
            message.Duplicate:\
                {'method': self._on_duplicate,
                 'state_after': ContractState.announced,
                 'state_before': ContractState.announced},
            message.FinalReport:\
                {'method': self._on_report,
                 'state_after': ContractState.granted,
                 'state_before': ContractState.granted},
            message.Cancellation:\
                {'method': self._on_cancel,
                 'state_before': ContractState.granted,
                 'state_after': ContractState.cancelled},
        }
        handler = self._event_handler(mapping, msg)
        if callable(handler):
            handler(msg)

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Hooks for events (timeout and messages comming in) ###

    def _on_grant_expire(self):
        self._set_state(ContractState.aborted)
        return self._run_and_terminate(self.manager.aborted,
                                       ensure_state=ContractState.aborted)

    def _on_announce_expire(self):
        self.log('Timeout expired, closing the announce window')
        if not self._ensure_state(ContractState.announced):
            return
        self._goto_closed_or_expired()

    def _on_bid(self, bid):
        self.log('Received bid %r', bid)
        ManagerContractor(self, bid)
        d = self.manager.bid(bid)
        if isinstance(d, defer.Deferred):
            d.addCallback(defer.drop_param, self._check_if_should_goto_close)
            return d
        else:
            self._check_if_should_goto_close()

    def _on_refusal(self, refusal):
        self.log('Received refusal  %r', refusal)
        ManagerContractor(self, refusal, ContractorState.refused)
        self._check_if_should_goto_close()

    def _on_duplicate(self, duplicate):
        contractor = self.contractors.by_message(duplicate)
        if contractor:
            self.log("Ignoring duplicate, we already received a bid"
                     " from this contractor.")
        else:
            self._on_refusal(duplicate)

    def _on_report(self, report):
        self.log('Received report: %r', report)

        contractor = self.contractors.by_message(report)
        if not contractor:
            self.warning("Couldn't find a contractor matching the report: %r "
                         ".Contractors are: %r", report,
                         self.contractors.keys())
            return False
        contractor.on_event(report)
        if len(self.contractors.with_state(ContractorState.granted)) == 0:
            self._on_complete()

    def _on_cancel(self, cancellation):
        self.log('Received cancellation: %r. Reason: %r',
                 cancellation, cancellation.reason)

        contractor = self.contractors.by_message(cancellation)
        if not contractor:
            self.warning("Couldn't find a contractor matching the "
                         "cancellation: %r .Contractors are: %r", cancellation,
                         self.contractors.keys())
            return False

        reason = "Other contractor cancelled the job with reason: %s" %\
                 cancellation.reason
        self.cancel(reason)

    def _on_complete(self):
        self.log('All Reports received. Sending ACKs')
        if not self._ensure_state(ContractState.granted):
            return
        self._set_state(ContractState.completed)
        self.cancel_timeout()

        contractors = self.contractors.with_state(ContractorState.completed)
        for contractor in contractors:
            ack = message.Acknowledgement()
            contractor.on_event(ack)

        reports = map(lambda x: x.report, contractors)
        d = self.manager.completed(reports)
        if isinstance(d, defer.Deferred):
            d.addCallback(self.finalize)
        else:
            self.finalize(d)

    ### Private Methods ###

    def _check_if_should_goto_close(self):
        if self._cmp_state(ContractState.terminated):
            return
        if self.expected_bids and len(self.contractors) >= self.expected_bids:
            self.cancel_timeout()
            self._goto_closed_or_expired()

    def _goto_closed_or_expired(self):
        if len(self.contractors.with_state(ContractorState.bid)) > 0:
            self._close_announce_period()
        else:
            self._set_state(ContractState.expired)
            self._run_and_terminate(self.manager.expired,
                                    ensure_state=ContractState.expired)

    def _close_announce_period(self):
        expiration_time = self.contractors.get_expiration_time()
        self.set_timeout(expiration_time, ContractState.expired,
                         self._run_and_terminate, self.manager.expired)
        self._set_state(ContractState.closed)
        self.call_agent_side(self.manager.closed,
                             ensure_state=ContractState.closed)

    def _count_expected_bids(self, recipients):
        '''
        Count the expected number of bids (after receiving them we close the
        contract. If the recipient type is broadcast return None which denotes
        unknown number of bids (contract will be closed after timeout).
        '''
        count = 0
        for recp in recipients:
            if recp.type == RecipientType.broadcast:
                return None
            count += 1
        return count


class AgencyContractor(common.AgencyMiddleBase):

    implements(ISerializable, IAgencyContractor, IAgencyListenerInternal)

    type_name = "contractor-medium"

    error_state = ContractState.wtf

    def __init__(self, agency_agent, factory, announcement, *args, **kwargs):
        common.AgencyMiddleBase.__init__(self, agency_agent, factory,
                                         remote_id=announcement.sender_id,
                                         protocol_id=announcement.protocol_id)

        assert isinstance(announcement, message.Announcement), \
               type(announcement)

        self.args = args
        self.kwargs = kwargs
        self.announce = announcement
        self.recipients = announcement.reply_to

    def initiate(self):
        contractor = self.factory(self.agent.get_agent(), self)

        self.contractor = contractor
        self._set_state(ContractState.initiated)

        self.call_agent_side(self.contractor.initiate,
                             *self.args,
                             ensure_state=ContractState.initiated,
                             **self.kwargs)
        return contractor

    ### IAgencyContractor Methods ###

    @serialization.freeze_tag('AgencyContractor.bid')
    @replay.named_side_effect('AgencyContractor.bid')
    def bid(self, bid):
        if not self._ensure_state(ContractState.announced):
            return

        bid = bid.duplicate()
        self.debug("Sending bid %r", bid)
        self._set_state(ContractState.bid)

        expiration_time = time.future(self.contractor.bid_timeout)
        self.own_bid = self.send_message(bid, expiration_time)

        self.set_timeout(expiration_time, ContractState.expired,
                         self._run_and_terminate, self.contractor.bid_expired)

        return self.own_bid

    @serialization.freeze_tag('AgencyContractor.handover')
    @replay.named_side_effect('AgencyContractor.handover')
    def handover(self, bid):
        if not self._ensure_state(ContractState.announced):
            return

        new_bid = bid.duplicate()
        new_bid.reply_to = bid.reply_to
        self.debug('Sending bid of the nested contractor: %r.', new_bid)
        self._set_state(ContractState.delegated)

        self.bid = self.handover_message(new_bid)
        self.finalize(None)
        return self.bid

    @replay.named_side_effect('AgencyContractor.refuse')
    def refuse(self, refusal):
        if not self._ensure_state(ContractState.announced):
            return

        refusal = refusal.duplicate()
        self.debug("Sending refusal %r", refusal)

        self._set_state(ContractState.refused)

        refusal = self.send_message(refusal)
        self.finalize(None)
        return refusal

    @replay.named_side_effect('AgencyContractor.defect')
    def defect(self, cancellation):
        if not self._ensure_state(ContractState.granted):
            return

        cancellation = cancellation.duplicate()
        self.debug("Sending cancelation %r", cancellation)

        self._set_state(ContractState.defected)

        cancellation = self.send_message(cancellation)
        self.finalize(None)
        return cancellation

    @replay.named_side_effect('AgencyContractor.complete')
    def complete(self, report):
        if not self._ensure_state(ContractState.granted):
            return

        report = report.duplicate()
        self.debug("Sending final report %r", report)

        self._set_state(ContractState.completed)

        expiration_time = time.future(self.contractor.bid_timeout)
        self.report = self.send_message(report, expiration_time)

        self.set_timeout(expiration_time, ContractState.aborted,
                         self._run_and_terminate, self.contractor.aborted)
        return self.report

    @serialization.freeze_tag('AgencyContractor.update_manager_address')
    @replay.named_side_effect('AgencyContractor.update_manager_address')
    def update_manager_address(self, recp):
        recp = recipient.IRecipient(recp)
        if recp != self.recipients:
            self.debug('Updating manager address %r -> %r',
                       self.recipients, recp)
            self.recipients = recp

    ### IAgencyProtocolInternal Methods ###

    def get_agent_side(self):
        return self.contractor

    ### IAgencyListenerInternal Methods ###

    def on_message(self, msg):
        mapping = {
            message.Announcement:\
                {'method': self._on_announce,
                 'state_before': ContractState.initiated,
                 'state_after': ContractState.announced},
            message.Rejection:\
                {'method': self._on_reject,
                 'state_after': ContractState.rejected,
                 'state_before': ContractState.bid},
            message.Grant:\
                {'method': self._on_grant,
                 'state_after': ContractState.granted,
                 'state_before': ContractState.bid},
            message.Cancellation:\
                [{'method': self._on_cancel_in_granted,
                 'state_after': ContractState.cancelled,
                 'state_before': ContractState.granted},
                 {'method': self._on_cancel_in_completed,
                 'state_after': ContractState.aborted,
                 'state_before': ContractState.completed}],
            message.Acknowledgement:\
                {'method': self._on_ack,
                 'state_after': ContractState.acknowledged,
                 'state_before': ContractState.completed},
        }
        handler = self._event_handler(mapping, msg)
        if callable(handler):
            handler(msg)

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Hooks for messages comming in ###

    def _on_announce(self, announcement):
        self.set_timeout(announcement.expiration_time, ContractState.closed,
                         self._run_and_terminate,
                         self.contractor.announce_expired)
        self.call_agent_side(self.contractor.announced, announcement,
                             ensure_state=ContractState.announced)

    def _on_grant(self, grant):
        '''
        Called upon receiving the grant. Than calls granted and sets
        up reporter if necessary.
        '''
        self.set_timeout(grant.expiration_time, ContractState.expired,
                         self._run_and_terminate, self.contractor.cancelled,
                         grant)

        self.grant = grant
        # this is necessary for nested contracts to work with handing
        # the messages over
        self.set_remote_id(grant.sender_id)
        self.update_manager_address(grant.reply_to)

        self.call_agent_side(self.contractor.granted, grant,
                             ensure_state=ContractState.granted)

    def _on_ack(self, msg):
        d = self.call_agent_side(self.contractor.acknowledged, msg,
                                 ensure_state=ContractState.acknowledged)
        d.addCallback(self.finalize)

    def _on_reject(self, rejection):
        self._run_and_terminate(self.contractor.rejected, rejection,
                                ensure_state=ContractState.rejected)

    def _on_cancel_in_granted(self, cancellation):
        self._run_and_terminate(self.contractor.cancelled, cancellation,
                                ensure_state=ContractState.cancelled)

    def _on_cancel_in_completed(self, cancellation):
        self._run_and_terminate(self.contractor.aborted,
                                ensure_state=ContractState.aborted)


@adapter.register(IManagerFactory, IAgencyInitiatorFactory)
class AgencyManagerFactory(protocols.BaseInitiatorFactory):
    type_name = "manager-medium-factory"
    protocol_factory = AgencyManager


@adapter.register(IContractorFactory, IAgencyInterestInternalFactory)
class AgencyContractorInterest(protocols.DialogInterest):
    pass


@adapter.register(IContractorFactory, IAgencyInterestedFactory)
class AgencyContractorFactory(protocols.BaseInterestedFactory):
    type_name = "contractor-medium-factory"
    protocol_factory = AgencyContractor
