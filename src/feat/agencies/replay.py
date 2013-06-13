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

from pprint import pformat
import sys

from zope.interface import implements, classProvides

from feat.common import serialization, log, text_helper, deep_compare, error
from feat.agents.base import replay
from feat.common.serialization import banana

from feat.interface.agent import IAgencyAgent
from feat.interface.generic import ITimeProvider
from feat.interface.journal import (IJournalReplayEntry, ReplayError,
                                    IEffectHandler, IRecorder, IRecorderNode,
                                    NoHamsterballError, IJournalKeeper, )
from feat.interface.replier import IAgencyReplier
from feat.interface.requester import IAgencyRequester
from feat.interface.manager import IAgencyManager
from feat.interface.contractor import IAgencyContractor
from feat.interface.serialization import (IExternalizer, ISerializable,
                                          IRestorator, )
from feat.interface.task import IAgencyTask
from feat.interface.collector import IAgencyCollector
from feat.interface.poster import IAgencyPoster
from feat.database.interface import IDatabaseClient


def side_effect_as_string(*args):
    '''
    side_effect_as_string() -> "ANY_FUNCTION(ANY_ARGS, ANY_KWARGS)"
    side_effect_as_string("foo") -> "foo(ANY_ARGS, ANY_KWARGS)"
    side_effect_as_string("foo", (42, )) -> "foo(42, ANY_KWARGS)"
    side_effect_as_string("foo", (42, 18)) -> "foo(42, 18, ANY_KWARGS)"
    side_effect_as_string("foo", (), {}) -> "foo()"
    side_effect_as_string("foo", (), {"barr": "spam"}) -> "foo(barr=\"spam\")"
    side_effect_as_string("foo", (), {}, None) -> "foo(): None"
    side_effect_as_string("foo", None, {}, 42) -> "foo(ANY_ARGS): 42"
    '''
    fun_id = "ANY_FUNCTION"
    se_args = None
    se_kwargs= None

    if len(args) > 0:
        fun_id = args[0] or "ANY_FUNCTION"

    if len(args) > 1:
        se_args = args[1]

    if len(args) > 2:
        se_kwargs = args[2]

    if se_args is None:
        args_desc = ["ANY_ARGS"]
    elif isinstance(se_args, tuple):
        args_desc = [repr(a) for a in se_args]
    else:
        args_desc = [str(se_args)]

    if se_kwargs is None:
        kwargs_desc = ["ANY_KWARGS"]
    elif isinstance(se_kwargs, dict):
        kwargs_desc = ["%s=%r" % (n, v) for n, v in se_kwargs.items()]
    else:
        kwargs_desc = [str(se_kwargs)]

    params = ", ".join(args_desc + kwargs_desc)
    text = "%s(%s)" % (fun_id, params)

    if len(args) < 5:
        return text

    if len(args) > 5:
        raise RuntimeError("Invalid side-effect specification")

    result = args[4]
    return text + ": " + repr(result)


