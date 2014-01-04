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
import copy
import types

from zope.interface import implements
from twisted.trial.unittest import FailTest

from feat.agencies import replay, agency, contracts, requests
from feat.common import serialization, guard, journal, reflect, fiber
from feat.agents.base import resource, agent, partners
from feat.agencies.message import BaseMessage
from feat.test import common, factories

from feat.interface.journal import *


def side_effect(fun_or_name, result=None, args=None, kwargs=None):
    if isinstance(fun_or_name, (types.FunctionType, types.MethodType, )):
        name = reflect.canonical_name(fun_or_name)
    else:
        name = fun_or_name
    return (name, args or None, kwargs or None, result)


def message(**params):
    return CompareObject(BaseMessage, **params)


class CompareObject(object):

    def __init__(self, type, **params):
        self.params = params
        self.type = type

    def __eq__(self, other):
        if not isinstance(other, self.type):
            return False
        for key in self.params:
            v = getattr(other, key)
            if self.params[key] != v:
                return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)


# instance matching everything
whatever = CompareObject(object)


def _clone(value):
    return copy.deepcopy(value)


class BaseSideEffect(object):

    def _extract_fun_id(self, something):
        if something is None:
            return something
        if isinstance(something, (types.FunctionType, types.MethodType)):
            return reflect.canonical_name(something)
        return something

    def _se2str(self, *args):
        return replay.side_effect_as_string(*args)

    def _error(self, msg, *args):
        raise ReplayError("%s %s instead of %s"
                          % (msg, self._se2str(*args), str(self)))


class SideEffect(BaseSideEffect):

    def __init__(self, result, fun_id, *args, **kwargs):
        self._result = _clone(result)
        self._fun_id = self._extract_fun_id(fun_id)
        self._args = _clone(args)
        self._kwargs = _clone(kwargs)

    def __str__(self):
        return self._se2str(self._fun_id, self._args,
                            self._kwargs, self._result)

    def __call__(self, fun_id, *args, **kwargs):
        if self._fun_id != fun_id:
            self._error("Unexpected side-effect", fun_id, args, kwargs)

        if self._args != args:
            self._error("Unexpected side-effect arguments",
                        fun_id, args, kwargs)

        if self._kwargs != kwargs:
            self._error("Unexpected side-effect keywords",
                        fun_id, args, kwargs)

        return self._result


class AnySideEffect(BaseSideEffect):

    def __init__(self, result=None, fun_id=None):
        self._result = _clone(result)
        self._fun_id = self._extract_fun_id(fun_id)

    def __str__(self):
        return self._se2str(self._fun_id, None, None, self._result)

    def __call__(self, fun_id, *args, **kwargs):
        if self._fun_id is not None:
            if fun_id != self._fun_id:
                self._error("Unexpected side-effect",
                            (fun_id, args, kwargs),
                            (self._fun_id, None, None))
        return self._result


class HamsterCall(object):

    implements(IJournalReplayEntry)

    def __init__(self, function):
        assert hasattr(function, "__self__")
        assert IRecorder.providedBy(function.__self__)
        self._recorder = function.__self__
        self._function = function
        self._side_effects = []
        self._next_effect = 0

    def __call__(self, *args, **kwargs):
        self._next_effect = 0 # Reseeting side-effect index
        result = journal.replay(self, self._function, *args, **kwargs)

        if self._next_effect < len(self._side_effects):
            remaining = self._side_effects[self._next_effect:]
            raise ReplayError("Unconsumed side_effects: %s"
                              % ", ".join([str(v) for v in remaining]))

        return result

    def get_state(self):
        return self._recorder._get_state()

    def add_side_effect(self, result, *args, **kwargs):
        '''
        There are various ways of adding a side effect:
          - args is empty and result is a BaseSideEffect sub-class:
            call.add_side_effect(SideEffect(42, "fun_name", some_arg))
          - args is empty and result is use as a AnySideEffect result:
            call.add_side_effect("foo")
          - args is not empty, the first argument is a function identifier
            or a function:
            call.add_side_effect(42, agent.initiate, param, key=word)
        '''
        if not args:
            if isinstance(result, SideEffect):
                side_effect = result
            else:
                side_effect = AnySideEffect(result)
        else:
            side_effect = SideEffect(result, *args, **kwargs)

        self._side_effects.append(side_effect)
        return self

    ### IJournalReplayEntry Methods ###

    def get_arguments(self):
        raise NotImplementedError()

    def rewind_side_effects(self):
        raise NotImplementedError()

    def next_side_effect(self, function_id, *args, **kwargs):
        if self._next_effect >= len(self._side_effects):
            raise ReplayError("Unexpected side-effect %s"
                              % self._se2str((function_id, args, kwargs)))

        side_effect = self._side_effects[self._next_effect]
        self._next_effect += 1
        return side_effect(function_id, *args, **kwargs)

    def _se2str(self, *args):
        return replay.side_effect_as_string(*args)


