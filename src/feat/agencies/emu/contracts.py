# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import uuid

from twisted.python import components
from twisted.internet import reactor, defer
from zope.interface import implements

from feat.common import log
from feat.interface import contracts, recipient, contractor, protocols
from feat.agents import message

from interface import IListener
from . import common


class AgencyContractorFactory(object):
    implements(protocols.IAgencyInterestedFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyContractor(agent, recipients, *args, **kwargs)


components.registerAdapter(AgencyContractorFactory,
                           contractor.IContractorFactory,
                           protocols.IAgencyInterestedFactory)


class AgencyContractor(log.LogProxy, log.Logger, common.StateMachineMixin):
    implements(contractor.IAgencyContractor, IListener)
 
    log_category = 'agency-contractor'

    def __init__(self, agent, announcement):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        common.StateMachineMixin.__init__(self)

        assert isinstance(announcement, message.Announcement)

        self.agent = agent
        self.announce = announcement
        self.recipients = announcement.reply_to
        self.session_id = announcement.session_id
        self.protocol_id = announcement.protocol_id

        self.log_name = self.session_id

        self._expiration_call = None
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
        
    def refuse(self, refusal):
        self.debug("Sending refusal %r", refusal)
        assert isinstance(refusal, message.Refusal)

        self._ensure_state(contracts.ContractState.announced)
        self._set_state(contracts.ContractState.refused)

        refusal = self._send_message(refusal)
        self._terminate()
        return refusal

    def cancel(self, cancellation):
        self.debug("Sending cancelation %r", cancellation)
        assert isinstance(cancellation, message.Cancellation)

        self._ensure_state(contracts.ContractState.granted)
        self._set_state(contracts.ContractState.cancelled)

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

    def _send_message(self, msg, expiration_time=None):
        msg.session_id = self.session_id
        msg.protocol_id = self.protocol_id
        if expiration_time is None:
            expiration_time = self.agent.get_time() + 10
        msg.expiration_time = expiration_time

        return self.agent.send_msg(self.recipients, msg)

    def _run_and_terminate(self, method, *args, **kwargs):
        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addCallback(lambda _: self._terminate())

    def _terminate(self):
        self.log("Unregistering contractor")

        self._cancel_expiration_call()
        self._cancel_reporter()
        self.agent.unregister_listener(self.session_id)

    def _error_handler(self, e):
        self.error('Terminating: %s', e.getErrorMessage())
        self._set_state(contracts.ContractState.wtf)
        self._terminate()

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
            self._reporter_call = self.agent.callLater(frequency, send_report)
        
        bind()

    def _update(self, report):
        self.debug("Sending update report %r", report)
        assert isinstance(report, message.UpdateReport)
        self._ensure_state(contracts.ContractState.granted)

        report = self._send_message(report)
        return report

    # expiration calls

    def _expire_at(self, expire_time, method, state, *args, **kwargs):
        time_left = expire_time - self.agent.get_time()
        if time_left < 0:
            self.error('Tried to call method in the past!')
            self._set_state(contracts.ContractState.wtf)
            self._terminate()
            return

        def to_call():
            self._set_state(state)
            self.log('Calling method: %r with args: %r', method, args)
            d = defer.maybeDeferred(method, *args, **kwargs)
            d.addCallback(lambda _: self._terminate())

        self._expiration_call = self.agent.callLater(time_left, to_call)

    def _cancel_expiration_call(self):
        if self._expiration_call and not (self._expiration_call.called or\
                                          self._expiration_call.cancelled):
            self.log('Canceling expiration call')
            self._expiration_call.cancel()
            self._expiration_call = None

    # hooks for messages comming in

    def _on_announce(self, announcement):
        self._expire_at(announcement.expiration_time,
                        self.contractor.announce_expired,
                        contracts.ContractState.closed)
        self.contractor.announced(announcement)

    def _on_grant(self, grant):
        '''
        Called upon receiving the grant. Check that grants bid includes
        actual bid we put. Than calls granted and sets up reporter if necessary.
        '''
        is_ok = grant.bid_index < len(self.bid.bids)
        if is_ok:
            self.grant = grant
            self.contractor.granted(grant)
            if grant.update_report:
                self._setup_reporter()
        else:
            self.error("The bid granted doesn't match the one put upon!"
                       "Terminating!")
            self.error("Bid index: %r, bids: %r", grant.bid_index,
                                                  self.bid.bids)
            self._set_state(contracts.ContractState.wtf)
            self._terminate()

    def _on_ack(self, msg):
        self._run_and_terminate(self.contractor.acknowledged, msg)

    def _on_reject(self, rejection):
        self._run_and_terminate(self.contractor.rejected, rejection)

    def _on_cancel(self, cancellation):
        self._run_and_terminate(self.contractor.cancelled, cancellation)

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
                {'method': self._on_cancel,
                 'state_after': contracts.ContractState.cancelled,
                 'state_before': [contracts.ContractState.granted,
                                  contracts.ContractState.completed]},
            message.Acknowledgement:\
                {'method': self._on_ack,
                 'state_after': contracts.ContractState.acknowledged,
                 'state_before': contracts.ContractState.completed},
        }
        self._event_handler(mapping, msg)

    def get_session_id(self):
        return self.session_id
