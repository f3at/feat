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
import types
import sys

from zope.interface import implements

from feat.common import log, serialization, fiber, defer, annotate
from feat.common import formatable, mro, error
from feat.agents.base import replay, requester
from feat.agencies import recipient
from feat.agents.application import feat

from feat.interface.protocols import IInitiator
from feat.interface.agent import IPartner


def accept_responsability(initiator):
    initiator = IInitiator(initiator)
    expiration_time = initiator.get_expiration_time()
    return ResponsabilityAccepted(expiration_time=expiration_time)


@feat.register_restorator
class ResponsabilityAccepted(formatable.Formatable):
    formatable.field('expiration_time', None)


class DefinitionError(Exception):
    pass


class DoublePartnership(Exception):
    pass


class FindPartnerError(Exception):
    pass


class Relation(object):

    def __init__(self, name, factory):
        self.name = name
        self.factory = factory

    def query(self, partners):
        return [x for x in partners if isinstance(x, self.factory)]

    def query_with_role(self, partners, role):
        return [x for x in partners \
                if isinstance(x, self.factory) and x.role == role]


class ManyRelation(Relation):
    pass


class OneRelation(Relation):

    def query(self, partners):
        match = Relation.query(self, partners)
        return self._ensure_one(partners, match)

    def query_with_role(self, partners):
        match = Relation.query_with_role(self, partners)
        return self._ensure_one(partners, match)

    def _ensure_one(self, partners, match):
        if len(match) > 1:
            raise FindPartnerError(
            'Expected at most one partner of the class %r, found %d in %r' %\
                (self.factory, len(match), match))
        elif len(match) == 1:
            return match[0]


def has_many(name, descriptor_type, factory, role=None, force=False):
    relation = ManyRelation(name, factory)
    _inject_definition(relation, descriptor_type, factory, role, force)


def has_one(name, descriptor_type, factory, role=None, force=False):
    relation = OneRelation(name, factory)
    _inject_definition(relation, descriptor_type, factory, role, force)


def _inject_definition(relation, descriptor_type, factory, role, force):

    if not force and factory == BasePartner:
        raise DefinitionError(
            "BasePartner class cannot be used in has_one or has_many "
            "definitions. Instead you should create a subclass for each type "
            "of relation you are defining.")

    annotate.injectClassCallback("handler", 4, "_define_handler",
                                 descriptor_type, factory, role)
    annotate.injectClassCallback("relation", 4, "_append_relation",
                                 relation)

    @property
    def getter(self):
        return self.query(relation.name)

    def getter_with_role(self, role):
        return self.query_with_role(relation.name, role)


    annotate.injectAttribute("relation_getter", 4, relation.name, getter)
    annotate.injectAttribute("relation_getter", 4,
                             relation.name + "_with_role", getter_with_role)


