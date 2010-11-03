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

    def initiate(self, contractor):
        self.contractor = contractor
        self.contractor.state = contracts.ContractState.announced
        self.contractor.announce = self.announce
        return contractor

    def bid(self, bid):
        self.debug("Sending bid %r", bid)
        assert isinstance(bid, message.Bid)
        assert isinstance(bid.bids, list)
        self.bid = self._send_message(bid)
        self.contractor.state = contracts.ContractState.bid
        return self.bid
        
    def refuse(self, refusal):
        self.debug("Sending refusal %r", refusal)
        assert isinstance(refusal, message.Refusal)
        refusal = self._send_message(refusal)
        self.contractor.state = contracts.ContractState.rejected
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
        msg.expiration_time = self.request.expiration_time

        return self.agent.send_msg(self.recipients, msg)

    def _validate_bid(self, grant):
        '''
        Called upon receiving the grant. Check that grants bid includes
        actual bid we put. Than calls granted and sets up reporter if necessary.
        '''
        is_ok = grant.bid in self.bid.bids
        if is_ok:
            self.grant = grant
            self.contractor.granted(grant)
            if grant.update_report:
                self._setup_reported()
        else:
            self.error("The bid granted doesn't match the one put upon!"
                       " Terminating!")
            self.error("Bid: %r, bids: %r", grant.bid, self.bid.bids)
            self._terminate()

    def _terminate(self):
        self.log("Unregistering contractor")
        self.agent.unregister_listener(self.session_id)

    def _ack_and_terminate(self, msg):
        self.contractor.acknowledged(msg)
        self._terminate()

    # IListener stuff

    def on_message(self, msg):
        mapping = {
            message.Announcement: { 'method': self.contractor.announced },
            message.Rejection: { 'method': self.contractor.rejected,
                                 'state': contracts.ContractState.rejected },
            message.Grant: { 'method': self._validate_bid },
            message.Cancellation: { 'method': self.contractor.canceled,
                                    'state': contracts.ContractState.aborted },
            message.Acknowledgement: { 'method': self._ack_and_terminate,
                                'state': contracts.ContractState.acknowledged},
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
