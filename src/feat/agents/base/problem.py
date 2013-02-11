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
import copy

from zope.interface import implements, Interface, Attribute

from feat.agents.base import task, contractor, manager, replay
from feat.agencies import message
from feat.common import fiber, log, serialization
from feat.agents.application import feat

from feat.interface.protocols import InterestType


class IProblemFactory(Interface):

    problem_id = Attribute('unique identifier of the problem')

    def __call__(agent, **kwargs):
        '''
        Construct the problem instance.
        '''


class IProblem(Interface):

    problem_id = Attribute('unique identifier of the problem')

    def get_keywords():
        '''
        Return the keywords used to create this problem instance.
        '''

    def wait_for_solution():
        '''
        Should return a fiber which will fire when the problem is solved.
        The trigger value will be passed to solve_for calls.
        '''

    def solve_for(solution, recp):
        '''
        Solve the problem for the agent with IRecipient recp.
        The solution param is the fiber trigger value of the
        wait_for_solution() fiber.
        '''

    def solve_localy():
        '''
        Called when decision is made that this agent will be the one resolving
        the problem.
        '''


class MetaBaseProblem(type(serialization.Serializable)):
    implements(IProblemFactory)

    problem_id = None


class BaseProblem(serialization.Serializable):
    implements(IProblem)
    __metaclass__ = MetaBaseProblem

    problem_id = None

    def __init__(self, agent, **kwargs):
        self.agent = agent
        self.kwargs = kwargs

    def get_keywords(self):
        return self.kwargs

    def wait_for_solution(self):
        pass

    def solve_for(self, solution, recp):
        pass

    def solve_localy(self):
        pass

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return self.kwargs == other.kwargs

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


class CollectiveSolver(task.BaseTask):

    protocol_id = 'problem-solver'
    timeout = 60

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
        f.add_callback(state.agent.initiate_protocol, resolver, state.problem)
        f.add_callback(lambda x: x.notify_finish())
        return f

    @replay.immutable
    def _prepare_retry(self, state, failure, original_list):
        '''
        Here we prepare to ask another brother to resolve our problem.
        The failure here is always ProtocolFailed. If contract finished
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


@feat.register_restorator
class SolveProblemInterest(serialization.Serializable):
    implements(contractor.IContractorFactory)

    def __init__(self, factory):
        self.factory = IProblemFactory(factory)
        self.protocol_id = 'solve-' + factory.problem_id
        self.protocol_type = SolveProblemContractor.protocol_type
        self.initiator = SolveProblemContractor.initiator
        self.interest_type = SolveProblemContractor.interest_type

    def __call__(self, agent, medium):
        instance = SolveProblemContractor(agent, medium, self.factory)
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
        if type(self) != type(other):
            return NotImplemented
        return not self.__eq__(other)


class SolveProblemContractor(contractor.BaseContractor):

    interest_type = InterestType.private

    def __init__(self, agent, medium, factory):
        log.Logger.__init__(self, medium)
        replay.Replayable.__init__(self, agent, medium, factory)

    def init_state(self, state, agent, medium, factory):
        state.agent = agent
        state.medium = medium
        state.factory = IProblemFactory(factory)
        state.problem = None

    @replay.mutable
    def announced(self, state, announcement):
        '''
        This part of contract is just to let the guy know we are here.
        '''
        state.problem = state.factory(state.agent, **announcement.payload)
        state.medium.bid(message.Bid())

    @replay.mutable
    def granted(self, state, grant):
        # make the fiber cancellable
        f = fiber.Fiber(state.medium.get_canceller())
        f.add_callback(fiber.drop_param, state.problem.wait_for_solution)
        f.add_callback(state.problem.solve_for, grant.reply_to)
        f.add_callback(fiber.drop_param, self._finalize)
        f.succeed()
        return f

    @replay.mutable
    def _finalize(self, state):
        report = message.FinalReport()
        state.medium.complete(report)


@feat.register_restorator
class SolveProblemManagerFactory(serialization.Serializable):
    implements(manager.IManagerFactory)

    def __init__(self, problem):
        self.problem = problem
        self.protocol_id = 'solve-' + problem.problem_id
        self.protocol_type = SolveProblemManager.protocol_type

    def __call__(self, agent, medium):
        instance = SolveProblemManager(agent, medium)
        instance.protocol_id = self.protocol_id
        return instance


class SolveProblemManager(manager.BaseManager):

    announce_timeout = 3
    grant_timeout = 20

    @replay.entry_point
    def initiate(self, state, problem):
        state.problem = problem
        announce = message.Announcement()
        announce.payload = state.problem.get_keywords()
        state.medium.announce(announce)

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
        # get wrapped in ProtocolFailed and removed by the logic of
        # HostAgent._prepare_retry
        return state.medium.get_recipients()

    def aborted(self):
        return None
