# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from zope.interface import implements
from twisted.python import components

from feat.common import log, serialization, fiber, annotate
from feat.agents.base import replay, recipient, requester
from feat.interface.protocols import InitiatorFailed


class DefinitionError(Exception):
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
            raise RuntimeError('Expected at most one partner of the class %r'
                               ', found %d in %r' %\
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

        def _ignore_initiator_failed(fail):
            if fail.check(InitiatorFailed):
                agent.log('Swallowing %r expection.', fail.value)
                return None
            else:
                agent.log('Reraising exception %r', fail)
                fail.raiseException()

        f = fiber.Fiber()
        f.add_callback(agent.initiate_protocol, self.recipient)
        f.add_callback(requester.GoodBye.notify_finish)
        f.add_errback(_ignore_initiator_failed)
        return f.succeed(requester.GoodBye)

    def on_goodbye(self, agent):
        if self.allocation_id:
            agent.release_resource(self.allocation_id)

    def __eq__(self, other):
        return self.recipient == other.recipient and\
               self.allocation_id == other.allocation_id

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
    def query(self, state, name):
        partners = state.agent.get_descriptor().partners
        return self._relations[name].query(partners)

    @replay.immutable
    def query_with_role(self, state, name, role):
        partners = state.agent.get_descriptor().partners
        return self._relations[name].query_with_role(partners, role)

    @replay.immutable
    def find(self, state, recp):
        desc = state.agent.get_descriptor()
        match = [x for x in desc.partners if x.recipient == recp]
        if len(match) == 0:
            return None
        elif len(match) > 1:
            raise RuntimeError('More than one partner was matched by the '
                               'recipient %r!', recp)
        else:
            return match[0]

    @replay.mutable
    def create(self, state, partner_class, recp,
               allocation_id=None, role=None):
        f = self.find(recp)
        if f:
            self.info('We already are in partnership with recipient '
                      '%r, instance: %r.', recp, f)
            return

        factory = self.query_handler(partner_class, role)
        partner = factory(recp, allocation_id, role)
        self.debug(
            'Registering partner %r (lookup (%r, %r)) for recipient: %r',
            factory, partner_class, role, recp)
        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, partner.initiate, state.agent)
        f.add_callback(fiber.drop_result, state.agent.update_descriptor,
                       self._append_partner, partner)
        return f.succeed()

    @replay.mutable
    def on_goodbye(self, state, recp):
        partner = self.find(recp)
        if partner is None:
            self.warning(
                "Didn't find a partner matching the goodbye sender :%r!", recp)
            return None

        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, state.agent.update_descriptor,
                       self._remove_partner, partner)
        f.add_callback(fiber.drop_result, partner.on_goodbye, state.agent)
        return f.succeed()

    # private

    def _append_partner(self, desc, partner):
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


@serialization.register
class RecipientFromPartner(recipient.BaseRecipient):

    implements(recipient.IRecipient, recipient.IRecipients)

    type_name = 'recp_p'

    def __init__(self, partner):
        recipient.BaseRecipient.__init__(self)
        self.shard = partner.recipient.shard
        self.key = partner.recipient.key

    @property
    def type(self):
        return recipient.RecipientType.agent


components.registerAdapter(RecipientFromPartner, BasePartner,
                           recipient.IRecipient)
components.registerAdapter(RecipientFromPartner, BasePartner,
                           recipient.IRecipients)