class JournalReplayEntry(object):

    implements(IJournalReplayEntry)

    def __init__(self, replay, record):
        self._replay = replay

        self._record = record
        self._next_effect = 0
        self.result = self._replay.unserializer.convert(self.frozen_result)

    ### properties of the entry ###

    @property
    def agent_id(self):
        return self._record['agent_id']

    @property
    def instance_id(self):
        return self._record['instance_id']

    @property
    def journal_id(self):
        if not hasattr(self, '_journal_id'):
            self._journal_id = self._replay.unserializer.convert(
                self._record['journal_id'])
        return self._journal_id

    @property
    def function_id(self):
        return self._record['function_id']

    @property
    def fiber_id(self):
        return self._record['fiber_id']

    @property
    def fiber_depth(self):
        return self._record['fiber_depth']

    @property
    def _args(self):
        return self._record['args']

    @property
    def _kwargs(self):
        return self._record['kwargs']

    @property
    def _side_effects(self):
        if not hasattr(self, '_sfx'):
            self._sfx = self._replay.unserializer.convert(
                self._record['side_effects'])
        return self._sfx

    @property
    def frozen_result(self):
        return self._record['result']

    @property
    def _timestamp(self):
        return self._record['timestamp']

    ### public methods ###

    def apply(self):
        try:
            if self.agent_id != self._replay.agent_id:
                raise ReplayError("Tried to apply the entry belonging to the "
                                  "agent id: %r, but the Replay instance "
                                  "belogs to: %r" % (self.agent_id,
                                                     self._replay.agent_id))

            self._replay.set_current_time(self._timestamp)

            if self.journal_id == 'agency':
                self._replay.replay_agency_entry(self)
                return self

            self._replay._log_entry(self)

            self._replay.require_agent()
            instance = self._replay.registry.get(self.journal_id, None)
            if instance is None:
                raise ReplayError("Instance for journal_id %r not found "
                                 "in the registry when replaying %r"
                                 % (self.journal_id, self.function_id))

            result = instance.replay(self)

            if self._next_effect < len(self._side_effects):
                remaining = self._side_effects[self._next_effect]
                side_effect = self.restore_side_effect(remaining,
                                                       parse_args=True)
                function_id, args, kwargs, _effects, _result = side_effect
                se_desc = side_effect_as_string(function_id, args, kwargs)
                raise ReplayError("Function %s did not consume side-effect %s"
                                  % (self.function_id, se_desc))

            frozen_result = self._replay.serializer.freeze(result)
            unfrozen_result = self._replay.unserializer.convert(frozen_result)
            expected = self._replay.unserializer.convert(self.frozen_result)

            if unfrozen_result != expected:
                res = pformat(unfrozen_result)
                exp = pformat(expected)

                diffs = text_helper.format_diff(exp, res, "\n               ")
                raise ReplayError("Function %r replay result "
                                  "does not match recorded one.\n"
                                  "  RESULT:      %s\n"
                                  "  EXPECTED:    %s\n"
                                  "  DIFFERENCES: %s\n"
                                  % (self.function_id, res, exp, diffs))

            self._replay.log("State after the entry: %r",
                             self._replay.agent._get_state())

            return self
        except Exception as e:
            error.handle_exception(
                'replay', e, "Failed trying to apply instance %r entry %r: ",
                self.journal_id, self.function_id)
            raise

    def to_string(self, header=""):
        args, kwargs = self.get_arguments()
        side_effects = [side_effect_as_string(
            *self.restore_side_effect(se, parse_args=True))
                        for se in self._side_effects]
        return ("%sinstance:  %r.\n"
                "%sfunction:  %r.\n"
                "%sarguments: %r.\n"
                "%skeywords:  %r.\n"
                "%sresult:    %r.\n"
                "%sside-effects:\n"
                "%s%s"
                % (header, self.journal_id,
                   header, self.function_id,
                   header, args,
                   header, kwargs,
                   header, self._replay.unserializer.convert(
                       self.frozen_result),
                   header, header + "  ",
                   ("\n  " + header).join(side_effects)))

    def restore_side_effect(self, record, parse_args=False):
        fun_id, raw_args, raw_kwargs, raw_effects, result = record
        if parse_args:
            args = self._replay.unserializer.convert(raw_args) or ()
            kwargs = self._replay.unserializer.convert(raw_kwargs) or {}
        else:
            args = raw_args or ()
            kwargs = raw_kwargs or {}
        effects = ((effect_id,
                    self._replay.unserializer.convert(effect_args),
                    self._replay.unserializer.convert(effect_kwargs))
                   for effect_id, effect_args, effect_kwargs in raw_effects)
        return fun_id, args, kwargs, effects, result

    ### IJournalReplayEntry Methods ###

    def get_arguments(self):
        if not hasattr(self, '_unserialized_arguments'):
            # unserializing arguments results in recorders being created
            # registred, etc. It is important that it happens only once
            # for each entry. Here we store the result to later only
            # return it.
            args = self._replay.unserializer.convert(self._args) or ()
            kwargs = self._replay.unserializer.convert(self._kwargs) or {}
            self._unserialized_arguments = (args, kwargs)
        return self._unserialized_arguments

    def rewind_side_effects(self):
        self._next_effect = 0

    def next_side_effect(self, function_id, *args, **kwargs):

        def current_effect_as_string():
            frozen_args = self._replay.serializer.freeze(args)
            frozen_kwargs = self._replay.serializer.freeze(kwargs)
            new_args = self._replay.unserializer.convert(frozen_args)
            new_kwargs = self._replay.unserializer.convert(frozen_kwargs)
            return side_effect_as_string(function_id, new_args, new_kwargs)

        def expected_effect_as_string(raw_side_effect):
            side_effect = self.restore_side_effect(raw_side_effect,
                                                   parse_args=True)
            function_id, args, kwargs, _effects, _result = side_effect
            return side_effect_as_string(function_id, args, kwargs)

        if self._next_effect >= len(self._side_effects):
            unexpected_desc = current_effect_as_string()
            raise ReplayError("Unexpected side-effect %s"
                              % (unexpected_desc, ))

        raw_side_effect = self._side_effects[self._next_effect]
        self._next_effect += 1

        side_effect = self.restore_side_effect(raw_side_effect)
        exp_fun_id, exp_args, exp_kwargs, effects, result = side_effect

        if exp_fun_id != function_id:
            unexpected_desc = current_effect_as_string()
            expected_desc = expected_effect_as_string(raw_side_effect)
            raise ReplayError("Side-effect %s called instead of %s"
                              % (unexpected_desc, expected_desc))

        frozen_args = self._replay.serializer.freeze(args)
        if exp_args != frozen_args:
            unexpected_desc = current_effect_as_string()
            expected_desc = expected_effect_as_string(raw_side_effect)
            raise ReplayError("Bad side-effect arguments in %s, expecting %s."
                              % (unexpected_desc, expected_desc))

        kwargs = self._replay.serializer.freeze(kwargs)
        if exp_kwargs != kwargs:
            unexpected_desc = current_effect_as_string()
            expected_desc = expected_effect_as_string(raw_side_effect)
            raise ReplayError("Bad side-effect keywords in %s, "
                              " expecting %s"
                              % (unexpected_desc, expected_desc))

        for effect_id, effect_args, effect_kwargs in effects:
            self._replay.apply_effect(effect_id,
                        *effect_args, **effect_kwargs)

        return self._replay.unserializer.convert(result)


