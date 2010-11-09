# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import uuid, traceback

from twisted.python import components, failure
from twisted.internet import reactor, defer
from zope.interface import implements

from feat.common import log, enum
from feat.interface import contracts, recipient, contractor, protocols, manager
from feat.agents import message

from interface import IListener
from . import common


class AgencyMiddleMixin(object):
    '''Responsible for formating messages, calling methods etc'''

    protocol_id = None
    session_id = None

    def __init__(self, protocol_id):
        self.protocol_id = protocol_id

    def _send_message(self, msg, expiration_time=None, recipients=None):
        msg.session_id = self.session_id
        msg.protocol_id = self.protocol_id
        if expiration_time is None:
            expiration_time = self.agent.get_time() + 10
        msg.expiration_time = expiration_time

        if not recipients:
            recipients = self.recipients

        return self.agent.send_msg(recipients, msg)

    def _call(self, method, *args, **kwargs):
        '''Call the method, wrap it in Deferred and bind error handler'''

        d = defer.maybeDeferred(method, *args, **kwargs)
        d.addErrback(self._error_handler)
        return d

    def _error_handler(e):
        # overload me
        raise e

    
class ExpirationCallsMixin(object):

    def __init__(self):
        self._expiration_call = None
    
    def _setup_expiration_call(self, expire_time, method, state=None,
                                  *args, **kwargs):
        time_left = expire_time - self.agent.get_time()

        if time_left < 0:
            self.error('Tried to call method in the past!')
            self._set_state(contracts.ContractState.wtf)
            self._terminate()
            return

        def to_call(callback):
            if state:
                self._set_state(state)
            self.log('Calling method: %r with args: %r', method, args)
            d = defer.maybeDeferred(method, *args, **kwargs)
            d.addCallback(callback.callback)

        result = defer.Deferred()
        self._expiration_call = self.agent.callLater(time_left, to_call, result)
        return result

    def _expire_at(self, expire_time, method, state, *args, **kwargs):
        d = self._setup_expiration_call(expire_time, method,
                                           state, *args, **kwargs)
        d.addCallback(lambda _: self._terminate())
        return d

    def _cancel_expiration_call(self):
        if self._expiration_call and not (self._expiration_call.called or\
                                          self._expiration_call.cancelled):
            self.log('Canceling expiration call')
            self._expiration_call.cancel()
            self._expiration_call = None

    def _run_and_terminate(self, method, *args, **kwargs):
        d = self._call(method, *args, **kwargs)
        d.addCallback(lambda _: self._terminate())

    def _terminate(self):
        self._cancel_expiration_call()