@feat.register_restorator
class BasePartner(serialization.Serializable, mro.FiberMroMixin):
    implements(IPartner)

    type_name = 'partner'

    def __init__(self, recp, allocation_id=None, role=None):
        self.recipient = recipient.IRecipient(recp)
        self.allocation_id = allocation_id
        self.role = role

    ### callbacks for partnership notifications ###

    def initiate(self, agent):
        """After returning a synchronous result or when the returned fiber
        is finished the partner is stored to descriptor."""

    def on_shutdown(self, agent):
        agent.log('Shutdown handler sending goodbye, for '
                  'agent %r partner %r.', agent, self)
        brothers = agent.query_partners(type(self))
        return requester.say_goodbye(agent, self.recipient, brothers)

    def on_goodbye(self, agent, brothers):
        '''
        Called when the partner goes through the termination procedure.

        @param brothers: The list of the partner of the same class
                         of the agent.
        '''

    def on_breakup(self, agent):
        '''
        Called when we have successfully broken up with the partner.
        '''

    def on_died(self, agent, brothers, monitor):
        '''
        Called by the monitoring agent, when he detects that the partner has
        died. If your handler is going to solve this problem return the
        L{feat.agents.base.partners.ResponsabilityAccepted} instance.

        @param brothers: Same as in on_goodbye.
        @param monitor: IRecipient of monitoring agent who notified us about
                        this unfortunate event
        '''

    def on_restarted(self, agent, old_recipient):
        '''
        Called after the partner is restarted by the monitoring agent.
        After returning a synchronous result or when the returned fiber
        is finished the partner is stored to descriptor.
        @param migrated: Flag saying whether the IRecipient of partner has
                         changed
        '''

    def on_buried(self, agent, brothers=None):
        '''
        Called when all the hope is lost. Noone took the responsability for
        handling the agents death, and monitoring agent failed to restart it.

        @param brothers: The list of the partner of the same class
                         of the agent.
        '''

    ### utility methods to be used from the handlers ###

    def remove_me_from_descriptor(self, agent):
        return agent.remove_partner(self)

    ### python specific ###

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.recipient == other.recipient and\
               self.allocation_id == other.allocation_id and\
               self.role == other.role

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)

    def __repr__(self):
        return "<%s.%s recp: %r, alloc: %s, role: %r>" % \
                (str(self.__class__.__module__),
                 str(self.__class__.__name__),
                 self.recipient, self.allocation_id, self.role, )


class Continuation(object):

    def __init__(self):
        self._list = list()

    def call_next(self, _method, *args, **kwargs):
        self._list.append((_method, args, kwargs))

    def perform(self, call_next):
        for method, args, kwargs in self._list:
            call_next(method, *args, **kwargs)