class Replay(log.LogProxy, log.Logger):
    '''
    Class managing the replay of the single agent.
    '''

    log_category = 'replay'

    implements(IExternalizer, IEffectHandler)

    def __init__(self, journal, agent_id, inject_dummy_externals=False):
        log_keeper = log.get_default() or log.FluLogKeeper()
        log.LogProxy.__init__(self, log_keeper)
        log.Logger.__init__(self, self)

        self.journal = journal
        self.unserializer = banana.Unserializer(externalizer=self)
        self.serializer = banana.Serializer(externalizer=self)
        self.inject_dummy_externals = inject_dummy_externals

        self.agent_type = None
        self.agent_id = agent_id
        Factory(self, 'agent-medium', AgencyAgent)
        Factory(self, 'db-connection', Connection)
        Factory(self, 'replier-medium', AgencyReplier)
        Factory(self, 'requester-medium', AgencyRequester)
        Factory(self, 'contractor-medium', AgencyContractor)
        Factory(self, 'manager-medium', AgencyManager)
        Factory(self, 'retrying-protocol', RetryingProtocol)
        Factory(self, 'periodic-protocol', PeriodicProtocol)
        Factory(self, 'task-medium', AgencyTask)
        Factory(self, 'collector-medium', AgencyCollector)
        Factory(self, 'poster-medium', AgencyPoster)

        self.reset()

    ### public methods ###

    def reset(self):
        # registry of Recorders: journal_id -> IRecorderNode
        self.registry = dict()
        # refrence to the agent medium instance (IAgencyAgent)
        self.medium = None
        # refrence to the agent instance being replayed (IAgent)
        self.agent = None
        # registry of dummy medium classes: id(instance) -> medium
        self.dummies = dict()
        # list of all the protocols
        self.protocols = list()

        # timestamp of the last entry applied, this is used by get_time()
        # calls perfromed from ExpDict's which is done outside the replayable
        # context to validate if the structures match the expected ones
        self._current_timestamp = None

    def snapshot_registry(self):
        '''
        Give the dictionary of recorders detached from the existing instances.
        It is safe to store those references for future use. Used by feattool.
        '''
        unserializer = banana.Unserializer(externalizer=self)
        serializer = banana.Serializer(externalizer=self)
        return unserializer.convert(serializer.convert(self.registry))

    def get_agent_type(self):
        return self.agent_type

    ### endof public section ###

    def get_time(self):
        # Here we could increase self._current_timestamp by the minimal
        # value to ensure that two subsequent calls of this function gives
        # different results. This is not implemented because of disagreemnt
        # whether this feature would cause or resolve more problems.
        return self._current_timestamp

    def set_current_time(self, epoch):
        self._current_timestamp = epoch

    def register(self, recorder):
        j_id = recorder.journal_id
        self.log('Registering recorder: %r, id: %r, id(recorder): %r',
                 recorder.__class__.__name__, j_id, id(recorder))
        if j_id in self.registry:
            raise ReplayError('Journal id: %r is already in registry!' %
                              (j_id, ))
        self.registry[j_id] = recorder

    def set_aa(self, medium):
        if self.medium is not None:
            raise ReplayError(
                'Replay instance already has the medium reference')
        self.medium = medium

    def __iter__(self):
        return self

    def next(self):
        record = self.journal.next()
        return JournalReplayEntry(self, record)

    def _log_entry(self, entry):
        self.log("<----------------- Applying entry:\n%s",
                 entry.to_string("  "))

    def _log_effect(self, effect_id, *args, **kwargs):
        self.log("<----------------- Applying effect:\n"
                 "  effect:    %r.\n"
                 "  arguments: %r.\n"
                 "  keywords:  %r."
                 % (effect_id, args, kwargs))

    def replay_agency_entry(self, entry):
        # Special case for snapshot call, because we don't want
        # to unserialize any arguments before reseting the registry.
        if entry.function_id == "snapshot":
            self.apply_snapshot(entry)
            return

        self._log_entry(entry)

        method = getattr(self, "effect_%s" % entry.function_id)
        args, kwargs = entry.get_arguments()
        return replay.replay(entry, method, *args, **kwargs)

    def effect_agent_created(self, agent_factory, dummy_id):
        if self.medium is not None:
            raise ReplayError(
                'Replay instance already has the medium reference')

        self.log_category = agent_factory.descriptor_type
        self.log_name = dummy_id[0]
        self.medium = AgencyAgent(self, dummy_id)
        self.register_dummy(dummy_id, self.medium)
        self.agent = agent_factory(self.medium)
        self.agent_type = self.agent.descriptor_type

    def effect_agent_deleted(self):
        self.reset()

    def effect_protocol_created(self, factory, medium, *args, **kwargs):
        self.require_agent()
        instance = factory(self.agent, medium)
        self.protocols.append(instance)

    def effect_protocol_deleted(self, journal_id, dummy_id):
        self.require_agent()
        instance = self.registry[journal_id]
        self.protocols.remove(instance)
        del(self.registry[journal_id])
        self.unregister_dummy(dummy_id)

    def apply_snapshot(self, entry):
        old_agent, old_protocols = self.agent, self.protocols
        self.reset()
        self.set_current_time(entry._timestamp)
        args, _kwargs = replay.replay(entry, entry.get_arguments)
        if not args:
            # we can get entry without the arguments in case it was
            # impossible to serialize the snapshot of the agent
            raise ReplayError("Malformed agent snapshot, reason: %r" %
                              (entry.result, ))
        snapshot = args[0]
        self._restore_snapshot(snapshot)
        self._check_snapshot(old_agent, old_protocols)
        self.agent_type = self.agent.descriptor_type

    # Managing the dummy registry:

    def register_dummy(self, dummy_id, dummy):
        if self.lookup_dummy(dummy_id) is not None:
            raise ReplayError("Tried to register dummy: %r class: %r second"
                              " time", dummy_id, dummy.__class__.__name__)
        self.dummies[dummy_id] = dummy

    def unregister_dummy(self, dummy_id):
        if self.lookup_dummy(dummy_id) is None:
            raise ReplayError("Treid to unregister dummy_id: %r "
                               "but not found.", dummy_id)
        del(self.dummies[dummy_id])

    def lookup_dummy(self, dummy_id):
        return self.dummies.get(dummy_id, None)

    ### IEffectHandler Methods ###

    def apply_effect(self, effect_id, *args, **kwargs):
        self._log_effect(effect_id, *args, **kwargs)
        method = getattr(self, "effect_%s" % effect_id)
        return method(*args, **kwargs)

    ### IExternalizer Methods ###

    def identify(self, instance):
        if (IRecorder.providedBy(instance) and
            instance.journal_id in self.registry):
            return instance.journal_id

    def lookup(self, identifier):
        found = self.registry.get(identifier, None)
        if not found and self.inject_dummy_externals:
            found = DummyExternal(identifier)
        return found

    ### private ###

    def require_agent(self):
        if self.agent is None:
            raise NoHamsterballError()

    def _restore_snapshot(self, snapshot):
        self.agent, self.protocols = snapshot

    def _check_snapshot(self, old_agent, old_protocols):
        # check that the state so far matches the snapshop
        # if old_agent is None, it means that the snapshot is first entry
        # we are replaynig - hence we have no state to compare to
        if old_agent is not None:
            try:
                if self.agent != old_agent:
                    comp = deep_compare(self.agent._get_state(),
                                        old_agent._get_state())
                    info = "  INFO:        %s: %s\n" % comp if comp else ""

                    raise ReplayError("States of current agent mismatch the "
                                      "old agent\nInfo: %s\nOld: %s\n"
                                      "Loaded: %s."
                                      % (info,
                                         pformat(old_agent._get_state()),
                                         pformat(self.agent._get_state())))
                if len(self.protocols) != len(old_protocols):
                    raise ReplayError("The number of protocols mismatch. "
                                      "\nOld: %r\nLoaded: %r"
                                      % (old_protocols, self.protocols))
                else:
                    for protocol in self.protocols:
                        if protocol not in old_protocols:
                            raise ReplayError("One of the protocols was not "
                                              "found.\nOld: %s\nLoaded: %s"
                                              % (pformat(old_protocols),
                                                 pformat(self.protocols)))
            except RuntimeError, e:
                exc_info = sys.exc_info()
                raise ReplayError("Runtime error during replay of %s: %s"
                                  % (self.agent.type_name,
                                     error.get_exception_message(e))), \
                      None, exc_info[2]


