# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import types

from zope.interface import implements
from twisted.trial.unittest import FailTest

from feat.agencies import replay, agency, contracts, requests
from feat.common import serialization, guard, journal, reflect, fiber
from feat.agents.base import resource, agent
from feat.agents.base.message import BaseMessage
from feat.test import common, factories


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
                print self.params[key], v
                return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)


# instance matching everything
whatever = CompareObject(object)


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

    def call(self, side_effects, method, *args, **kwargs):
        recorder = method.__self__
        fun_id = reflect.canonical_name(method)

        assert recorder in self.registry.values()
        left_se, output =\
            journal.replay(method, args or tuple(),
                           kwargs or dict(), side_effects or tuple())
        if left_se is not None:
            msg = 'There were unconsumed side_effects: '
            names = [x[0].__repr__() for x in left_se]
            msg += ', '.join(names)
            raise FailTest(msg)
        return output, recorder._get_state()

    # generating instances for tests

    def generate_resources(self, agent):
        instance = self.generate_instance(resource.Resources)
        instance.init_state(instance.state, agent)

    def generate_agent(self, factory):
        instance = self.generate_instance(factory)
        instance.state.medium = agency.AgencyAgent.__new__(agency.AgencyAgent)
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
        instance.init_state(instance.state, agent, medium)
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

        return magic_instance

    # IRecorderNode

    def generate_identifier(self, recorder):
        self._recorder_count += 1
        return (self._recorder_count, )

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
        calllist = f.snapshot()[2]
        for cb, err in calllist:
            call, cargs, ckwargs = cb
            if call == fiber.drop_result:
                call, cargs = cargs[0], cargs[1:]
            if call == expected:
                self.info('Call %r found, checking args and kwargs', expected)
                if args is not None and args != cargs:
                    self.info("Args didn't match %r != %r", args, cargs)
                    continue
                if kwargs is not None and kwargs != ckwargs:
                    self.info("Kwargs didn't match %r != %r", kwargs, ckwargs)
                    continue
                return True
        raise FailTest("Call %r not found in the fiber" % expected)
