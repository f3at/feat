# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import operator
import sys
from pprint import pformat

from twisted.trial.unittest import FailTest

from feat.test import common
from feat.common import text_helper, defer, reflect
from feat.common.serialization import pytree
from feat.simulation import driver
from feat.agencies import replay
from feat.agents.base import dbtools
from feat.agents.base.agent import registry_lookup

from feat.agencies.interface import NotFoundError

attr = common.attr
delay = common.delay
delay_errback = common.delay_errback
delay_callback = common.delay_callback
break_chain = common.break_chain
break_callback_chain = common.break_callback_chain
break_errback_chain = common.break_errback_chain


class IntegrationTest(common.TestCase):
    pass


def jid2str(jid):
    if isinstance(jid, basestring):
        return str(jid)
    return "-".join([str(i) for i in jid])


def format_journal(journal, prefix=""):

    def format_call(funid, args, kwargs):
        params = []
        if args:
            params += [repr(a) for a in args]
        if kwargs:
            params += ["%r=%r" % i for i in kwargs.items()]
        return [funid, "(", ", ".join(params), ")"]

    parts = []
    for _, jid, funid, fid, fdepth, args, kwargs, se, result in journal:
        parts += [prefix, jid2str(jid), ": \n"]
        parts += [prefix, " "*4]
        parts += format_call(funid, args, kwargs)
        parts += [":\n"]
        parts += [prefix, " "*8, "FIBER ", str(fid),
                  " DEPTH ", str(fdepth), "\n"]
        if se:
            parts += [prefix, " "*8, "SIDE EFFECTS:\n"]
            for se_funid, se_args, se_kwargs, se_effects, se_result in se:
                parts += [prefix, " "*12]
                parts += format_call(se_funid, se_args, se_kwargs)
                parts += [":\n"]
                if se_effects:
                    parts += [prefix, " "*16, "EFFECTS:\n"]
                    for eid, args, kwargs in se_effects:
                        parts += [prefix, " "*20]
                        parts += format_call(eid, args, kwargs) + ["\n"]
                parts += [prefix, " "*16, "RETURN: ", repr(se_result), "\n"]
        parts += [prefix, " "*8, "RETURN: ", repr(result), "\n\n"]
    return "".join(parts)