@serialization.register
class DummyExternal(serialization.Serializable):

    type_name = 'unknown-reference'

    def __init__(self, identifier):
        self._identifier = identifier

    def __repr__(self):
        return "unknown at this point"


class BaseReplayDummy(log.LogProxy, log.Logger):

    implements(ISerializable)

    _outside_hamsterball_tag = True

    def __init__(self, replay, dummy_id):
        log.Logger.__init__(self, replay)
        log.LogProxy.__init__(self, replay)
        self._dummy_id = dummy_id
        self.replay = replay

    ### ISerializable Methods ###

    def restored(self):
        pass

    def snapshot(self):
        return self._dummy_id

    def __eq__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return True

    def __ne__(self, other):
        if type(self) != type(other):
            return NotImplemented
        return False


class StateMachineSpecific(object):

    @serialization.freeze_tag('StateMachineMixin.wait_for_state')
    def wait_for_state(self, state):
        raise RuntimeError('This should never be called!')

    @replay.named_side_effect("StateMachineMixin.get_canceller")
    def get_canceller(self):
        pass


class Factory(serialization.Serializable):

    implements(IRestorator)

    def __init__(self, replay, type_name, cls):
        self.replay = replay
        self.type_name = type_name
        self.cls = cls
        serialization.register(self)

    def restore(self, dummy_id):
        existing = self.replay.lookup_dummy(dummy_id)
        if existing:
            return existing
        new = self.cls(self.replay, dummy_id)
        self.replay.register_dummy(dummy_id, new)
        return new

    def prepare(self):
        return None


