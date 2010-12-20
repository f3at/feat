# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import copy

from feat.agents.base import (agent, message, contractor, manager, recipient,
                              descriptor, document, )
from feat.common import enum, fiber
from feat.interface.protocols import InterestType
from feat.interface.contracts import ContractState
from feat.agents.host import host_agent


@agent.register('shard_agent')
class ShardAgent(agent.BaseAgent):

    def initiate(self):
        agent.BaseAgent.initiate(self)

        self.resources.define('hosts', 10)
        self.resources.define('children', 2)

        desc = self.medium.get_descriptor()
        for x in range(len(desc.children)):
            self.resource.allocate(children=1)
        for x in range(len(desc.hosts)):
            self.resource.allocate(hosts=1)

        interest = self.medium.register_interest(JoinShardContractor)
        if (self.medium.get_descriptor()).parent is None:
            interest.bind_to_lobby()

    @agent.update_descriptor
    def add_children_shard(self, descriptor, child):
        descriptor.children.append(child)
        return child

    @agent.update_descriptor
    def add_agent(self, descriptor, agent):
        descriptor.hosts.append(agent)


class JoinShardContractor(contractor.BaseContractor):

    protocol_id = 'join-shard'
    interest_type = InterestType.public

    @fiber.woven
    def announced(self, announcement):
        self.preallocation = self.agent.resources.preallocate(hosts=1)
        self.nested_manager = None
        action_type = None

        # check if we can serve the request on our own
        if self.preallocation:
            action_type = ActionType.join
            cost = 0
        else:
            self.preallocation = self.agent.resources.preallocate(children=1)
            if self.preallocation:
                action_type = ActionType.create
                cost = 20

        # create a bid for our own action
        bid = None
        if action_type is not None:
            bid = message.Bid()
            bid.payload['action_type'] = action_type
            cost += announcement.payload['level'] * 15
            bid.bids = [cost]

        f = fiber.Fiber()
        if action_type != ActionType.join:
            f.add_callback(self._fetch_children_bids, announcement)
        f.add_callback(self._pick_best_bid, bid)
        f.add_callback(self._bid_refuse_or_handover, bid)
        f.add_callback(self._terminate_nested_manager)
        f.succeed(None)
        return f

    def _fetch_children_bids(self, _, announcement):
        desc = self.agent.medium.get_descriptor()
        recipients = map(lambda shard: recipient.Agent(shard, shard),
                         desc.children)
        if len(recipients) == 0:
            return list()

        new_announcement = copy.deepcopy(announcement)
        new_announcement.payload['level'] += 1

        self.nested_manager = self.agent.medium.initiate_protocol(
            NestedJoinShardManager, recipients, new_announcement)
        f = fiber.Fiber()
        f.add_callback(self.nested_manager.wait_for_bids)
        f.succeed(None)
        return f

    def _terminate_nested_manager(self, _):
        if self.nested_manager:
            self.nested_manager.terminate()

    def _pick_best_bid(self, nested_bids, own_bid):
        # prepare the list of bids
        bids = list()
        if own_bid:
            bids.append(own_bid)
        if nested_bids is None:
            nested_bids = list()
        bids += nested_bids
        self.log('_pick_best_bid analizes total of %d bids', len(bids))

        # check if we have received anything
        if len(bids) == 0:
            self.info('Did not receive any bids to evaluate! '
                      'Contract will fail.')
            return None

        # elect best bid
        best = bids[0]
        for bid in bids:
            if bid.bids[0] < best.bids[0]:
                best = bid

        # Send refusals to contractors of nested manager which we already
        # know will not receive the grant.
        for bid in bids:
            if bid == best:
                continue
            elif bid in nested_bids:
                self.nested_manager.refuse_bid(bid)
        return best

    def _bid_refuse_or_handover(self, bid=None, original_bid=None):
        if bid is None:
            refusal = message.Refusal()
            return self.medium.refuse(refusal)
        elif bid == original_bid:
            return self.medium.bid(bid)
        else:
            self.release_preallocation()
            return self.medium.handover(bid)

    def release_preallocation(self, *_):
        if self.preallocation is not None:
            self.preallocation.release()

    announce_expired = release_preallocation
    rejected = release_preallocation
    expired = release_preallocation

    @fiber.woven
    def granted(self, grant):
        self.preallocation.confirm()

        joining_agent_id = self.medium.announce.reply_to.key

        if grant.payload['action_type'] == ActionType.create:
            f = fiber.Fiber()
            f.add_callback(self._prepare_child_descriptor)
            f.add_callback(self._request_start_agent)
            f.add_callback(self._extract_shard)
            f.add_callback(self.agent.add_children_shard)
            f.add_callback(self._finalize)
            f.succeed(joining_agent_id)
            return f
        else: # ActionType.join
            f = fiber.Fiber()
            f.add_callback(self.agent.add_agent)
            f.add_callback(self._get_our_shard)
            f.add_callback(self._finalize)
            f.succeed(joining_agent_id)
            return f

    def _get_our_shard(self, *_):
        return (self.agent.medium.get_descriptor()).shard

    def _get_our_id(self, *_):
        return (self.agent.medium.get_descriptor()).doc_id

    def _finalize(self, shard):
        report = message.FinalReport()
        report.payload['shard'] = shard
        self.medium.finalize(report)

    @fiber.woven
    def _prepare_child_descriptor(self, host_agent_id):
        f = fiber.Fiber()
        f.add_callback(generate_descriptor, hosts=[host_agent_id],
                      parent=self._get_our_id())
        f.succeed(self.agent.medium)
        return f

    @fiber.woven
    def _request_start_agent(self, desc):
        recp = self.medium.announce.reply_to
        f = fiber.Fiber()
        f.add_callback(self.agent.medium.initiate_protocol, recp, desc)
        f.add_callback(host_agent.StartAgentRequester.notify_finish)
        f.succeed(host_agent.StartAgentRequester)
        return f

    def _extract_shard(self, reply):
        return reply.payload['shard']


class NestedJoinShardManager(manager.BaseManager):

    protocol_id = 'join-shard'

    def __init__(self, agent, medium, announcement):
        manager.BaseManager.__init__(self, agent, medium)
        self._announcement = announcement

    def initiate(self):
        self.medium.announce(self._announcement)

    @fiber.woven
    def wait_for_bids(self, _):
        f = fiber.Fiber()
        f.add_callback(self.medium.wait_for_state)
        f.add_callback(lambda _: self.medium.contractors.keys())
        f.succeed(ContractState.closed)
        return f

    def refuse_bid(self, bid):
        self.debug('Sending refusal to bid from nested manager.')
        return self.medium.refuse(bid)

    def terminate(self):
        return self.medium._terminate()


class ActionType(enum.Enum):
    '''
    The type solution we are offering:

    join   - join the existing shard
    create - start your own ShardAgent as a child bid sender
    '''
    (join, create) = range(2)


@document.register
class Descriptor(descriptor.Descriptor):

    document_type = 'shard_agent'

    def __init__(self, parent=None, children=[], hosts=[], **kwargs):
        descriptor.Descriptor.__init__(self, **kwargs)
        self.parent = parent
        self.children = list()
        self.hosts = list()

    def get_content(self):
        c = descriptor.Descriptor.get_content(self)
        c['parent'] = self.parent
        c['hosts'] = self.hosts
        c['children'] = self.children
        return c


def generate_descriptor(connection, **options):
    desc = Descriptor(**options)

    def set_shard(desc):
        desc.shard = desc.doc_id
        return desc

    d = connection.save_document(desc)
    d.addCallback(set_shard)
    d.addCallback(connection.save_document)

    return d