class Hamsterball(replay.Replay):

    implements(journal.IRecorderNode, serialization.ISerializable)

    type_name = 'testsuite-driver'

    def __init__(self):
        self.journal_keeper = self
        self._recorder_count = 0
        SingletonFactory(self)
        replay.Replay.__init__(self, None, u'agent-under-test')

    def reset(self):
        replay.Replay.reset(self)
        self.descriptor = None

    def load(self, instance):
        snapshot = self.serializer.convert(instance)
        result = self.unserializer.convert(snapshot)

        # search agent in the registry and generate the descriptor for it
        search_agent = [x for x in self.registry.values()\
                        if isinstance(x, agent.BaseAgent)]
        if len(search_agent) == 1:
            self.agent = search_agent[0]
            self.reset_descriptor()
        return result

    def reset_descriptor(self):
        self.descriptor = factories.build(type(self.agent).descriptor_type,
                                          doc_id=self.agent_id)

    def call(self, side_effects, function, *args, **kwargs):
        call = self.generate_call(function)
        if side_effects:
            for se_funid, se_args, se_kwargs, se_result in side_effects:
                call.add_side_effect(se_result, se_funid,
                                     *(se_args or ()), **(se_kwargs or {}))
        output = call(*args, **kwargs)
        return output, call.get_state()

    # generating instances for tests

    def generate_call(self, function):
        return HamsterCall(function)

    def generate_resources(self, agent):
        return self.generate_utility_class(agent, resource.Resources)

    def generate_partners(self, agent):
        return self.generate_utility_class(agent, agent.partners_class)

    def generate_utility_class(self, agent, factory):
        instance = self.generate_instance(factory)
        instance.init_state(instance.state, agent)
        return instance

    def generate_agent(self, factory):
        instance = self.generate_instance(factory)
        instance.state.medium = agency.AgencyAgent.__new__(agency.AgencyAgent)

        def return_agent_id():
            return self.agent_id

        setattr(instance.state.medium, 'snapshot', return_agent_id)
        return instance

    def generate_interest(self):
        return agency.Interest.__new__(agency.Interest)

    def generate_manager(self, agent, factory):
        medium = contracts.AgencyManager.__new__(contracts.AgencyManager)
        return self.generate_listener(agent, factory, medium)

    def generate_contractor(self, agent, factory):
        medium = contracts.AgencyContractor.__new__(contracts.AgencyContractor)
        return self.generate_listener(agent, factory, medium)

    def generate_requester(self, agent, factory):
        medium = requests.AgencyRequester.__new__(requests.AgencyRequester)
        return self.generate_listener(agent, factory, medium)

    def generate_replier(self, agent, factory):
        medium = requests.AgencyReplier.__new__(requests.AgencyReplier)
        return self.generate_listener(agent, factory, medium)

    def generate_listener(self, agent, factory, medium):
        instance = self.generate_instance(factory)
        instance.state.medium = medium
        instance.state.agent = agent
        return instance

    def generate_instance(self, factory):
        factory = serialization.IRestorator(factory)

        magic_instance = factory.__new__(factory)
        journal.RecorderNode.__init__(magic_instance, self)

        state = guard.MutableState()
        j_snapshot = journal.RecorderNode.snapshot(magic_instance)
        full = (j_snapshot, state, )

        def return_value(value):

            def snapshot():
                return value

            return snapshot

        setattr(magic_instance, 'snapshot', return_value(full))
        setattr(magic_instance, 'state', state)
        setattr(magic_instance, '_get_state', return_value(state))

        return magic_instance

    # IRecorderNode

    def generate_identifier(self, recorder):
        self._recorder_count += 1
        return (self._recorder_count, )

    def new_entry(self, *_):
        raise NotImplementedError()

    # ISerializable

    def snapshot(self):
        return None

    # IExternalizer

    def identify(self, instance):
        if (journal.IRecorder.providedBy(instance) and
            instance.journal_id in self.registry):
            return instance.journal_id


class SingletonFactory(object):
    '''
    This class uses evil in its pure form to inject the reference passed to the
    construct as the unserialization result of the given object type.

    The singleton here means, that every unserialized object of this type
    will be point to the reference.
    '''

    implements(serialization.IRestorator)

    def __init__(self, instance):
        self.instance = instance
        self.type_name = instance.type_name
        serialization.register(self)

    def restore(self, _):
        return self.instance

    def prepare(self):
        return None


class TestCase(common.TestCase):

    def setUp(self):
        self.ball = Hamsterball()

    def assertFiberTriggered(self, f, t_type, value=None):
        tt, vv = f.snapshot()[0:2]
        self.assertEqual(t_type, tt)
        self.assertEqual(value, vv)

    def assertFiberCalls(self, f, expected, args=None, kwargs=None):
        if self.fiber_find_call(f, expected, args, kwargs) is None:
            raise FailTest("Call %r not found in the fiber" % expected)

    def assertFiberDoesntCall(self, f, expected, args=None, kwargs=None):
        if self.fiber_find_call(f, expected, args, kwargs) is not None:
            raise FailTest("Found call %r in the fiber." % expected)

    def fiber_find_call(self, f, expected, args=None, kwargs=None):
        calllist = f.snapshot()[2]
        index = -1
        for cb, err in calllist:
            index += 1
            call, cargs, ckwargs = cb
            if call == fiber.drop_param:
                call, cargs = cargs[0], cargs[1:]
            if call == expected:
                self.info('Call %r found, checking args and kwargs', expected)
                if args is not None and args != cargs:
                    self.info("Args didn't match %r != %r", args, cargs)
                    continue
                if kwargs is not None and kwargs != ckwargs:
                    self.info("Kwargs didn't match %r != %r", kwargs, ckwargs)
                    continue
                return index
        return None