@serialization.register
class AgencyInterest(log.Logger):

    type_name = "agent-interest"

    _outside_hamsterball_tag = True

    classProvides(IRestorator)
    implements(ISerializable)

    def __eq__(self, other):
        if not hasattr(other, 'agent_factory'):
            return NotImplemented
        return self.agent_factory == other.agent_factory

    def __ne__(self, other):
        if not hasattr(other, 'agent_factory'):
            return NotImplemented
        return not self.__eq__(other)

    ### IRestorator Methods ###

    @classmethod
    def prepare(cls):
        return cls.__new__(cls)

    ### ISerializable Methods ###

    def snapshot(self):
        return self.agent_factory, self.args, self.kwargs

    def recover(self, snapshot):
        self.agent_factory, self.args, self.kwargs = snapshot

    ### IAgencyInterest Method ###

    @replay.named_side_effect('Interest.bind_to_lobby')
    def bind_to_lobby(self):
        pass

    @replay.named_side_effect('Interest.unbind_from_lobby')
    def unbind_from_lobby(self):
        pass


class Connection(BaseReplayDummy):

    type_name = "db-connection"

    implements(IDatabaseClient, ISerializable)

    ### IDatabaceClient ###

    @serialization.freeze_tag('IDatabaseClient.create_database')
    def create_database(self):
        raise RuntimeError('create_database() should never be called!')

    @serialization.freeze_tag('IDatabaseClient.save_document')
    def save_document(self, doc):
        raise RuntimeError('save_document() should never be called!')

    @serialization.freeze_tag('IDatabaseClient.get_attachment_body')
    def get_attachment_body(self, attachment):
        raise RuntimeError('get_attachment_body() should never be called!')

    @serialization.freeze_tag('IDatabaseClient.get_document')
    def get_document(self, doc_id):
        raise RuntimeError('get_document() should never be called!')

    @serialization.freeze_tag('IDatabaseClient.get_revision')
    def get_revision(self, doc_id):
        raise RuntimeError('get_revision() should never be called!')

    @serialization.freeze_tag('IDatabaseClient.reload_database')
    def reload_document(self, doc):
        raise RuntimeError('reload_document() should never be called!')

    @serialization.freeze_tag('IDatabaseClient.delete_document')
    def delete_document(self, doc):
        raise RuntimeError('delete_document() should never be called!')

    @serialization.freeze_tag('IDatabaseClient.changes_listener')
    def changes_listener(self, filter_, callback, **kwargs):
        raise RuntimeError('changes_listener()should never be called!')

    @serialization.freeze_tag('IDatabaseClient.update_document')
    def update_document(self, doc, _method, *args, **kwargs):
        raise RuntimeError('update_document()should never be called!')

    @serialization.freeze_tag('IDatabaseClient.cancel_listener')
    @replay.named_side_effect('IDatabaseClient.cancel_listener')
    def cancel_listener(self, filter_):
        pass

    @serialization.freeze_tag('IDatabaseClient.query_view')
    def query_view(self, factory, **options):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('IDatabaseClient.disconnect')
    @replay.named_side_effect('IDatabaseClient.disconnect')
    def disconnect(self):
        pass

    @serialization.freeze_tag('IDatabaseClient.get_update_seq')
    def get_update_seq(self):
        raise RuntimeError('get_update_seq() never be called!')

    @serialization.freeze_tag('IDatabaseClient.get_changes')
    def get_changes(self, filter_=None, limit=None, since=0):
        raise RuntimeError('get_changes() should never be called!')

    @serialization.freeze_tag('IDatabaseClient.bulk_get')
    def bulk_get(self, doc_ids, consume_errors=True):
        raise RuntimeError('bulk_get() should never be called!')


