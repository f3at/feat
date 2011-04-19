# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.agents.base import (agent, contractor, manager, partners,
                              message, replay, recipient, )
from feat.interface.protocols import InterestType
from feat.common import fiber, serialization


@serialization.register
class ShardPartner(partners.BasePartner):

    type_name = 'monitor->shard'


class Partners(partners.Partners):

    partners.has_one('shard', 'shard_agent', ShardPartner)


@agent.register('monitor_agent')
class MonitorAgent(agent.BaseAgent):

    partners_class = Partners

    @replay.entry_point
    def initiate(self, state):
        agent.BaseAgent.initiate(self)
        state.medium.register_interest(
            contractor.Service(MonitorContractor))
        state.medium.register_interest(MonitorContractor)

    @replay.journaled
    def handle_agent_death(self, state, recp):
        recp = recipient.IRecipient(recp)


class MonitorContractor(contractor.NestingContractor):

    protocol_id = 'request-monitor'
    interest_type = InterestType.private

    announce_timeout = 10

    @replay.entry_point
    def announced(self, state, announcement):
        msg = message.Bid()
        state.medium.bid(msg)

    @replay.entry_point
    def granted(self, state, grant):
        f = fiber.Fiber()
        f.add_callback(fiber.drop_result, self._create_partner,
                      grant)
        f.add_callbacks(self._finalize, self._granted_failed)
        return f.succeed()

    @replay.mutable
    def _create_partner(self, state, grant):
        f = fiber.Fiber()
        f.add_callback(state.agent.establish_partnership)
        return f.succeed(grant.reply_to)

    @replay.immutable
    def _granted_failed(self, state, failure):
        state.medium._error_handler(failure)
        msg = message.Cancellation(reason=str(failure.value))
        state.medium.defect(msg)

    @replay.immutable
    def _finalize(self, state, _):
        report = message.FinalReport()
        state.medium.finalize(report)
