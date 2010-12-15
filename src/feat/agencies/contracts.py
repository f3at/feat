# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from twisted.python import components, failure
from zope.interface import implements

from feat.agents.base import message, recipient
from feat.common import log, enum, delay
from feat.interface import contracts, contractor, manager
from feat.interface.recipient import RecipientType

from interface import (IListener, IAgencyInitiatorFactory,
                       IAgencyInterestedFactory)
from . import common


class AgencyManagerFactory(object):
    implements(IAgencyInitiatorFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyManager(agent, recipients, *args, **kwargs)


components.registerAdapter(AgencyManagerFactory,
                           manager.IManagerFactory,
                           IAgencyInitiatorFactory)


class ContractorState(enum.Enum):
    '''
    bid - Bid has been received
    refused - Refusal has been received
    rejected - Bid has been rejected
    granted - Grant has been sent
    completed - FinalReport has been received
    cancelled - Sent or received Cancellation
    acknowledged - Ack has been sent
    '''

    (bid, refused, rejected, granted,
     completed, cancelled, acknowledged) = range(7)


class ManagerContractor(common.StateMachineMixin, log.Logger):
    '''
    Represents the contractor from the point of view of the manager
    '''

    log_category = 'manager-contractor'

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


class AgencyManager(log.LogProxy, log.Logger, common.StateMachineMixin,
                    common.ExpirationCallsMixin, common.AgencyMiddleMixin):
    implements(manager.IAgencyManager, IListener)

    log_category = 'agency-contractor'

    error_state = contracts.ContractState.wtf

    def __init__(self, agent, recipients, *args, **kwargs):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        common.StateMachineMixin.__init__(self)
        common.ExpirationCallsMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self)

        self.agent = agent
        self.recipients = recipients
        self.expected_bids = self._count_expected_bids(recipients)
        self.args = args
        self.kwargs = kwargs

        self.contractors = ManagerContractors()

    # manager.IAgencyManager stuff

    def initiate(self, manager):
        self.manager = manager
        self.log_name = manager.__class__.__name__
        self._set_protocol_id(manager.protocol_id)

        self._set_state(contracts.ContractState.initiated)
        self._call(manager.initiate, *self.args, **self.kwargs)

        timeout = self.agent.get_time() + self.manager.initiate_timeout
        error = RuntimeError('Timeout exceeded waiting for manager.initate() '
                             'to send the announcement')
        self._expire_at(timeout, self._error_handler,
                        contracts.ContractState.wtf, failure.Failure(error))
        return manager

    def announce(self, announce):
        self.debug("Sending announcement %r", announce)
        assert isinstance(announce, message.Announcement)

        self._ensure_state(contracts.ContractState.initiated)
        self._set_state(contracts.ContractState.announced)

        expiration_time = self.agent.get_time() + self.manager.announce_timeout
        self.bid = self._send_message(announce, expiration_time)

        self._cancel_expiration_call()
        self._setup_expiration_call(expiration_time,
                                    self._on_announce_expire)

        return self.bid

    def reject(self, bid, rejection=None):
        self._ensure_state(contracts.ContractState.announced)

        contractor = self.contractors[bid]
        if not rejection:
            rejection = message.Rejection()
        contractor.on_event(rejection)

    def grant(self, grants):
        self._ensure_state([contracts.ContractState.closed,
                            contracts.ContractState.announced])

        if not isinstance(grants, list):
            grants = [grants]

        self._cancel_expiration_call()
        self._set_state(contracts.ContractState.granted)

        expiration_time = self.agent.get_time() + self.manager.grant_timeout
        self._expire_at(expiration_time, self._on_grant_expire,
                        contracts.ContractState.aborted)

        for bid, grant in grants:
            grant.expiration_time = expiration_time
            contractor = self.contractors[bid]
            contractor.on_event(grant)

        for contractor in self.contractors.with_state(ContractorState.bid):
            contractor.on_event(message.Rejection())

    def cancel(self, reason=None):
        self._ensure_state([contracts.ContractState.granted,
                            contracts.ContractState.cancelled])
        self._set_state(contracts.ContractState.cancelled)

        to_cancel = self.contractors.with_state(\
                        ContractorState.granted, ContractorState.completed)
        for contractor in to_cancel:
            cancellation = message.Cancellation(reason=reason)
            contractor.on_event(cancellation)

        self._run_and_terminate(self.manager.cancelled)

    # hooks for events (timeout and messages comming in)

    def _on_grant_expire(self):
        self._set_state(contracts.ContractState.aborted)
        self._call(self.manager.aborted)

    def _on_announce_expire(self):
        self.log('Timeout expired, closing the announce window')
        self._ensure_state(contracts.ContractState.announced)

        self._cancel_expiration_call()

        if len(self.contractors.with_state(ContractorState.bid)) > 0:
            self._close_announce_period()
        else:
            self._set_state(contracts.ContractState.expired)
            self._run_and_terminate(self.manager.expired)

    def _on_bid(self, bid):
        self.log('Received bid %r', bid)
        ManagerContractor(self, bid)
        self._call(self.manager.bid, bid)
        if self.expected_bids and len(self.contractors) >= self.expected_bids:
            self._cancel_expiration_call()
            self._close_announce_period()

    def _on_refusal(self, refusal):
        self.log('Received bid %r', refusal)
        ManagerContractor(self, refusal, ContractorState.refused)

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
        self._ensure_state(contracts.ContractState.granted)
        self._set_state(contracts.ContractState.completed)
        self._cancel_expiration_call()

        contractors = self.contractors.with_state(ContractorState.completed)
        for contractor in contractors:
            ack = message.Acknowledgement()
            contractor.on_event(ack)

        reports = map(lambda x: x.report, contractors)
        self._run_and_terminate(self.manager.completed, reports)

    # private

    def _close_announce_period(self):
        self._set_state(contracts.ContractState.closed)
        expiration_time = max(map(lambda bid: bid.expiration_time,
                                  self.contractors))
        self._expire_at(expiration_time, self.manager.expired,
                        contracts.ContractState.expired)
        self._call(self.manager.closed)

    def _terminate(self):
        common.ExpirationCallsMixin._terminate(self)

        self.log("Unregistering manager")
        self.agent.unregister_listener(self.session_id)

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

    # IListener stuff

    def on_message(self, msg):
        mapping = {
            message.Bid:\
                {'method': self._on_bid,
                 'state_after': contracts.ContractState.announced,
                 'state_before': contracts.ContractState.announced},
            message.Refusal:\
                {'method': self._on_refusal,
                 'state_after': contracts.ContractState.announced,
                 'state_before': contracts.ContractState.announced},
            message.FinalReport:\
                {'method': self._on_report,
                 'state_after': contracts.ContractState.granted,
                 'state_before': contracts.ContractState.granted},
            message.Cancellation:\
                {'method': self._on_cancel,
                 'state_before': contracts.ContractState.granted,
                 'state_after': contracts.ContractState.cancelled},
        }
        self._event_handler(mapping, msg)

    def get_session_id(self):
        return self.session_id


