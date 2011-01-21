# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from zope.interface import implements
from twisted.python import components

from feat.common import log, serialization, fiber, annotate
from feat.agents.base import replay, recipient, requester


class Relation(object):

    def __init__(self, name, factory):
        self.name = name
        self.factory = factory

    def query(self, partners):
        return [x for x in partners if isinstance(x, self.factory)]


class ManyRelation(Relation):
    pass


class OneRelation(Relation):

    def query(self, partners):
        match = Relation.query(self, partners)
        if len(match) > 1:
            raise RuntimeError('Expected excatly one partner of the class %r'
                               ', found %d in %r' %\
                               (self.factory, len(partners), partners))
        elif len(match) == 1:
            return match[0]


def has_many(name, descriptor_type, factory, role=None):
    relation = ManyRelation(name, factory)
    _inject_definition(relation, descriptor_type, factory, role)


def has_one(name, descriptor_type, factory, role=None):
    relation = OneRelation(name, factory)
    _inject_definition(relation, descriptor_type, factory, role)


def _inject_definition(relation, descriptor_type, factory, role):
    annotate.injectClassCallback("handler", 4, "_define_handler",
                                 descriptor_type, factory, role)
    annotate.injectClassCallback("relation", 4, "_append_relation",
                                 relation)

    @property
    def getter(self):
        return self.query(relation.name)

    annotate.injectAttribute("relation_getter", 4, relation.name, getter)


@serialization.register
class BasePartner(serialization.Serializable):

    type_name = 'partner'

    def __init__(self, recp, allocation=None):
        self.recipient = recipient.IRecipient(recp)
        self.allocation = allocation

    def initiate(self, agent):
        pass

    def on_shutdown(self, agent):
        f = fiber.Fiber()
        f.add_callback(agent.initiate_protocol, self.recipient)
        f.add_callback(requester.GoodBye.notify_finish)
        return f.succeed(requester.GoodBye)

    def on_goodbye(self, agent):
        if self.allocation:
            agent.release_resource(self.allocation)

    def __eq__(self, other):
        return self.recipient == other.recipient and\
               self.allocation == other.allocation

    def __ne__(self, other):
        return not self.__eq__(other)


class Partners(log.Logger, log.LogProxy, replay.Replayable):

    log_category = "partners"

    default_handler = BasePartner

    def __init__(self, agent):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        replay.Replayable.__init__(self, agent)
        self.log_name = type(self).__name__

    def init_state(self, state, agent):
        state.agent = agent

    # managing the handlers

    @classmethod
    def __class__init__(cls, name, bases, dct):
        # agent.descriptor_type -> HandlerFactory
        cls._handlers = dict()
        # name -> Relation
        cls._relations = dict()
        cls._define_default_handler(cls.default_handler)
        serialization.register(cls)

    @classmethod
    def query_handler(cls, identifier, role=None):
        '''
        Lookup the handler for the giving idetifier (descriptor_type) and role.
        In case it was not found return the default.
        '''
        key = cls._key_for(identifier, role)
        resp = cls._handlers.get(key, cls._handlers['_default'])
        return resp

    @classmethod
    def _define_default_handler(cls, factory):
        cls._handlers['_default'] = factory

    @classmethod
    def _append_relation(cls, relation):
        assert isinstance(relation, Relation)
        cls._relations[relation.name] = relation

    @classmethod
    def _define_handler(cls, agent_class, factory, role=None):
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
    def create(self, state, partner_class, recp, allocation=None, role=None):
        f = self.find(recp)
        if f:
            self.info('We already are in partnership with recipient '
                      '%r, instance: %r.', recp, f)
            return

        factory = self.query_handler(partner_class, role)
        partner = factory(recp, allocation)
        self.debug(
            'Registering partner %r (lookup (%r, %r)) for recipient: %r',
            factory, partner_class, role, recp)
        f = fiber.Fiber()
        f.add_callback(partner.initiate)
        f.add_callback(fiber.drop_result, state.agent.update_descriptor,
                       self._append_partner, partner)
        return f.succeed(state.agent)

    @replay.mutable
    def on_goodbye(self, state, recp):
        partner = self.find(recp)
        if partner is None:
            self.warning(
                "Didn't find a partner matching the goodbye sender :r!", recp)
            return None

        f = fiber.Fiber()
        f.add_callback(partner.on_goodbye)
        f.add_both(fiber.drop_result, state.agent.update_descriptor,
                   self._remove_partner, partner)
        return f.succeed(state.agent)

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
        desc = state.agent.get_descriptor()
        p = []
        if desc:
            p = ["%r (%r)" % (type(x).name, x.allocation, ) \
                 for x in desc.partners]
        return "<Partners: [%s]>" % ', '.join(p)


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