class Partners(log.Logger, log.LogProxy, replay.Replayable):

    ignored_state_keys = ['medium', 'agent']

    default_handler = BasePartner
    default_role = None

    application = feat

    has_many("all", "whatever", BasePartner, force=True)

    def __init__(self, agent):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        replay.Replayable.__init__(self, agent)

    @replay.immutable
    def restored(self, state):
        log.Logger.__init__(self, state.agent)
        log.LogProxy.__init__(self, state.agent)
        replay.Replayable.restored(self)

    def init_state(self, state, agent):
        state.agent = agent

    # managing the handlers

    @classmethod
    def __class__init__(cls, name, bases, dct):
        # agent.descriptor_type -> HandlerFactory
        cls._handlers = dict()
        # name -> Relation
        cls._relations = dict()

        for base in bases:
            cls._relations.update(getattr(base, '_relations', dict()))
            cls._handlers.update(getattr(base, '_handlers', dict()))

        cls._define_default_handler(cls.default_handler)
        cls.application.register_restorator(cls)

    @classmethod
    def query_handler(cls, identifier, role=None):
        '''
        Lookup the handler for the giving idetifier (descriptor_type) and role.
        In case it was not found return the default.

        Logic goes as follows:
         - First try to find exact match for identifier and role,
         - Try to find match for identifier and role=None,
         - Return default handler.
        '''
        key = cls._key_for(identifier, role)
        handler = cls._handlers.get(key, None)
        if handler is None:
            default_for_identifier = cls._key_for(identifier, None)
            handler = cls._handlers.get(default_for_identifier,
                                        cls._handlers['_default'])
        return handler

    @classmethod
    def _define_default_handler(cls, factory):
        cls._handlers['_default'] = factory

    @classmethod
    def _append_relation(cls, relation):
        assert isinstance(relation, Relation)
        cls._relations[relation.name] = relation

    @classmethod
    def _define_handler(cls, agent_class, factory, role=None):
        try:
            existing = next((cls._handlers[k], k) \
                            for k in cls._handlers \
                            if cls._handlers[k] == factory and k != '_default')
        except StopIteration:
            existing = None
        if existing and existing[0] != factory:
            raise DefinitionError(
                "Factory %r is already defined for the key %r. Factories "
                "shouldn't be reused! Create another subclass." % existing)

        key = cls._key_for(agent_class, role)
        cls._handlers[key] = factory

    @classmethod
    def _key_for(cls, factory, role):
        return (factory, role, )

    # quering and updating

    @replay.immutable
    def query(self, state, name_or_class):
        partners = state.agent.get_descriptor().partners
        if (isinstance(name_or_class, types.TypeType) and
            IPartner.implementedBy(name_or_class)):
            return filter(lambda x: isinstance(x, name_or_class), partners)
        else:
            relation = self._get_relation(name_or_class)
            return relation.query(partners)

    @replay.immutable
    def query_with_role(self, state, name, role):
        partners = state.agent.get_descriptor().partners
        relation = self._get_relation(name)
        return relation.query_with_role(partners, role)

    @replay.immutable
    def find(self, state, recp):
        """WARNING: This function do not return partners
        currently being initialized."""
        if recipient.IRecipient.providedBy(recp):
            agent_id = recipient.IRecipient(recp).key
        else:
            agent_id = recp
        desc = state.agent.get_descriptor()
        match = [x for x in desc.partners if x.recipient.key == agent_id]
        if len(match) == 0:
            return None
        elif len(match) > 1:
            raise FindPartnerError('More than one partner was matched by the '
                                   'recipient %r!. Matched: %r' % \
                                   (recp, match, ))
        else:
            return match[0]

    @replay.mutable
    def create(self, state, partner_class, recp,
               allocation_id=None, role=None, substitute=None,
               options=None):
        options = options or dict()
        found = self.find(recp)
        if found:
            self.info('We already are in partnership with recipient '
                      '%r, instance: %r.', recp, found)
            return fiber.succeed(found)

        factory = self.query_handler(partner_class, role)
        partner = factory(recp, allocation_id, role)
        self.debug(
            'Registering partner %r (lookup (%r, %r)) for recipient: %r',
            factory, partner_class, role, recp)

        if substitute:
            self.debug('It will substitute: %r', substitute)

        f = fiber.succeed()
        if allocation_id:
            f.add_callback(fiber.drop_param,
                           state.agent.get_allocation,
                           allocation_id)
        f.add_callback(fiber.drop_param, self.initiate_partner, partner,
                       substitute, **options)
        return f

    @replay.mutable
    def update_partner(self, state, partner):
        return state.agent.update_descriptor(self._do_update_partner,
                                             partner)

    @replay.immutable
    def initiate_partner(self, state, partner, substitute=None, **options):
        continuation = Continuation()

        keywords = dict(options)
        keywords['agent'] = state.agent
        keywords['call_next'] = continuation.call_next

        f = partner.call_mro_ex('initiate', keywords,
                                raise_on_unconsumed=False)
        f.add_callback(fiber.drop_param, state.agent.update_descriptor,
                       self._do_update_partner, partner, substitute)
        f.add_callback(fiber.bridge_param, continuation.perform,
                       state.agent.call_next)
        return f

    @replay.mutable
    def receive_notification(self, state, recp, notification_type,
                             blackbox, sender):
        partner = self.find(recp)
        if partner is None:
            self.warning("Didn't find a partner matching the notification "
                         "%r origin :%r!", notification_type, recp)
            return None
        handler_method = '_on_%s' % (notification_type, )
        handler = getattr(self, handler_method, None)
        if not callable(handler):
            return fiber.fail(
                ValueError('No handler found for notification %r!' %\
                           (notification_type, )))
        return handler(partner, blackbox, sender)

    @replay.mutable
    def remove(self, state, partner):
        # FIXME: Two subsequent updates of descriptor.
        f = fiber.succeed()
        f.add_callback(fiber.drop_param, state.agent.update_descriptor,
                       self._remove_partner, partner)
        if partner.allocation_id:
            f.add_callback(fiber.drop_param, state.agent.release_resource,
                           partner.allocation_id)
        return f

    @replay.mutable
    def breakup(self, state, partner):
        brothers = self.query(type(partner))
        f = requester.say_goodbye(state.agent, partner.recipient, brothers)
        f.add_callback(fiber.drop_param, self._do_breakup, partner)
        return f

    # handlers for incoming notifications from/about partners

    def _on_goodbye(self, partner, blackbox, sender):
        return self._remove_and_trigger_cb(partner, 'on_goodbye',
                                           brothers=blackbox)

    def _on_buried(self, partner, blackbox, sender):
        return self._remove_and_trigger_cb(partner, 'on_buried',
                                           brothers=blackbox)

    @replay.immutable
    def _on_died(self, state, partner, blackbox, sender):
        f = fiber.wrap_defer(partner.call_mro, 'on_died',
                             agent=state.agent,
                             brothers=blackbox,
                             monitor=sender)
        f.add_errback(self._error_handler)
        return f

    @replay.immutable
    def _on_restarted(self, state, partner, new_address, sender):
        old = partner.recipient if new_address != partner.recipient else None
        f = fiber.succeed()
        partner.recipient = recipient.IRecipient(new_address)
        f.add_callback(fiber.drop_param, self._call_next_cb_broken,
                       partner, 'on_restarted', True, old_recipient=old)
        return f

    # private

    def _error_handler(self, f):
        error.handle_failure(self, f, 'Error processing')

    def _do_breakup(self, partner):
        return self._remove_and_trigger_cb(partner, 'on_breakup')

    def _remove_and_trigger_cb(self, partner, cb_name, **kwargs):
        f = fiber.Fiber()
        f.add_callback(fiber.drop_param, self.remove, partner)
        f.add_callback(fiber.drop_param, self._call_next_cb_broken,
                       partner, cb_name, False, **kwargs)
        return f.succeed()

    @replay.immutable
    def _call_next_cb_broken(self, state, partner, method_name,
                            update_descriptor, **kwargs):
        # This is done outside the current execution chain, as the
        # action performed may be arbitrary long running, and we don't want
        # to run into the timeout of goodbye request
        state.agent.call_next(self._call_next_cb, partner, method_name,
                              update_descriptor, **kwargs)

    @fiber.woven
    @replay.immutable
    def _call_next_cb(self, state, partner, method_name,
                      update_descriptor, **kwargs):
        continuation = Continuation()
        keywords = dict(agent=state.agent, call_next=continuation.call_next)
        keywords.update(kwargs)
        f = partner.call_mro_ex(method_name, keywords,
                                raise_on_unconsumed=False)
        f.add_errback(fiber.inject_param, 1,
                      error.handle_failure, self,
                      "%s() method of %s returned the failure.", method_name,
                      partner)
        if update_descriptor:
            f.add_callback(defer.drop_param, self.update_partner, partner)
        f.add_callback(defer.drop_param, continuation.perform,
                       state.agent.call_next)
        return f

    def _get_relation(self, name):
        try:
            return self._relations[name]
        except KeyError:
            raise ValueError('Unknown relation name %r: ' % (name, )), \
                  None, sys.exc_info()[2]

    def _do_update_partner(self, desc, partner, substitute=None):
        if substitute:
            self._remove_partner(desc, substitute)
        found = [x for x in desc.partners
                 if x.recipient.key == partner.recipient.key]
        if len(found) != 1:
            desc.partners.append(partner)
        else:
            index = desc.partners.index(found[0])
            desc.partners[index] = partner
        return partner

    def _remove_partner(self, desc, partner):
        if partner not in desc.partners:
            self.warning(
                "Was about to remove partner %r. But didn't find it in %r",
                partner, desc.partners)
            return
        desc.partners.remove(partner)

    @replay.immutable
    def __repr__(self, state):
        return "<Partners>"


@feat.register_adapter(BasePartner, recipient.IRecipient)
@feat.register_adapter(BasePartner, recipient.IRecipients)
class RecipientFromPartner(recipient.Recipient):

    type_name = 'recipient'

    def __init__(self, partner):
        recipient.Recipient.__init__(self, partner.recipient.key,
                                     partner.recipient.route)