class AgencyManagerFactory(object):
    implements(protocols.IAgencyInitiatorFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyManager(agent, recipients, *args, **kwargs)


components.registerAdapter(AgencyManagerFactory,
                           manager.IManagerFactory,
                           protocols.IAgencyInitiatorFactory)


class ContractorState(enum.Enum):
    '''
    bid - bid has been received
    refused - refusal has been received
    rejected - bid has been rejected
    granted - job has been granted
    '''

    (bid, refused, rejected, granted) = range(4)


class ManagerContractor(common.StateMachineMixin, log.Logger):
    '''
    Represents the contractor from the point of view of the manager
    '''

    log_category = 'manager-contractor'
    
    def __init__(self, manager, bid):
        log.Logger.__init__(self, manager)
        common.StateMachineMixin.__init__(self)
        self._set_state(ContractorState.bid)
        self.bid = bid
        self.manager = manager
        self.recipient = recipient.IRecipient(bid)

        if bid in self.manager.contractors:
            raise RuntimeError('Contractor for the bid already registered!')
        self.manager.contractors[bid] = self

    def remove(self):
        del(self.manager.contractors[self.bid])

    def _send_message(self, msg):
        self.log('Sending message: %r to contractor', msg)
        self.manager._send_message(msg, recipients=self.recipient)

    def _call(self, *args, **kwargs):
        # delegate calling methods to medium class
        # this way we can reuse the error handler
        self.manager._call(*args, **kwargs)

    def on_event(self, msg):
        mapping = {
            message.Rejection:\
                {'method': self._send_message,
                 'state_before': ContractorState.bid,
                 'state_after': ContractorState.rejected},
            message.Grant:\
                {'method': self._send_message,
                 'state_before': ContractorState.bid,
                 'state_after': ContractorState.granted}
        }
        self._event_handler(mapping, msg)

        
class ManagerContractors(dict):
    
    def with_state(self, *states):
        return filter(lambda x: x.state in states, self.values())


class AgencyManager(log.LogProxy, log.Logger, common.StateMachineMixin,
                    ExpirationCallsMixin, AgencyMiddleMixin):
    implements(manager.IAgencyManager, IListener)
 
    log_category = 'agency-contractor'

    def __init__(self, agent, recipients, *args, **kwargs):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        common.StateMachineMixin.__init__(self)
        ExpirationCallsMixin.__init__(self)
       

        self.agent = agent
        self.recipients = recipients
        self.args = args
        self.kwargs = kwargs
        self.session_id = str(uuid.uuid1())
        self.log_name = self.session_id

        self.contractors = ManagerContractors()
    
    # manager.IAgencyManager stuff

    def initiate(self, manager):
        self.manager = manager
        AgencyMiddleMixin.__init__(self, manager.protocol_id)

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
        self._setup_expiration_call(expiration_time, self._on_announce_expire)  

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
            grants = [ grants ]

        for bid, grant in grants:
            contractor = self.contractors[bid]
            contractor.on_event(grant)
        
        self._cancel_expiration_call()
        self._set_state(contracts.ContractState.granted)

        for contractor in self.contractors.with_state(ContractorState.bid):
            contractor.on_event(message.Rejection())

    def cancel(self, grant, cancellation):
        pass

    def acknowledge(self, report):
        pass

    # hooks for events (timeout and messages comming in)
    
    def _on_announce_expire(self):
        self.log('Timeout expired, closing the announce window')
        self._ensure_state(contracts.ContractState.announced)

        self._cancel_expiration_call()

        if len(self.contractors) > 0:
            self._set_state(contracts.ContractState.closed)
            expiration_time = max(map(lambda bid: bid.expiration_time,
                                      self.contractors))
            self._expire_at(expiration_time, self.manager.expired,
                            contracts.ContractState.expired)
            self._call(self.manager.closed)
        else:
            self._set_state(contracts.ContractState.expired)
            self._run_and_terminate(self.manager.expired)
            
    def _on_bid(self, bid):
        self.log('Received bid %r', bid)
        ManagerContractor(self, bid)
        self._call(self.manager.bid, bid)

    # private

    def _error_handler(self, e):
        msg = e.getErrorMessage()
        self.error('Terminating: %s', msg)

        frames = traceback.extract_tb(e.getTracebackObject())
        if len(frames) > 0:
            self.error('Last traceback frame: %r', frames[-1])

        self._set_state(contracts.ContractState.wtf)
        self._terminate()

    def _terminate(self):
        ExpirationCallsMixin._terminate(self)

        self.log("Unregistering manager")
        self.agent.unregister_listener(self.session_id)

    # IListener stuff

    def on_message(self, msg):
        mapping = {
            message.Bid:\
                {'method': self._on_bid,
                 'state_after': contracts.ContractState.announced,
                 'state_before': contracts.ContractState.announced},
        }
        self._event_handler(mapping, msg)

    def get_session_id(self):
        return self.session_id


class AgencyContractorFactory(object):
    implements(protocols.IAgencyInterestedFactory)

    def __init__(self, factory):
        self._factory = factory

    def __call__(self, agent, recipients, *args, **kwargs):
        return AgencyContractor(agent, recipients, *args, **kwargs)


components.registerAdapter(AgencyContractorFactory,
                           contractor.IContractorFactory,
                           protocols.IAgencyInterestedFactory)


class AgencyContractor(log.LogProxy, log.Logger, common.StateMachineMixin,
                       ExpirationCallsMixin, AgencyMiddleMixin):
    implements(contractor.IAgencyContractor, IListener)
 
    log_category = 'agency-contractor'

    def __init__(self, agent, announcement):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        common.StateMachineMixin.__init__(self)
        ExpirationCallsMixin.__init__(self)
        AgencyMiddleMixin.__init__(self, announcement.protocol_id)

        assert isinstance(announcement, message.Announcement)

        self.agent = agent
        self.announce = announcement
        self.recipients = announcement.reply_to
        self.session_id = announcement.session_id

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

    def _terminate(self):
        ExpirationCallsMixin._terminate(self)

        self.log("Unregistering contractor")
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

    # hooks for messages comming in

    def _on_announce(self, announcement):
        self._expire_at(announcement.expiration_time,
                        self.contractor.announce_expired,
                        contracts.ContractState.closed)
        self._call(self.contractor.announced, announcement)

    def _on_grant(self, grant):
        '''
        Called upon receiving the grant. Check that grants bid includes
        actual bid we put. Than calls granted and sets up reporter if necessary.
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
