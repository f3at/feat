# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import uuid

from twisted.python import components, failure
from zope.interface import implements

from feat.agents.base import message, recipient, replay
from feat.common import log, enum, delay, serialization
from feat.agencies import common, protocols

from feat.agencies.interface import *
from feat.interface.serialization import *
from feat.interface.protocols import *
from feat.interface.contracts import *
from feat.interface.manager import *
from feat.interface.contractor import *
from feat.interface.recipient import *


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

    log_category = "manager-contractor"

    def __init__(self, manager, bid, state=None):
        log.Logger.__init__(self, manager)
        common.StateMachineMixin.__init__(self)
        self._set_state(state or ContractorState.bid)
        self.bid = bid
        self.report = None
        self.manager = manager
        self.recipient = recipient.IRecipient(bid)

        if bid in self.manager.contractors:
            raise RuntimeError('Contractor for the bid already registered!')
        self.manager.contractors[bid] = self

    ### Private Methods ###

    def _send_message(self, msg):
        self.log('Sending message: %r to contractor: %r',
                 msg, self.recipient.key)
        self.manager._send_message(msg, recipients=self.recipient,
                                   remote_id=self.bid.sender_id)

    def _call(self, *args, **kwargs):
        # delegate calling methods to medium class
        # this way we can reuse the error handler
        self.manager._call(*args, **kwargs)

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
        self._event_handler(mapping, msg)


class ManagerContractors(dict):

    def with_state(self, *states):
        return filter(lambda x: x.state in states, self.values())

    def by_message(self, msg):
        key = msg.reply_to.key
        match = filter(lambda x: x.reply_to.key == key, self.keys())
        if len(match) != 1:
            raise ValueError("Could not find ManagerContractor for msg: %r",
                             msg)
        return self.get(match[0])

    def get_bids(self):
        return self.with_state(ContractorState.bid)