class SimulationTest(common.TestCase):

    configurable_attributes = ['skip_replayability', 'jourfile', 'save_stats']
    skip_replayability = False
    jourfile = None
    save_stats = False

    def __init__(self, *args, **kwargs):
        common.TestCase.__init__(self, *args, **kwargs)
        initial_documents = dbtools.get_current_initials()
        self.addCleanup(dbtools.reset_documents, initial_documents)
        self.overriden_configs = None

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        self.driver = driver.Driver(jourfile=self.jourfile)
        yield self.driver.initiate()
        yield self.prolog()

    def prolog(self):
        pass

    def process(self, script):
        d = self.cb_after(None, self.driver._parser, 'on_finish')
        self.driver.process(script)
        return d

    def get_local(self, *names):
        results = map(lambda name: self.driver._parser.get_local(name), names)
        if len(results) == 1:
            return results[0]
        else:
            return tuple(results)

    def set_local(self, name, value):
        self.driver._parser.set_local(value, name)

    @defer.inlineCallbacks
    def tearDown(self):
        # First get the current exception before anything else
        exc_type, _, _ = sys.exc_info()

        for x in self.driver.iter_agents():
            yield x._cancel_long_running_protocols()
            yield x.wait_for_protocols_finish()

        yield common.TestCase.tearDown(self)

        if self.save_stats:
            f = file(self.save_stats, "a")
            print >> f, ""
            print >> f, "%s.%s:" % (reflect.canonical_name(self),
                                    self._testMethodName, )
            t = text_helper.Table(fields=('name', 'value'),
                                  lengths=(40, 40))
            print >> f, t.render(self.driver.get_stats().iteritems())
            f.close()

        try:
            if exc_type is None or exc_type is StopIteration:
                yield self._check_replayability()
        finally:
            # remove leaking memory during the tests
            yield self.driver.destroy()
            for k, v in self.__dict__.items():
                if str(k)[0] == "_":
                    continue
                delattr(self, k)

    @defer.inlineCallbacks
    def _check_replayability(self):
        if not self.skip_replayability:
            self.info("Test finished, now validating replayability.")
            yield self.wait_for(self.driver._journaler.is_idle, 10, 0.01)

            histories = yield self.driver._journaler.get_histories()
            for history in histories:
                entries = yield self.driver._journaler.get_entries(history)
                yield self._validate_replay_on_agent(history, entries)
        else:
            msg = ("\n\033[91mFIXME: \033[0mReplayability test "
                  "skipped: %s\n" % self.skip_replayability)
            print msg

    @defer.inlineCallbacks
    def _validate_replay_on_agent(self, history, entries):
        aid = history.agent_id
        agent = yield self.driver.find_agent(aid)
        if agent is None:
            self.warning(
                'Agent with id %r not found. '
                'This usually means it was terminated, during the test.', aid)
            return
        if agent._instance_id != history.instance_id:
            self.warning(
                'Agent instance id is %s, the journal entries are for '
                'instance_id %s. This history will not get validated, as '
                'now we dont have the real instance to compare the result '
                'with.', agent._instance_id, history.instance_id)
            return

        self.log("Validating replay of %r with id: %s",
                 agent.agent.__class__.__name__, aid)

        self.log("Found %d entries of this agent.", len(entries))
        r = replay.Replay(iter(entries), aid)
        for entry in r:
            entry.apply()

        agent_snapshot, protocols = agent.snapshot_agent()
        self.log("Replay complete. Comparing state of the agent and his "
                 "%d protocols.", len(protocols))
        if agent_snapshot._get_state() != r.agent._get_state():
            s1 = r.agent._get_state()
            s2 = agent_snapshot._get_state()
            comp = self.deep_compare(s1, s2)
            info = "  INFO:        %s: %s\n" % comp if comp else ""
            res = repr(pytree.serialize(agent_snapshot._get_state()))
            exp = repr(pytree.serialize(r.agent._get_state()))
            diffs = text_helper.format_diff(exp, res, "\n               ")
            self.fail("Agent snapshot different after replay:\n%s"
                      "  SNAPSHOT:    %s\n"
                      "  EXPECTED:    %s\n"
                      "  DIFFERENCES: %s\n"
                      % (info, res, exp, diffs))

        self.assertEqual(agent_snapshot._get_state(), r.agent._get_state())

        self.assertEqual(len(r.protocols), len(protocols),
                         "Protocols of agent: %s from replay doesn't much "
                         "the test result. \nReplay: %s,\nResult: %s" %
                         (aid,
                          pformat(r.protocols),
                          pformat(protocols)))

        def sort(recorders):
            # at some point the protocols are stored as the dictionary values,
            # for this reason they come in snapshot in random order and need
            # to be sorted before comparing
            return sorted(recorders, key=operator.attrgetter('journal_id'))

        for from_snapshot, from_replay in zip(sort(protocols),
                                              sort(r.protocols)):
            self.assertEqual(from_snapshot._get_state(),
                             from_replay._get_state(),
                             "Failed comparing state of protocols. \nA=%s "
                             "\B=%s." % (pformat(from_snapshot),
                                         pformat(from_replay)))

    def deep_compare(self, expected, value):

        def compare_value(v1, v2, path):
            if v1 == v2:
                return

            if isinstance(v1, (list, tuple)):
                return compare_iter(v1, v2, path)
            if isinstance(v1, dict):
                return compare_dict(v1, v2, path)
            return compare_object(v1, v2, path)

        def compare_iter(v1, v2, path):
            if not isinstance(v2, (list, tuple)):
                msg = ("expected list or tuple and got %s"
                       % (type(v2).__name__, ))
                return path, msg

            if len(v1) != len(v2):
                msg = "Expected %d item(s) and got %d" % (len(v1), len(v2))
                return path, msg

            i = 0
            a = iter(v1)
            b = iter(v2)
            try:
                while True:
                    new_path = path + "[%s]" % i
                    i += 1
                    v1 = a.next()
                    v2 = b.next()
                    result = compare_value(v1, v2, new_path)
                    if result:
                        return result
            except StopIteration:
                return path, "Lists or tuples do not compare equal"

        def compare_dict(v1, v2, path):
            if not isinstance(v2, dict):
                msg = ("expected dict and got %s"
                       % (type(v2).__name__, ))
                return path, msg

            if len(v1) != len(v2):
                msg = "Expected %d item(s) and got %d" % (len(v1), len(v2))
                return path, msg

            for k in v1:
                new_path = path + "[%r]" % (k, )
                a = v1[k]
                if k not in v2:
                    return new_path, "key not found"
                b = v2[k]
                result = compare_value(a, b, new_path)
                if result:
                    return result

            return path, "Dictionaries do not compare equal"

        def compare_object(v1, v2, path):
            basic_types = (int, float, long, bool, str, unicode)
            if isinstance(v1, basic_types) or isinstance(v2, basic_types):
                if not isinstance(v2, type(v1)):
                    msg = ("expected %s and got %s"
                           % (type(v1).__name__, type(v2).__name__))
                    return path, msg

            d1 = v1.__dict__
            d2 = v2.__dict__

            if len(d1) != len(d2):
                msg = ("Expected %d attribute(s) and got %d"
                       % (len(v1), len(v2)))
                return path, msg

            for k in d1:
                # Simplistic black list
                if k in ["medium", "agent"]:
                    continue
                new_path = path + ("." if path else "") + "%s" % (k, )
                a = d1[k]
                if k not in d2:
                    return new_path, "attribute not found"
                b = d2[k]
                result = compare_value(a, b, new_path)
                if result:
                    return result

            return path, ("Instances %s and %s do not compare equal"
                          % (type(v1).__name__, type(v2).__name__))

        return compare_value(expected, value, "")

    @defer.inlineCallbacks
    def wait_for_idle(self, timeout, freq=0.05):
        try:
            yield self.wait_for(self.driver.is_idle, timeout, freq)
        except FailTest:
            for agent in self.driver.iter_agents():
                activity = agent.show_activity()
                if activity is None:
                    continue
                self.info(activity)
            raise

    def count_agents(self, agent_type=None):
        return len([x for x in self.driver.iter_agents(agent_type)])

    def override_config(self, agent_type, config):
        if self.overriden_configs is None:
            self.overriden_configs = dict()
            self.addCleanup(self.revert_overrides)
        factory = registry_lookup(agent_type)
        self.overriden_configs[agent_type] = factory.configuration_doc_id
        factory.configuration_doc_id = config.doc_id

    def revert_overrides(self):
        if self.overriden_configs is None:
            return
        for key, value in self.overriden_configs.iteritems():
            factory = registry_lookup(key)
            factory.configuration_doc_id = value

    def assert_document_not_found(self, doc_id):
        d = self.driver.get_document(doc_id)
        self.assertFailure(d, NotFoundError)
        return d
