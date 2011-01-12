# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from zope.interface import implements
from twisted.python import components

from feat.common import log, serialization, fiber, annotate
from feat.agents.base import replay, recipient, requester


class Relation(serialization.Serializable):

    def __init__(self, name, factory):
        self.name = name
        self.factory = factory

    def query(self, partners):
        return [x for x in partners if isinstance(x, self.factory)]

    def snapshot(self):
        return None


@serialization.register
class ManyRelation(Relation):
    pass


@serialization.register
class OneRelation(Relation):

    def query(self, partners):
        match = Relation.query(self, partners)
        if len(match) > 1:
            raise RuntimeError(
                'Expected excatly one partner of the class %r' % self.factory)
        elif len(match) == 1:
            return match[0]


@serialization.register
class Partners(log.Logger, log.LogProxy, replay.Replayable):

    log_category = "partners"

    def __init__(self, agent):
        log.Logger.__init__(self, agent)
        log.LogProxy.__init__(self, agent)
        replay.Replayable.__init__(self, agent)
        self.log_name = agent.descriptor_type

    def init_state(self, state, agent):
        state.agent = agent
        # agent.descriptor_type -> HandlerFactory
        state.handlers = dict()
        state.relations = dict()
        self.define_default_handler(BasePartner)

    # managing the handlers

    @replay.mutable
    def has_many(self, state, name, factory):
        state.relations[name] = ManyRelation(name, factory)

    @replay.mutable
    def has_one(self, state, name, factory):
        state.relations[name] = OneRelation(name, factory)

    @replay.mutable
    def define_handler(self, state, agent_class, factory, role=None):
        key = self._key_for(agent_class, role)
        state.handlers[key] = factory

    @replay.immutable
    def query_handler(self, state, partner_class, role=None):
        key = self._key_for(partner_class, role)
        resp = state.handlers.get(key, state.handlers['_default'])
        self.log("query_handler for key %r return %r", key, resp)
        return resp

    @replay.mutable
    def define_default_handler(self, state, factory):
        state.handlers['_default'] = factory

    # quering and updating

    @replay.immutable
    def query(self, state, name):
        partners = state.agent.get_descriptor().partners
        return state.relations[name].query(partners)

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

    def _key_for(self, factory, role):
        return (factory, role, )

    @replay.immutable
    def __repr__(self, state):
        desc = state.agent.get_descriptor()
        p = []
        if desc:
            p = ["%r (%r)" % (type(x).name, x.allocation, ) \
                 for x in desc.partners]
        return "<Partners: [%s]>" % ', '.join(p)


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