class AgencyManager(log.LogProxy, log.Logger, common.StateMachineMixin,
                    common.ExpirationCallsMixin, common.AgencyMiddleMixin,
                    common.TransientInitiatorMediumBase):

    implements(IAgencyManager, IListener, ISerializable)

    log_category = "manager-medium"
    type_name = "manager-medium"

    error_state = ContractState.wtf

    def __init__(self, agency_agent, factory, recipients, *args, **kwargs):
        log.Logger.__init__(self, agency_agent)
        log.LogProxy.__init__(self, agency_agent)
        common.StateMachineMixin.__init__(self)
        common.ExpirationCallsMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self)
        common.TransientInitiatorMediumBase.__init__(self)

        self.agent = agency_agent
        self.factory = factory
        self.recipients = recipients
        self.expected_bids = self._count_expected_bids(recipients)
        self.args = args
        self.kwargs = kwargs

        self.contractors = ManagerContractors()

    # IAgencyManager stuff

    def initiate(self):
        self.agent.journal_protocol_created(self.factory, self,
                                            *self.args, **self.kwargs)
        manager = self.factory(self.agent.get_agent(), self)
        self.agent.register_listener(self)

        self.manager = manager
        self.log_name = manager.__class__.__name__
        self._set_protocol_id(manager.protocol_id)

        self._set_state(ContractState.initiated)
        timeout = self.agent.get_time() + self.manager.initiate_timeout
        error = InitiatorExpired("Timeout exceeded waiting for "
                                 "initate() to send the announcement")
        self._expire_at(timeout, self._error_handler,
                        ContractState.wtf, failure.Failure(error))

        self.call_next(self._call, self.manager.initiate,
                       *self.args, **self.kwargs)

        return manager

    ### IAgencyManager Methods ###

    @replay.named_side_effect('AgencyManager.announce')
    def announce(self, announce):
        announce = announce.clone()
        self.debug("Sending announcement %r", announce)
        assert isinstance(announce, message.Announcement)

        if announce.traversal_id is None:
            announce.traversal_id = str(uuid.uuid1())

        self._ensure_state(ContractState.initiated)
        self._set_state(ContractState.announced)

        exp_time = self.agent.get_time() + self.manager.announce_timeout
        bid = self._send_message(announce, exp_time)

        self._cancel_expiration_call()
        self._setup_expiration_call(exp_time, self._on_announce_expire)

        return bid

    @replay.named_side_effect('AgencyManager.reject')
    def reject(self, bid, rejection=None):
        self._ensure_state([ContractState.announced,
                            ContractState.granted,
                            ContractState.closed])

        contractor = self.contractors[bid]
        if not rejection:
            rejection = message.Rejection()
        else:
            rejection = rejection.clone()
        contractor.on_event(rejection)

    @serialization.freeze_tag('AgencyManager.grant')
    @replay.named_side_effect('AgencyManager.grant')
    def grant(self, grants):
        self._ensure_state([ContractState.closed,
                            ContractState.announced])

        if not isinstance(grants, list):
            grants = [grants]
        # clone the grant messages, not to mess with the
        # state on the agent side
        grants = [(bid, grant.clone(), ) for bid, grant in grants]

        self._cancel_expiration_call()
        self._set_state(ContractState.granted)

        expiration_time = self.agent.get_time() + self.manager.grant_timeout
        self._expire_at(expiration_time, self._on_grant_expire,
                        ContractState.aborted)

        # send a grant event to the contractors
        for bid, grant in grants:
            grant.expiration_time = expiration_time
            contractor = self.contractors[bid]
            contractor.on_event(grant)

        # send the rejections to all the contractors we are not granting
        for contractor in self.contractors.with_state(ContractorState.bid):
            contractor.on_event(message.Rejection())

    @serialization.freeze_tag('AgencyManager.elect')
    @replay.named_side_effect('AgencyManager.elect')
    def elect(self, bid):
        contractor = self.contractors.get(bid, None)
        if not contractor:
            self.debug('Asked to elect() an unknown bid. Ignoring.')
            return
        contractor._set_state(ContractorState.elected)

    @replay.named_side_effect('AgencyManager.cancel')
    def cancel(self, reason=None):
        self._ensure_state([ContractState.granted,
                            ContractState.cancelled])
        self._set_state(ContractState.cancelled)

        to_cancel = self.contractors.with_state(\
                        ContractorState.granted, ContractorState.completed)
        for contractor in to_cancel:
            cancellation = message.Cancellation(reason=reason)
            contractor.on_event(cancellation)

        self._run_and_terminate(self.manager.cancelled)

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
            self.call_next(self._terminate, result)

    @replay.named_side_effect('AgencyManager.get_bids')
    def get_bids(self):
        contractors = self.contractors.with_state(ContractorState.bid)
        return [x.bid for x in contractors]

    @replay.named_side_effect('AgencyManager.get_recipients')
    def get_recipients(self):
        return self.recipients

    ### IListener Methods ###

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
                {'method': self._on_refusal,
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
        self._event_handler(mapping, msg)

    def get_session_id(self):
        return self.session_id

    def get_agent_side(self):
        return self.manager

    # notify_finish() implemented in common.TransientInitiatorMediumBase

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Hooks for events (timeout and messages comming in) ###

    def _on_grant_expire(self):
        self._set_state(ContractState.aborted)
        return self._call(self.manager.aborted)

    def _on_announce_expire(self):
        self.log('Timeout expired, closing the announce window')
        self._ensure_state(ContractState.announced)

        self._cancel_expiration_call()

        self._goto_closed_or_expired()

    def _on_bid(self, bid):
        self.log('Received bid %r', bid)
        ManagerContractor(self, bid)
        self._call(self.manager.bid, bid)
        self._check_if_should_goto_close()

    def _on_refusal(self, refusal):
        self.log('Received refusal  %r', refusal)
        ManagerContractor(self, refusal, ContractorState.refused)
        self._check_if_should_goto_close()

    def _on_report(self, report):
        self.log('Received report: %r', report)

        try:
            contractor = self.contractors.by_message(report)
        except ValueError as e:
            self.warning("%s Ignoring", str(e))
            return False

        contractor.on_event(report)
        if len(self.contractors.with_state(ContractorState.granted)) == 0:
            self._on_complete()

    def _on_cancel(self, cancellation):
        self.log('Received cancellation: %r. Reason: %r',
                 cancellation, cancellation.reason)

        try:
            contractor = self.contractors.by_message(cancellation)
        except ValueError as e:
            self.warning("%s Ignoring", str(e))
            return False

        reason = "Other contractor cancelled the job with reason: %s" %\
                 cancellation.reason
        self.cancel(reason)

    def _on_complete(self):
        self.log('All Reports received. Sending ACKs')
        self._ensure_state(ContractState.granted)
        self._set_state(ContractState.completed)
        self._cancel_expiration_call()

        contractors = self.contractors.with_state(ContractorState.completed)
        for contractor in contractors:
            ack = message.Acknowledgement()
            contractor.on_event(ack)

        reports = map(lambda x: x.report, contractors)
        d = self._call(self.manager.completed, reports)
        d.addCallback(self._terminate)

    # Used by ExpirationCallsMixin

    def _get_time(self):
        return self.agent.get_time()

    ### Required by TransientInitiatorMediumbase ###

    def call_next(self, _method, *args, **kwargs):
        return self.agent.call_next(_method, *args, **kwargs)

    ### Private Methods ###

    def _check_if_should_goto_close(self):
        if self.expected_bids and len(self.contractors) >= self.expected_bids:
            self._cancel_expiration_call()
            self._goto_closed_or_expired()

    def _goto_closed_or_expired(self):
        if len(self.contractors.with_state(ContractorState.bid)) > 0:
            self._close_announce_period()
        else:
            self._set_state(ContractState.expired)
            self._run_and_terminate(self.manager.expired)

    def _close_announce_period(self):
        expiration_time = max(map(lambda bid: bid.expiration_time,
                                  self.contractors))
        self._expire_at(expiration_time, self.manager.expired,
                        ContractState.expired)
        self._set_state(ContractState.closed)
        self._call(self.manager.closed)

    def _terminate(self, result):
        common.ExpirationCallsMixin._terminate(self)

        self.log("Unregistering manager")
        self.agent.unregister_listener(self.session_id)

        common.TransientInitiatorMediumBase._terminate(self, result)

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


class AgencyContractor(log.LogProxy, log.Logger, common.StateMachineMixin,
                       common.ExpirationCallsMixin, common.AgencyMiddleMixin,
                       common.TransientInterestedMediumBase):

    implements(IAgencyContractor, IListener, ISerializable)

    log_category = "contractor-medium"
    type_name = "contractor-medium"

    error_state = ContractState.wtf

    def __init__(self, agency_agent, factory, announcement):
        log.Logger.__init__(self, agency_agent)
        log.LogProxy.__init__(self, agency_agent)
        common.StateMachineMixin.__init__(self)
        common.ExpirationCallsMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self, announcement.sender_id,
                                          announcement.protocol_id)
        common.TransientInterestedMediumBase.__init__(self)

        assert isinstance(announcement, message.Announcement)

        self.agent = agency_agent
        self.factory = factory
        self.announce = announcement
        self.recipients = announcement.reply_to

        self._reporter_call = None

    def initiate(self):
        self.agent.journal_protocol_created(self.factory, self)
        contractor = self.factory(self.agent.get_agent(), self)

        self.contractor = contractor
        self.log_name = self.contractor.__class__.__name__
        self._set_state(ContractState.initiated)
        return contractor

    ### IAgencyContractor Methods ###

    @serialization.freeze_tag('AgencyContractor.bid')
    @replay.named_side_effect('AgencyContractor.bid')
    def bid(self, bid):
        bid = bid.clone()
        self.debug("Sending bid %r", bid)
        assert isinstance(bid, message.Bid)

        self._ensure_state(ContractState.announced)
        self._set_state(ContractState.bid)

        expiration_time = self.agent.get_time() + self.contractor.bid_timeout
        self.own_bid = self._send_message(bid, expiration_time)

        self._cancel_expiration_call()
        self._expire_at(expiration_time, self.contractor.bid_expired,
                        ContractState.expired)

        return self.own_bid

    @serialization.freeze_tag('AgencyContractor.handover')
    @replay.named_side_effect('AgencyContractor.handover')
    def handover(self, bid):
        bid = bid.clone()
        self.debug('Sending bid of the nested contractor: %r.', bid)
        assert isinstance(bid, message.Bid)

        self._ensure_state(ContractState.announced)
        self._set_state(ContractState.delegated)

        self.bid = self._handover_message(bid)
        delay.callLater(0, self._terminate, None)
        return self.bid

    @replay.named_side_effect('AgencyContractor.refuse')
    def refuse(self, refusal):
        refusal = refusal.clone()
        self.debug("Sending refusal %r", refusal)
        assert isinstance(refusal, message.Refusal)

        self._ensure_state(ContractState.announced)
        self._set_state(ContractState.refused)

        refusal = self._send_message(refusal)
        self._terminate(None)
        return refusal

    @replay.named_side_effect('AgencyContractor.defect')
    def defect(self, cancellation):
        cancellation = cancellation.clone()
        self.debug("Sending cancelation %r", cancellation)
        assert isinstance(cancellation, message.Cancellation)

        self._ensure_state(ContractState.granted)
        self._set_state(ContractState.defected)

        cancellation = self._send_message(cancellation)
        self._terminate(None)
        return cancellation

    @replay.named_side_effect('AgencyContractor.finalize')
    def finalize(self, report):
        report = report.clone()
        self.debug("Sending final report %r", report)
        assert isinstance(report, message.FinalReport)

        self._ensure_state(ContractState.granted)
        self._set_state(ContractState.completed)

        expiration_time = self.agent.get_time() + self.contractor.bid_timeout
        self.report = self._send_message(report, expiration_time)

        self._cancel_expiration_call()
        self._expire_at(expiration_time, self.contractor.aborted,
                        ContractState.aborted)
        return self.report

    @serialization.freeze_tag('AgencyContractor.update_manager_address')
    @replay.named_side_effect('AgencyContractor.update_manager_address')
    def update_manager_address(self, recp):
        recp = recipient.IRecipient(recp)
        if recp != self.recipients:
            self.debug('Updating manager address %r -> %r',
                       self.recipients, recp)
            self.recipients = recp

    ### IListener Methods ###

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
        self._event_handler(mapping, msg)

    def get_session_id(self):
        return self.session_id

    def get_agent_side(self):
        return self.contractor

    # notify_finish() implemented in common.TransientInterestedMediumBase

    ### ISerializable Methods ###

    def snapshot(self):
        return id(self)

    ### Used by ExpirationCallsMixin ###

    def _get_time(self):
        return self.agent.get_time()

    ### Private Methods ###

    def _terminate(self, result):
        common.ExpirationCallsMixin._terminate(self)

        self.log("Unregistering contractor")
        self._cancel_reporter()
        self.agent.unregister_listener(self.session_id)
        common.TransientInterestedMediumBase._terminate(self, result)

    ### Update reporter stuff ###

    def _cancel_reporter(self):
        if self._reporter_call and not (self._reporter_call.called or\
                                        self._reporter_call.cancelled):
            self._reporter_call.cancel()
            self.log("Canceling periodical reporter")

    def _setup_reporter(self):
        frequency = self.grant.update_report

        def send_report():
            report = message.UpdateReport()
            self._update(report)
            bind()

        def bind():
            self._reporter_call = delay.callLater(frequency, send_report)

        bind()

    def _update(self, report):
        self.debug("Sending update report %r", report)
        assert isinstance(report, message.UpdateReport)
        self._ensure_state(ContractState.granted)

        report = self._send_message(report)
        return report

    ### Required by TransientInterestedMediumBase ###

    def call_next(self, _method, *args, **kwargs):
        return self.agent.call_next(_method, *args, **kwargs)

    ### Hooks for messages comming in ###

    def _on_announce(self, announcement):
        self._expire_at(announcement.expiration_time,
                        self.contractor.announce_expired,
                        ContractState.closed)
        self._call(self.contractor.announced, announcement)

    def _on_grant(self, grant):
        '''
        Called upon receiving the grant. Than calls granted and sets
        up reporter if necessary.
        '''
        self.grant = grant
        # this is necessary for nested contracts to work with handing
        # the messages over
        self._set_remote_id(grant.sender_id)
        self.update_manager_address(grant.reply_to)

        self._call(self.contractor.granted, grant)
        if grant.update_report:
            self._setup_reporter()

    def _on_ack(self, msg):
        self._run_and_terminate(self.contractor.acknowledged, msg)

    def _on_reject(self, rejection):
        self._run_and_terminate(self.contractor.rejected, rejection)

    def _on_cancel_in_granted(self, cancellation):
        self._run_and_terminate(self.contractor.cancelled, cancellation)

    def _on_cancel_in_completed(self, cancellation):
        self._run_and_terminate(self.contractor.aborted)


class AgencyManagerFactory(protocols.BaseInitiatorFactory):
    type_name = "manager-medium-factory"
    protocol_factory = AgencyManager


components.registerAdapter(AgencyManagerFactory,
                           IManagerFactory,
                           IAgencyInitiatorFactory)


class AgencyContractorInterest(protocols.DialogInterest):
    pass


components.registerAdapter(AgencyContractorInterest,
                           IContractorFactory,
                           IAgencyInterestInternalFactory)


class AgencyContractorFactory(protocols.BaseInterestedFactory):
    type_name = "contractor-medium-factory"
    protocol_factory = AgencyContractor


components.registerAdapter(AgencyContractorFactory,
                           IContractorFactory,
                           IAgencyInterestedFactory)
