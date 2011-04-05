import copy

from zope.interface import implements

from feat.agents.base import task, contractor, manager, message, replay
from feat.common import serialization, fiber, log

from feat.interface.protocols import InterestType
from feat.interface.contracts import ContractState


class BaseProblem(serialization.Serializable):

    def __init__(self, agent):
        self.agent = agent

    def wait_for_solution(self):
        '''
        Should return a fiber which will fire when the problem is solved.
        The trigger value will be passed to solve_for calls.
        '''
        pass

    def solve_for(self, solution, recp):
        '''
        Solve the problem for the agent with IRecipient recp.
        The solution param is the fiber trigger value of the
        wait_for_solution() fiber.
        '''
        pass

    def solve_localy(self):
        '''
        Called when decision is made that this agent will be the one resolving
        the problem.
        '''

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return True

    def __ne__(self, other):
        return not self.__eq__(other)


class CollectiveSolver(task.BaseTask):

    protocol_id = 'problem-solver'
    timeout = 30

    @replay.mutable
    def initiate(self, state, problem, brothers):
        state.problem = problem
        return self._iterate(brothers)

    @replay.mutable
    def _iterate(self, state, brothers):
        own_address = state.agent.get_own_address()
        our_index = brothers.index(own_address)
        if our_index == 0:
            return state.problem.solve_localy()
        else:
            resolver = brothers[our_index - 1]
            f = self._ask_to_resolve(resolver)
            f.add_errback(self._prepare_retry, brothers)
            return f

    @replay.immutable
    def _ask_to_resolve(self, state, resolver):
        f = fiber.succeed(SolveProblemManagerFactory(state.problem))
        f.add_callback(state.agent.initiate_protocol, resolver)
        f.add_callback(lambda x: x.notify_finish())
        return f

    @replay.immutable
    def _prepare_retry(self, state, failure, original_list):
        '''
        Here we prepare to ask another brother to resolve our problem.
        The failure here is always InitiatorFailed. If contract finished
        without getting a bid (resolver is not there) we are removing the guy
        from our local list. If we just run into the timeout, we will retry
        in the same setup.
        '''
        failed_recipient = failure.value.args[0]
        new_list = copy.deepcopy(original_list)
        if failed_recipient is not None:
            if failed_recipient in new_list:
                new_list.remove(failed_recipient)
            else:
                self.error(
                    'I wanted to remove %r from %r, but it is not here!',
                    failed_recipient, new_list)
        return self._iterate(new_list)


@serialization.register
class SolveProblemInterest(serialization.Serializable):
    implements(contractor.IContractorFactory)

    def __init__(self, problem):
        self.problem = problem
        self.protocol_id = 'solve-' + problem.__class__.__name__
        self.protocol_type = SolveProblemContractor.protocol_type
        self.initiator = SolveProblemContractor.initiator
        self.interest_type = SolveProblemContractor.interest_type

    def __call__(self, agent, medium):
        instance = SolveProblemContractor(agent, medium, self.problem)
        instance.protocol_id = self.protocol_id
        return instance

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.protocol_id == other.protocol_id and\
               self.protocol_type == other.protocol_type and\
               self.initiator == other.initiator and\
               self.interest_type == other.interest_type

    def __ne__(self, other):
        return not self.__eq__(other)


class SolveProblemContractor(contractor.BaseContractor):

    interest_type = InterestType.private

    def __init__(self, agent, medium, problem):
        log.Logger.__init__(self, medium)
        replay.Replayable.__init__(self, agent, medium, problem)

    def init_state(self, state, agent, medium, problem):
        state.agent = agent
        state.medium = medium
        state.problem = problem

    @replay.journaled
    def announced(self, state, announcement):
        '''
        This part of contract is just to let the guy know we are here.
        '''
        state.medium.bid(message.Bid())

    @replay.mutable
    def granted(self, state, grant):
        f = state.problem.wait_for_solution()
        f.add_callback(fiber.bridge_result, state.medium.ensure_state,
                       ContractState.granted)
        f.add_callback(state.problem.solve_for, grant.reply_to)
        f.add_callback(fiber.drop_result, state.medium.ensure_state,
                       ContractState.granted)
        f.add_callback(fiber.drop_result, self._finalize)
        return f

    @replay.mutable
    def _finalize(self, state):
        report = message.FinalReport()
        state.medium.finalize(report)


@serialization.register
class SolveProblemManagerFactory(serialization.Serializable):
    implements(manager.IManagerFactory)

    def __init__(self, problem):
        self.problem = problem
        self.protocol_id = 'solve-' + problem.__class__.__name__
        self.protocol_type = SolveProblemManager.protocol_type

    def __call__(self, agent, medium):
        instance = SolveProblemManager(agent, medium)
        instance.protocol_id = self.protocol_id
        return instance


class SolveProblemManager(manager.BaseManager):

    @replay.journaled
    def initiate(self, state):
        state.medium.announce(message.Announcement())

    @replay.journaled
    def closed(self, state):
        bids = state.medium.get_bids()
        bid = bids[0]
        params = [(bid, message.Grant(), )]
        state.medium.grant(params)

    @replay.immutable
    def expired(self, state):
        # We didn't receive the bid. The host is not there. It needs to be
        # removed from the list. We return it from here, it will
        # get wrapped in InitiatorFailed and removed by the logic of
        # HostAgent._prepare_retry
        return state.medium.get_recipients()

    def aborted(self):
        return None
