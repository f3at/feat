from zope.interface import implements

from feat.common import serialization, log
from feat.agents.base import replay
from feat.common.serialization import pytree

from feat.interface.agent import *
from feat.interface.journal import *
from feat.interface.serialization import *


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

        (self.agent_id, self.journal_id, self.function_id,
         self.fiber_id, self.fiber_depth,
         self._args, self._kwargs,
         self._side_effects, self.frozen_result) = record

        self._next_effect = 0

    def apply(self):
        try:
            assert self.agent_id == self._replay.agent_id

            if self.journal_id == 'agency':
                self._replay.replay_agency_entry(self)
                return self

            self._replay._log_entry(self)

            instance = self._replay.registry.get(self.journal_id, None)
            if instance is None:
                raise ValueError("Instance for journal_id %r not found "
                                 "in the registry when replaying %r"
                                 % (self.journal_id, self.function_id))

            result = instance.replay(self)

            if self._next_effect < len(self._side_effects):
                remaining = self._side_effects[self._next_effect:]
                se_desc = ", ".join([side_effect_as_string(*v)
                                     for v in remaining])
                raise ReplayError("Unconsumed side_effects: %s"
                                  % se_desc)

            frozen_result = self._replay.serializer.freeze(result)

            if frozen_result != self.frozen_result:
                raise ReplayError("Function %r replay result "
                                  "do not match recorded one.\n"
                                  "  result:    %r\n"
                                  "  expecting: %r"
                                  % (self.function_id,
                                     frozen_result,
                                     self.frozen_result))

            self._replay.log("State after the entry: %r",
                             self._replay.agent._get_state())

            return self
        except:
            self._replay.error("Failed trying to apply instance %r entry %r"
                               % (self.journal_id, self.function_id))
            raise

    def to_string(self, header=""):
        args, kwargs = self.get_arguments()
        side_effects = [side_effect_as_string(*self._restore_side_effect(se))
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
                   header, self.frozen_result,
                   header, header + "  ",
                   ("\n  " + header).join(side_effects)))

    ### IJournalReplayEntry Methods ###

    def get_arguments(self):
        return (self._replay.unserializer.convert(self._args) or (),
                self._replay.unserializer.convert(self._kwargs) or {})

    def rewind_side_effects(self):
        self._next_effect = 0

    def next_side_effect(self, function_id, *args, **kwargs):
        unexpected_desc = side_effect_as_string(function_id, args, kwargs)

        if self._next_effect >= len(self._side_effects):
            raise ReplayError("Unexpected side-effect %s"
                              % (unexpected_desc, ))

        side_effect = self._side_effects[self._next_effect]
        self._next_effect += 1

        side_effect = self._restore_side_effect(side_effect)
        exp_fun_id, exp_args, exp_kwargs, effects, result = side_effect

        expected_desc = side_effect_as_string(exp_fun_id, exp_args, exp_kwargs)

        if exp_fun_id != function_id:
            raise ReplayError("Side-effect %s called instead of %s"
                              % (unexpected_desc, expected_desc))

        if exp_args != args:
            raise ReplayError("Bad side-effect arguments in %s "
                              "when expecting of %s"
                              % (unexpected_desc, expected_desc))

        if exp_kwargs != kwargs:
            raise ReplayError("Bad side-effect keyworkds in %s "
                              "when expecting of %s"
                              % (unexpected_desc, expected_desc))

        for effect_id, effect_args, effect_kwargs in effects:
            self._replay.apply_effect(effect_id, *effect_args, **effect_kwargs)

        return self._replay.unserializer.convert(result)

    ### Private Methods ###

    def _restore_side_effect(self, record):
        fun_id, raw_args, raw_kwargs, raw_effects, result = record
        args = self._replay.unserializer.convert(raw_args) or ()
        kwargs = self._replay.unserializer.convert(raw_kwargs) or {}
        effects = [(effect_id,
                    self._replay.unserializer.convert(effect_args),
                    self._replay.unserializer.convert(effect_kwargs))
                   for effect_id, effect_args, effect_kwargs in raw_effects]
        return fun_id, args, kwargs, effects, result


