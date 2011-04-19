# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import types

from twisted.python import components

from feat.common import log, serialization, fiber, annotate
from feat.agents.base import replay, recipient, requester


ACCEPT_RESPONSABILITY = "___I'm on it___"


class DefinitionError(Exception):
    pass


@serialization.register
class DoublePartnership(Exception, serialization.Serializable):
    pass


@serialization.register
class FindPartnerError(Exception, serialization.Serializable):
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
                (self.factory, len(partners), partners))
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


@serialization.register
class BasePartner(serialization.Serializable):

    type_name = 'partner'

    def __init__(self, recp, allocation_id=None, role=None):
        self.recipient = recipient.IRecipient(recp)
        self.allocation_id = allocation_id
        self.role = role

    def initiate(self, agent):
        pass

    def on_shutdown(self, agent):
        agent.log('Shutdown handler sending goodbye, for '
                  'agent %r partner %r.', agent, self)
        brothers = agent.query_partners(type(self))
        return requester.say_goodbye(agent, self.recipient, brothers)

    def on_goodbye(self, agent, payload=None):
        '''
        Called when the partner goes through the termination procedure.
        @param payload: By default list of the partner of the same class
                        of the agent.
        '''

    def on_died(self, agent, payload=None):
        '''
        Called by the monitoring agent, when he detects that the partner has
        died. If your handler is going to solve this problem return the
        ACCEPT_RESPONSABILITY constant.

        @param payload: Same as in on_goodbye.
        '''

    def on_restarted(self, agent, migrated):
        '''
        Called after the partner is restarted by the monitoring agent.
        @param migrated: Flag saying whether the IRecipient of partner has
                         changed
        '''

    def on_burried(self, agent, payload=None):
        '''
        Called when all the hope is lost. Noone took the responsability for
        handling the agents death, and monitoring agent failed to restart it.

        @param payload: Same as in on_goodbye.
        '''

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.recipient == other.recipient and\
               self.allocation_id == other.allocation_id and\
               self.role == other.role

    def __ne__(self, other):
        return not self.__eq__(other)


class Partners(log.Logger, log.LogProxy, replay.Replayable):

    log_category = "partners"

    default_handler = BasePartner

    has_many("all", "whatever", BasePartner, force=True)

    def __init__(self, agent):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        replay.Replayable.__init__(self, agent)
        self.log_name = type(self).__name__

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
        serialization.register(cls)

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
        if existing:
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
        if isinstance(name_or_class, types.TypeType) and \
            issubclass(name_or_class, BasePartner):
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
        desc = state.agent.get_descriptor()
        match = [x for x in desc.partners if x.recipient == recp]
        if len(match) == 0:
            return None
        elif len(match) > 1:
            raise FindPartnerError('More than one partner was matched by the '
                                   'recipient %r!', recp)
        else:
            return match[0]

    @replay.mutable
    def create(self, state, partner_class, recp,
               allocation_id=None, role=None, substitute=None):
        found = self.find(recp)
        if found:
            self.info('We already are in partnership with recipient '
                      '%r, instance: %r.', recp, found)
            return

        factory = self.query_handler(partner_class, role)
        partner = factory(recp, allocation_id, role)
        self.debug(
            'Registering partner %r (lookup (%r, %r)) for recipient: %r',
            factory, partner_class, role, recp)

        if substitute:
            self.debug('It will substitute: %r', substitute)

        f = fiber.succeed()
        if allocation_id:
            f.add_callback(fiber.drop_result,
                           state.agent.check_allocation_exists,
                           allocation_id)
        f.add_callback(fiber.drop_result, self.initiate_partner, partner)
        f.add_callback(fiber.drop_result, state.agent.update_descriptor,
                       self._append_partner, partner, substitute)
        return f

    @replay.immutable
    def initiate_partner(self, state, partner):
        return partner.initiate(state.agent)

    @replay.mutable
    def receive_notification(self, state, recp, notification_type,
                             blackbox):
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
        return handler(partner, blackbox)

    @replay.mutable
    def remove(self, state, partner):
        # FIXME: Two subsequent updates of descriptor.
        f = fiber.succeed()
        f.add_callback(fiber.drop_result, state.agent.update_descriptor,
                       self._remove_partner, partner)
        if partner.allocation_id:
            f.add_callback(fiber.drop_result, state.agent.release_resource,
                           partner.allocation_id)
        return f

    # handlers for incoming notifications from/about partners

    def _on_goodbye(self, partner, blackbox):
        return self._remove_and_trigger_cb(partner, 'on_goodbye', blackbox)

    def _on_burried(self, partner, blackbox):
        return self._remove_and_trigger_cb(partner, 'on_burried', blackbox)

    @replay.immutable
    def _on_died(self, state, partner, blackbox):
        return fiber.wrap_defer(partner.on_died, state.agent, blackbox)

    @replay.immutable
    def _on_restarted(self, state, partner, new_address):
        moved = (new_address != partner.recipient)
        f = fiber.succeed()
        if moved:
            f.add_callback(fiber.drop_result, state.agent.update_descriptor,
                           self._update_recipient, partner, new_address)
        f.add_callback(fiber.drop_result, self._call_next_cb,
                       partner.on_restarted, moved)
        return f

    # private

    def _remove_and_trigger_cb(self, partner, cb_name, blackbox):
        callback = getattr(partner, cb_name, None)
        assert callable(callback)
        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, self.remove, partner)
        f.add_callback(fiber.drop_result, self._call_next_cb,
                       callback, blackbox)
        return f.succeed()

    @replay.immutable
    def _call_next_cb(self, state, method, blackbox):
        # This is done outside the currect execution chain, as the
        # action performed may be arbitrary long running, and we don't want
        # to run into the timeout of goodbye request
        state.agent.call_next(method, state.agent, blackbox)

    def _get_relation(self, name):
        try:
            return self._relations[name]
        except KeyError:
            raise ValueError('Unknown relation name %r: ' % (name, ))

    def _update_recipient(self, desc, partner, new_recp):
        index = desc.partners.index(partner)
        partner.recipient = new_recp
        desc.partners[index] = partner
        return partner

    def _append_partner(self, desc, partner, substitute):
        if substitute:
            self._remove_partner(desc, substitute)
        desc.partners.append(partner)
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


class RecipientFromPartner(recipient.Recipient):

    type_name = 'recipient'

    def __init__(self, partner):
        recipient.Recipient.__init__(self, partner.recipient.key,
                                     partner.recipient.shard)


components.registerAdapter(RecipientFromPartner, BasePartner,
                           recipient.IRecipient)
components.registerAdapter(RecipientFromPartner, BasePartner,
                           recipient.IRecipients)