class Agency(BaseReplayDummy):

    type_name = "agency"

    @serialization.freeze_tag('IAgency.get_config')
    @replay.named_side_effect('IAgency.get_config')
    def get_config(self):
        pass

    @serialization.freeze_tag('IAgency.start_agent')
    @replay.named_side_effect('IAgency.start_agent')
    def start_agent(self, *args, **kwargs):
        pass


class AgencyAgent(BaseReplayDummy):

    type_name = "agent-medium"

    implements(IAgencyAgent, ITimeProvider, IRecorderNode, IJournalKeeper)

    def __init__(self, replay, dummy_id):
        BaseReplayDummy.__init__(self, replay, dummy_id)
        self.journal_keeper = self
        self.replay = replay
        self.replay.set_aa(self)
        self.agency = Agency(replay, dummy_id=None)

    ### IAgencyAgent Methods ###

    @serialization.freeze_tag('AgencyAgent.get_own_address')
    @replay.named_side_effect('AgencyAgent.get_own_address')
    def get_own_address(self):
        pass

    @serialization.freeze_tag('AgencyAgent.create_external_route')
    @replay.named_side_effect('AgencyAgent.create_external_route')
    def create_external_route(self, backend_id, **kwargs):
        pass

    @serialization.freeze_tag('AgencyAgent.remove_external_route')
    @replay.named_side_effect('AgencyAgent.remove_external_route')
    def remove_external_route(self, backend_id, **kwargs):
        pass

    @replay.named_side_effect('AgencyAgent.get_tunneling_url')
    @serialization.freeze_tag('AgencyAgent.get_tunneling_url')
    def get_tunneling_url(self):
        pass

    @replay.named_side_effect('AgencyAgent.observe')
    def observe(self, _method, *args, **kwargs):
        pass

    @replay.named_side_effect('AgencyAgent.get_hostname')
    def get_hostname(self):
        pass

    @replay.named_side_effect('AgencyAgent.get_ip')
    def get_ip(self):
        pass

    @replay.named_side_effect('AgencyAgent.get_descriptor')
    def get_descriptor(self):
        pass

    @replay.named_side_effect('AgencyAgent.get_configuration')
    def get_configuration(self):
        pass

    @serialization.freeze_tag('AgencyAgent.update_descriptor')
    def update_descriptor(self, desc):
        pass

    @replay.named_side_effect('AgencyAgent.get_mode')
    def get_mode(self, component):
        pass

    @serialization.freeze_tag('AgencyAgent.upgrade_agency')
    @replay.named_side_effect('AgencyAgent.upgrade_agency')
    def upgrade_agency(self, upgrade_cmd):
        pass

    @serialization.freeze_tag('AgencyAgent.join_shard')
    def join_shard(self, shard):
        pass

    @serialization.freeze_tag('AgencyAgent.leave_shard')
    def leave_shard(self, shard):
        pass

    @serialization.freeze_tag('AgencyAgent.check_if_hosted')
    def check_if_hosted(self, agent_id):
        pass

    @serialization.freeze_tag('AgencyAgent.initiate_protocol')
    @replay.named_side_effect('AgencyAgent.initiate_protocol')
    def initiate_protocol(self, factory, *args, **kwargs):
        pass

    @replay.named_side_effect('AgencyAgent.revoke_interest')
    def revoke_interest(self, factory):
        pass

    @replay.named_side_effect('AgencyAgent.register_interest')
    def register_interest(self, factory):
        pass

    @serialization.freeze_tag('AgencyAgency.terminate')
    def terminate(self):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgency.terminate_hard')
    def terminate_hard(self):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgency.save_document')
    def save_document(self, document):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgency.reload_document')
    def reload_document(self, document):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgency.delete_document')
    def delete_document(self, document):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgent.register_change_listener')
    def register_change_listener(self, filter_, callback):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgent.cancel_change_listener')
    @replay.named_side_effect('AgencyAgent.cancel_change_listener')
    def cancel_change_listener(self, filter_):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgency.query_view')
    def query_view(self, factory, **options):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgency.get_attachment_body')
    def get_attachment_body(self, attachment):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgency.get_document')
    def get_document(self, document_id):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgent.get_database')
    @replay.named_side_effect('AgencyAgent.get_database')
    def get_database(self):
        raise RuntimeError('This should never be called!')

    @replay.named_side_effect('AgencyAgency.call_next')
    def call_next(self, method, *args, **kwargs):
        pass

    @replay.named_side_effect('AgencyAgency.call_later')
    def call_later(self, time_left, method, *args, **kwargs):
        pass

    @replay.named_side_effect('AgencyAgency.call_later_ex')
    def call_later_ex(self, time_left, method, args, kwargs, busy=True):
        pass

    @replay.named_side_effect('AgencyAgent.cancel_delayed_call')
    def cancel_delayed_call(self, call_id):
        pass

    @replay.named_side_effect("AgencyAgent.is_connected")
    def is_connected(self):
        pass

    @replay.named_side_effect('AgencyAgent.get_machine_state')
    def get_machine_state(self):
        pass

    @serialization.freeze_tag('StateMachineMixin.wait_for_state')
    @replay.named_side_effect('StateMachineMixin.wait_for_state')
    def wait_for_state(self, state):
        pass

    @replay.named_side_effect('AgencyAgent.get_base_gateway_url')
    def get_base_gateway_url(self):
        pass

    ### ITimeProvider Methods ###

    @replay.named_side_effect('AgencyAgent.get_time')
    def get_time(self):
        return self.replay.get_time()

    ### IJournalKeeper Methods ###

    def register(self, recorder):
        self.replay.register(recorder)

    ### IRecorderNone Methods ###

    def generate_identifier(self, recorder):
        if getattr(self, 'indentifier_generated', False):
            raise ReplayError("Indetifier for the recorder %r has already "
                              "been generated!" % (recorder, ))
        self._identifier_generated = True
        return self._dummy_id


    ### ISerializable Methods ###

    def snapshot(self):
        return self._dummy_id[0], self._dummy_id[1]