class Replay(log.FluLogKeeper, log.Logger):
    '''
    Class managing the replay of the single agent.
    '''

    implements(IExternalizer, IEffectHandler)

    log_category = 'replay-driver'

    def __init__(self, journal, agent_id):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self.journal = journal
        self.unserializer = pytree.Unserializer(externalizer=self)
        self.serializer = pytree.Serializer(externalizer=self)

        self.agent_id = agent_id
        Factory(self, 'agent-medium', AgencyAgent)
        Factory(self, 'replier-medium', AgencyReplier)
        Factory(self, 'requester-medium', AgencyRequester)
        Factory(self, 'contractor-medium', AgencyContractor)
        Factory(self, 'manager-medium', AgencyManager)
        Factory(self, 'retrying-protocol', RetryingProtocol)

        self.reset()

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

    def register(self, recorder):
        j_id = recorder.journal_id
        self.log('Registering recorder: %r, id: %r, id(recorder): %r',
                 recorder.__class__.__name__, j_id, id(recorder))
        assert j_id not in self.registry
        self.registry[j_id] = recorder

    def set_aa(self, medium):
        assert self.medium is None
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
            return replay.replay(entry, self.apply_snapshot, entry)

        self._log_entry(entry)

        method = getattr(self, "effect_%s" % entry.function_id)
        args, kwargs = entry.get_arguments()
        return replay.replay(entry, method, *args, **kwargs)

    def effect_agent_created(self, agent_factory, dummy_id):
        assert self.medium is None
        self.medium = AgencyAgent(self)
        self.register_dummy(dummy_id, self.medium)
        self.agent = agent_factory(self.medium)

    def effect_agent_deleted(self):
        self.reset()

    def effect_protocol_created(self, factory, medium, *args, **kwargs):
        assert self.agent is not None
        instance = factory(self.agent, medium)
        self.protocols.append(instance)

    def effect_protocol_deleted(self, journal_id, dummy_id):
        instance = self.registry[journal_id]
        self.protocols.remove(instance)
        del(self.registry[journal_id])
        self.unregister_dummy(dummy_id)

    def apply_snapshot(self, entry):
        old_agent, old_protocols = self.agent, self.protocols
        self.reset()
        args, kwargs = entry.get_arguments()
        self.restore_snapshot(*args, **kwargs)
        self.check_snapshot(old_agent, old_protocols)

    def restore_snapshot(self, snapshot):
        self.agent, self.protocols = snapshot

    def check_snapshot(self, old_agent, old_protocols):
        # check that the state so far matches the snapshop
        # if old_agent is None, it means that the snapshot is first entry
        # we are replaynig - hence we have no state to compare to
        if old_agent is not None:
            if self.agent != old_agent:
                raise ReplayError("States of current agent mismatch the "
                                  "old agent\nOld: %r\nLoaded: %r."
                                  % (old_agent._get_state(),
                                     self.agent._get_state()))
            if len(self.protocols) != len(old_protocols):
                raise ReplayError("The number of protocols mismatch. "
                                  "\nOld: %r\nLoaded: %r"
                                  % (old_protocols, self.protocols))
            else:
                for protocol in self.protocols:
                    if protocol not in old_protocols:
                        raise ReplayError("One of the protocols was not found."
                                          "\nOld: %r\nLoaded: %r"
                                          % (old_protocols, self.protocols))

    # Managing the dummy registry:

    def register_dummy(self, dummy_id, dummy):
        if self.lookup_dummy(dummy_id) is not None:
            raise RuntimeError("Tried to register dummy: %r class: %r second"
                               " time", dummy_id, dummy.__class__.__name__)
        self.dummies[dummy_id] = dummy

    def unregister_dummy(self, dummy_id):
        if self.lookup_dummy(dummy_id) is None:
            raise RuntimeError("Treid to unregister dummy_id: %r "
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

    def identify(self, _):
        raise RuntimeError("OOPS, this should not be used in replay")

    def lookup(self, identifier):
        return self.registry.get(identifier, None)


class BaseReplayDummy(object):

    def restored(self):
        pass


class StateMachineSpecific(object):

    @serialization.freeze_tag('StateMachineMixin.wait_for_state')
    def wait_for_state(self, state):
        raise RuntimeError('This should never be called!')


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
        new = self.cls(self.replay)
        self.replay.register_dummy(dummy_id, new)
        return new

    def prepare(self):
        return None


class AgencyAgent(log.LogProxy, log.Logger, BaseReplayDummy):

    type_name = 'agent-medium'

    implements(IAgencyAgent, IRecorderNode, IJournalKeeper, ISerializable)

    def __init__(self, replay):
        log.LogProxy.__init__(self, replay)
        log.Logger.__init__(self, replay)
        self.journal_keeper = self
        self.replay = replay
        self.replay.set_aa(self)

    def restored(self):
        pass

    @replay.named_side_effect('AgencyAgent.get_descriptor')
    def get_descriptor(self):
        pass

    def update_descriptor(self, desc):
        pass

    @replay.named_side_effect('AgencyAgent.get_mode')
    def get_mode(self, component):
        pass

    @replay.named_side_effect('AgencyAgent.get_time')
    def get_time(self):
        pass

    @serialization.freeze_tag('AgencyAgent.join_shard')
    def join_shard(self, shard):
        pass

    @serialization.freeze_tag('AgencyAgent.leave_shard')
    def leave_shard(self, shard):
        pass

    @serialization.freeze_tag('AgencyAgent.start_agent')
    def start_agent(self, desc):
        pass

    @serialization.freeze_tag('AgencyAgent.initiate_protocol')
    @replay.named_side_effect('AgencyAgent.initiate_protocol')
    def initiate_protocol(self, factory, recipients, *args, **kwargs):
        pass

    @serialization.freeze_tag('AgencyAgent.retrying_protocol')
    @replay.named_side_effect('AgencyAgent.retrying_protocol')
    def retrying_protocol(self, factory, recipients, max_retries=None,
                         initial_delay=1, max_delay=None, *args, **kwargs):
        pass

    @replay.named_side_effect('AgencyAgent.revoke_interest')
    def revoke_interest(self, factory):
        pass

    @replay.named_side_effect('AgencyAgent.register_interest')
    def register_interest(self, factory):
        pass

    @serialization.freeze_tag('AgencyAgency.save_document')
    def save_document(self, document):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgency.reload_document')
    def reload_document(self, document):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgency.delete_document')
    def delete_document(self, document):
        raise RuntimeError('This should never be called!')

    @serialization.freeze_tag('AgencyAgency.get_document')
    def get_document(self, document_id):
        raise RuntimeError('This should never be called!')

    # IJournalKeeper

    def register(self, recorder):
        self.replay.register(recorder)

    # IRecorderNone

    def generate_identifier(self, recorder):
        assert not getattr(self, 'indentifier_generated', False)
        self._identifier_generated = True
        return (self.replay.agent_id, )


    # ISerializable

    def snapshot(self):
        return self.replay.agent_id


class AgencyReplier(log.LogProxy, log.Logger,
                    BaseReplayDummy, StateMachineSpecific):

    def __init__(self, replay):
        log.Logger.__init__(self, replay)
        log.LogProxy.__init__(self, replay)

    @serialization.freeze_tag('AgencyReplier.reply')
    @replay.named_side_effect('AgencyReplier.reply')
    def reply(self, reply):
        pass


class AgencyRequester(log.LogProxy, log.Logger,
                      BaseReplayDummy, StateMachineSpecific):

    def __init__(self, replay):
        log.Logger.__init__(self, replay)
        log.LogProxy.__init__(self, replay)

    @replay.named_side_effect('AgencyRequester.request')
    def request(self, request):
        pass


class AgencyContractor(log.LogProxy, log.Logger,
                       BaseReplayDummy, StateMachineSpecific):

    def __init__(self, replay):
        log.Logger.__init__(self, replay)
        log.LogProxy.__init__(self, replay)

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

    @replay.named_side_effect('AgencyContractor.finalize')
    def finalize(self, report):
        pass

    @serialization.freeze_tag('AgencyContractor.update_manager_address')
    @replay.named_side_effect('AgencyContractor.update_manager_address')
    def update_manager_address(self, recp):
        pass


class RetryingProtocol(BaseReplayDummy, log.Logger):

    implements(serialization.ISerializable)

    def __init__(self, replay):
        log.Logger.__init__(self, replay)

    @serialization.freeze_tag('RetryingProtocol.notify_finish')
    def notify_finish(self):
        raise RuntimeError('This should never get called')

    @serialization.freeze_tag('RetryingProtocol.give_up')
    def give_up(self):
        pass


class AgencyManager(log.LogProxy, log.Logger,
                    BaseReplayDummy, StateMachineSpecific):

    def __init__(self, replay):
        log.Logger.__init__(self, replay)
        log.LogProxy.__init__(self, replay)

    @replay.named_side_effect('AgencyManager.announce')
    def announce(self, announce):
        pass

    @replay.named_side_effect('AgencyManager.reject')
    def reject(self, bid, rejection=None):
        pass

    @replay.named_side_effect('AgencyManager.grant')
    def grant(self, grants):
        pass

    @replay.named_side_effect('AgencyManager.cancel')
    def cancel(self, reason=None):
        pass

    @replay.named_side_effect('AgencyManager.terminate')
    def terminate(self):
        pass

    @replay.named_side_effect('AgencyManager.get_bids')
    def get_bids(self):
        pass
