# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import uuid

from twisted.python import components
from twisted.internet import reactor
from zope.interface import implements

from feat.common import log
from feat.interface.protocols import IAgencyInitiatorFactory,\
                                     IAgencyInterestedFactory
from feat.interface.contractor import IAgencyContractor, IAgentContractor,\
                                      IContractorFactory
from feat.interface import contracts, recipient
from feat.agents import message

from interface import IListener


class AgencyContractorFactory(object):
    implements(IAgencyInterestedFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyContractor(agent, recipients, *args, **kwargs)


components.registerAdapter(AgencyContractorFactory,
                           IContractorFactory, IAgencyInterestedFactory)


class AgencyContractor(log.LogProxy, log.Logger):
    implements(IAgencyContractor, IListener)
 
    log_category = 'agency-contractor'

    def __init__(self, agent, announcement):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)

        assert isinstance(announcement, message.Announcement)

        self.agent = agent
        self.announce = announcement
        self.recipients = recipient.Agent(announcement.reply_to_key,
                                          announcement.reply_to_shard)
        self.session_id = announcement.session_id
        self.protocol_id = announcement.protocol_id

        self.log_name = self.session_id

        self._expiration_call = None

    def initiate(self, contractor):
        self.contractor = contractor
        self.contractor.state = contracts.ContractState.announced
        return contractor

    def bid(self, bid):
        self.debug("Sending bid %r", bid)
        assert isinstance(bid, message.Bid)
        assert isinstance(bid.bids, list)
        self.contractor.state = contracts.ContractState.bid
        self.bid = self._send_message(bid)
        if self._expiration_call:
            self.log('Canceling expiration call')
            self._expiration_call.cancel()
            self._expiration_call = None
        expiration_time = self.agent.get_time() +\
            self.contractor.grant_wait_timeout
        self._expire_at(expiration_time, self._bid_timeout)

        return self.bid
        
    def refuse(self, refusal):
        self.debug("Sending refusal %r", refusal)
        assert isinstance(refusal, message.Refusal)
        refusal = self._send_message(refusal)
        self.contractor.state = contracts.ContractState.rejected
        self._terminate()
        return refusal

    def cancel(self, cancellation):
        self.debug("Sending cancelation %r", cancellation)
        assert isinstance(cancellation, message.Cancellation)
        cancellation = self._send_message(cancellation)
        self.contractor.state = contracts.ContractState.aborted
        return cancellation

    def update(self, report):
        self.debug("Sending update report %r", report)
        assert isinstance(report, message.UpdateReport)
        report = self._send_message(self, report)
        return report

    def finalize(self, report):
        self.debug("Sending final report %r", report)
        assert isinstance(report, message.FinalReport)
        self.report = self._send_message(self, report)
        return self.report
    
    # private section

    def _send_message(self, msg):
        msg.session_id = self.session_id
        msg.protocol_id = self.protocol_id
        if self.contractor.state < contracts.ContractState.bid:
            msg.expiration_time = self.announce.expiration_time
        elif self.contractor.state < contracts.ContractState.granted:
            msg.expiration_time = self.agent.get_time() +\
                                  self.contractor.grant_wait_timeout
        else: 
            msg.expiration_time = self.grant.expiration_time

        return self.agent.send_msg(self.recipients, msg)

    def _on_grant(self, grant):
        '''
        Called upon receiving the grant. Check that grants bid includes
        actual bid we put. Than calls granted and sets up reporter if necessary.
        '''
        is_ok = grant.bid in self.bid.bids
        if is_ok:
            self.grant = grant
            self.contractor.granted(grant)
            if grant.update_report:
                self._setup_reporter()
        else:
            self.error("The bid granted doesn't match the one put upon!"
                       "Terminating!")
            self.error("Bid: %r, bids: %r", grant.bid, self.bid.bids)
            self._terminate()

    def _setup_reporter(self):
        frequency = self.grant.update_report
        
        def send_report():
            report = message.UpdateReport()
            self.update(report)
            bind()

        def bind():
            self.agent.callLater(frequency, send_report)

    def _bid_timeout(self):
        self.contractor.rejected(None)
        self._terminate()

    def _terminate(self):
        self.log("Unregistering contractor")
        self.contractor.state = contracts.ContractState.closed
        if self._expiration_call and not (self._expiration_call.called or\
                                          self._expiration_call.cancelled):
            self._expiration_call.cancel()
            self._expiration_call = None
            self.log('Canceling expiration call in _terminate()')
        self.agent.unregister_listener(self.session_id)

    def _expire_at(self, expire_time, method, *args, **kwargs):
        time_left = expire_time - self.agent.get_time()
        if time_left < 0:
            self.error('Tried to call method in the past!')
            self._terminate()
            return
        self._expiration_call = self.agent.callLater(time_left, method)

    def _on_ack(self, msg):
        self.contractor.acknowledged(msg)
        self._terminate()

    def _on_announce(self, announcement):
        self._expire_at(announcement.expiration_time, self._terminate)
        self.contractor.announced(announcement)

    def _on_reject(self, rejection):
        contractor.rejected(rejection)
        self._terminate()

    # IListener stuff

    def on_message(self, msg):
        mapping = {
            message.Announcement: { 'method': self._on_announce },
            message.Rejection: { 'method': self._on_reject,
                                 'state': contracts.ContractState.rejected },
            message.Grant: { 'method': self._on_grant,
                             'state': contracts.ContractState.granted },
            message.Cancellation: { 'method': self.contractor.canceled,
                                   'state': contracts.ContractState.cancelled },
            message.Acknowledgement: { 'method': self._on_ack,
                                'state': contracts.ContractState.acknowledged },
        }
        klass = msg.__class__
        decision = mapping.get(klass, None)
        if not decision:
            self.error("Unknown method class %r", msg)
            return False

        change_state = decision.get('state', None)
        if change_state:
            self.contractor.state = change_state

        decision['method'](msg)

    def get_session_id(self):
        return self.session_id