class AgencyProtocol(BaseReplayDummy, StateMachineSpecific):

    @serialization.freeze_tag('IAgencyProtocol.notify_finish')
    def notify_finish(self):
        pass

    @replay.named_side_effect('AgencyAgency.call_next')
    def call_next(self, method, *args, **kwargs):
        pass

    @replay.named_side_effect('AgencyAgency.call_later')
    def call_later(self, time_left, method, *args, **kwargs):
        pass

    @replay.named_side_effect('AgencyAgency.call_later_ex')
    def call_later_ex(self, time_left, method,
                      args=None, kwargs=None, busy=True):
        pass


class AgencyReplier(AgencyProtocol, StateMachineSpecific):

    implements(IAgencyReplier)

    type_name = "replier-medium"

    ### IAgencyReplier Methods ###

    @serialization.freeze_tag('AgencyReplier.reply')
    @replay.named_side_effect('AgencyReplier.reply')
    def reply(self, reply):
        pass


class AgencyRequester(AgencyProtocol, StateMachineSpecific):

    implements(IAgencyRequester)

    type_name = "requester-medium"

    ### IAgencyRequester Methods ###

    @replay.named_side_effect('AgencyRequester.request')
    def request(self, request):
        pass

    @replay.named_side_effect('AgencyRequester.get_recipients')
    def get_recipients(self):
        pass