class AgencyContractorFactory(object):
    implements(IAgencyInterestedFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyContractor(agent, recipients, *args, **kwargs)


components.registerAdapter(AgencyContractorFactory,
                           contractor.IContractorFactory,
                           IAgencyInterestedFactory)


class AgencyContractor(log.LogProxy, log.Logger, common.StateMachineMixin,
                       common.ExpirationCallsMixin, common.AgencyMiddleMixin):
    implements(contractor.IAgencyContractor, IListener)

    log_category = 'agency-contractor'

    error_state = contracts.ContractState.wtf

    def __init__(self, agent, announcement):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        common.StateMachineMixin.__init__(self)
        common.ExpirationCallsMixin.__init__(self)
        common.AgencyMiddleMixin.__init__(self, announcement.sender_id,
                                          announcement.protocol_id)

        assert isinstance(announcement, message.Announcement)

        self.agent = agent
        self.announce = announcement
        self.recipients = announcement.reply_to

        self.log_name = self.session_id

        self._reporter_call = None

    def initiate(self, contractor):
        self.contractor = contractor
        self._set_state(contracts.ContractState.initiated)
        return contractor

    # contractor.IAgencyContractor stuff

    def bid(self, bid):
        self.debug("Sending bid %r", bid)
        assert isinstance(bid, message.Bid)
        assert isinstance(bid.bids, list)

        self._ensure_state(contracts.ContractState.announced)
        self._set_state(contracts.ContractState.bid)

        expiration_time = self.agent.get_time() + self.contractor.bid_timeout
        self.bid = self._send_message(bid, expiration_time)

        self._cancel_expiration_call()
        self._expire_at(expiration_time, self.contractor.bid_expired,
                        contracts.ContractState.expired)

        return self.bid

    def handover(self, bid):
        self.debug('Sending bid of the nested contractor: %r.', bid)
        assert isinstance(bid, message.Bid)

        self._ensure_state(contracts.ContractState.announced)
        self._set_state(contracts.ContractState.delegated)

        self.bid = self._handover_message(bid)
        self._terminate()
        return self.bid

    def refuse(self, refusal):
        self.debug("Sending refusal %r", refusal)
        assert isinstance(refusal, message.Refusal)

        self._ensure_state(contracts.ContractState.announced)
        self._set_state(contracts.ContractState.refused)

        refusal = self._send_message(refusal)
        self._terminate()
        return refusal

    def defect(self, cancellation):
        self.debug("Sending cancelation %r", cancellation)
        assert isinstance(cancellation, message.Cancellation)

        self._ensure_state(contracts.ContractState.granted)
        self._set_state(contracts.ContractState.defected)

        cancellation = self._send_message(cancellation)
        self._terminate()
        return cancellation

    def finalize(self, report):
        self.debug("Sending final report %r", report)
        assert isinstance(report, message.FinalReport)

        self._ensure_state(contracts.ContractState.granted)
        self._set_state(contracts.ContractState.completed)

        expiration_time = self.agent.get_time() + self.contractor.bid_timeout
        self.report = self._send_message(report, expiration_time)

        self._cancel_expiration_call()
        self._expire_at(expiration_time, self.contractor.aborted,
                        contracts.ContractState.aborted)
        return self.report

    # private section

    def _terminate(self):
        common.ExpirationCallsMixin._terminate(self)

        self.log("Unregistering contractor")
        self._cancel_reporter()
        self.agent.unregister_listener(self.session_id)

    # update reporter stuff

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
        self._ensure_state(contracts.ContractState.granted)

        report = self._send_message(report)
        return report

    # hooks for messages comming in

    def _on_announce(self, announcement):
        self._expire_at(announcement.expiration_time,
                        self.contractor.announce_expired,
                        contracts.ContractState.closed)
        self._call(self.contractor.announced, announcement)

    def _on_grant(self, grant):
        '''
        Called upon receiving the grant. Check that grants bid includes
        actual bid we put. Than calls granted and sets up reporter
        if necessary.
        '''
        is_ok = grant.bid_index < len(self.bid.bids)
        if is_ok:
            self.grant = grant
            self._call(self.contractor.granted, grant)
            if grant.update_report:
                self._setup_reporter()
        else:
            self.error("The bid granted doesn't match the one put upon! "
                       "Terminating!")
            self.error("Bid index: %r, bids: %r", grant.bid_index,
                                                  self.bid.bids)
            self._set_state(contracts.ContractState.wtf)
            self._terminate()

    def _on_ack(self, msg):
        self._run_and_terminate(self.contractor.acknowledged, msg)

    def _on_reject(self, rejection):
        self._run_and_terminate(self.contractor.rejected, rejection)

    def _on_cancel_in_granted(self, cancellation):
        self._run_and_terminate(self.contractor.cancelled, cancellation)

    def _on_cancel_in_completed(self, cancellation):
        self._run_and_terminate(self.contractor.aborted)

    # IListener stuff

    def on_message(self, msg):
        mapping = {
            message.Announcement:\
                {'method': self._on_announce,
                 'state_before': contracts.ContractState.initiated,
                 'state_after': contracts.ContractState.announced},
            message.Rejection:\
                {'method': self._on_reject,
                 'state_after': contracts.ContractState.rejected,
                 'state_before': contracts.ContractState.bid},
            message.Grant:\
                {'method': self._on_grant,
                 'state_after': contracts.ContractState.granted,
                 'state_before': contracts.ContractState.bid},
            message.Cancellation:\
                [{'method': self._on_cancel_in_granted,
                 'state_after': contracts.ContractState.cancelled,
                 'state_before': contracts.ContractState.granted},
                 {'method': self._on_cancel_in_completed,
                 'state_after': contracts.ContractState.aborted,
                 'state_before': contracts.ContractState.completed}],
            message.Acknowledgement:\
                {'method': self._on_ack,
                 'state_after': contracts.ContractState.acknowledged,
                 'state_before': contracts.ContractState.completed},
        }
        self._event_handler(mapping, msg)

    def get_session_id(self):
        return self.session_id