class AgencyContractor(AgencyProtocol, StateMachineSpecific):

    implements(IAgencyContractor)

    type_name = "contractor-medium"

    ### IAgencyContractor Methods ###

    @serialization.freeze_tag('AgencyContractor.bid')
    @replay.named_side_effect('AgencyContractor.bid')
    def bid(self, bid):
        pass

    @serialization.freeze_tag('AgencyContractor.handover')
    @replay.named_side_effect('AgencyContractor.handover')
    def handover(self, bid):
        pass

    @replay.named_side_effect('AgencyContractor.refuse')
    def refuse(self, refusal):
        pass

    @replay.named_side_effect('AgencyContractor.defect')
    def defect(self, cancellation):
        pass

    @replay.named_side_effect('AgencyContractor.complete')
    def complete(self, report):
        pass

    @serialization.freeze_tag('AgencyContractor.update_manager_address')
    @replay.named_side_effect('AgencyContractor.update_manager_address')
    def update_manager_address(self, recp):
        pass


class AgencyManager(AgencyProtocol, StateMachineSpecific):

    implements(IAgencyManager)

    type_name = "manager-medium"

    ### IAgencyManager Methods ###

    @replay.named_side_effect('AgencyManager.announce')
    def announce(self, announce):
        pass

    @replay.named_side_effect('AgencyManager.reject')
    def reject(self, bid, rejection=None):
        pass

    @serialization.freeze_tag('AgencyManager.grant')
    @replay.named_side_effect('AgencyManager.grant')
    def grant(self, grants):
        pass

    @serialization.freeze_tag('AgencyManager.elect')
    @replay.named_side_effect('AgencyManager.elect')
    def elect(self, bid):
        pass

    @replay.named_side_effect('AgencyManager.cancel')
    def cancel(self, reason=None):
        pass

    @replay.named_side_effect('AgencyManager.terminate')
    @serialization.freeze_tag('AgencyManager.terminate')
    def terminate(self, result=None):
        pass

    @replay.named_side_effect('AgencyManager.get_bids')
    def get_bids(self):
        pass

    @replay.named_side_effect('AgencyManager.get_recipients')
    def get_recipients(self):
        pass


class AgencyTask(AgencyProtocol, StateMachineSpecific):

    type_name = "task-medium"

    implements(IAgencyTask)

    @replay.named_side_effect('AgencyTask.terminate')
    def finish(self, result=None):
        '''Deprecated.'''

    @serialization.freeze_tag('AgencyTask.terminate')
    @replay.named_side_effect('AgencyTask.terminate')
    def terminate(self, result=None):
        pass

    @replay.named_side_effect('AgencyTask.fail')
    def fail(self, failure):
        pass

    @replay.named_side_effect('AgencyTask.finished')
    def finished(self):
        pass

    @property
    def agent(self):
        return self.replay.medium


class AgencyCollector(AgencyProtocol):

    implements(IAgencyCollector)

    type_name = "collector-medium"

    ### IAgencyCollector Methods ###


class AgencyPoster(AgencyProtocol):

    implements(IAgencyPoster)

    type_name = "poster-medium"

    ### IAgencyPoster Methods ###

    @replay.named_side_effect('AgencyPoster.post')
    def post(self, message):
        pass


class RetryingProtocol(AgencyProtocol):

    type_name="retrying-protocol"

    @serialization.freeze_tag('RetryingProtocol.cancel')
    def cancel(self):
        pass

    @replay.named_side_effect('RetryingProtocol.get_status')
    def get_status(self):
        pass


class PeriodicProtocol(AgencyProtocol):

    type_name="periodic-protocol"

    @serialization.freeze_tag('PeriodicProtocol.cancel')
    def cancel(self):
        pass
