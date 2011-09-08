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
import sys

from twisted.trial.unittest import FailTest

from feat.test import common
from feat.common import text_helper, defer, reflect
from feat.simulation import driver
from feat.agencies import replay
from feat.agencies.emu import tunneling
from feat.agents.base import dbtools, registry

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


class OverrideConfigMixin(object):

    def override_agent(self, agent_type, factory):
        if not hasattr(self, 'overriden_agents'):
            self.overriden_agents = dict()

        old = registry.registry_lookup(agent_type)
        self.overriden_agents[agent_type] = old
        registry.override(agent_type, factory)

    def revert_overrides_agents(self):
        if not hasattr(self, 'overriden_agents'):
            return
        else:
            for agent_type, factory in self.overriden_agents.iteritems():
                if factory:
                    registry.override(agent_type, factory)

    def override_config(self, agent_type, config):
        if not hasattr(self, 'overriden_configs'):
            self.overriden_configs = dict()
        factory = registry.registry_lookup(agent_type)
        self.overriden_configs[agent_type] = factory.configuration_doc_id
        factory.configuration_doc_id = config.doc_id

    def revert_overrides_config(self):
        if not hasattr(self, 'overriden_configs'):
            return
        for key, value in self.overriden_configs.iteritems():
            factory = registry.registry_lookup(key)
            factory.configuration_doc_id = value

    def tearDown(self):
        self.revert_overrides_agents()
        self.revert_overrides_config()


class SimulationTest(common.TestCase, OverrideConfigMixin):

    configurable_attributes = ['skip_replayability', 'jourfile', 'save_stats']
    skip_replayability = False
    jourfile = None
    save_stats = False

    def __init__(self, *args, **kwargs):
        common.TestCase.__init__(self, *args, **kwargs)
        initial_documents = dbtools.get_current_initials()
        self.addCleanup(dbtools.reset_documents, initial_documents)

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
        results = map(lambda name: self.driver.get_local(name), names)
        if len(results) == 1:
            return results[0]
        else:
            return tuple(results)

    def set_local(self, name, value):
        self.driver.set_local(name, value)

    @defer.inlineCallbacks
    def tearDown(self):
        # First get the current exception before anything else
        exc_type, _, _ = sys.exc_info()

        yield self.driver.freeze_all()

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
            OverrideConfigMixin.tearDown(self)
            # remove leaking memory during the tests
            yield self.driver.destroy()
            for k, v in self.__dict__.items():
                if str(k)[0] == "_":
                    continue
                delattr(self, k)
            yield common.TestCase.tearDown(self)

    @defer.inlineCallbacks
    def _check_replayability(self):
        self.driver.snapshot_all_agents()
        if not self.skip_replayability:
            self.info("Test finished, now validating replayability.")
            yield self.wait_for(self.driver._journaler.is_idle, 10, 0.01)

            histories = yield self.driver._journaler.get_histories()
            for history in histories:
                entries = yield self.driver._journaler.get_entries(history)
                self._validate_replay_on_agent(history, entries)
        else:
            msg = ("\n\033[91mFIXME: \033[0mReplayability test "
                  "skipped: %s\n" % self.skip_replayability)
            print msg

    def _validate_replay_on_agent(self, history, entries):
        aid = history.agent_id
        self.log("Found %d entries of this agent.", len(entries))
        r = replay.Replay(iter(entries), aid)
        for entry in r:
            entry.apply()

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
        return self.driver.count_agents(agent_type)

    def assert_document_not_found(self, doc_id):
        d = self.driver.get_document(doc_id)
        self.assertFailure(d, NotFoundError)
        return d


class MultiClusterSimulation(common.TestCase, OverrideConfigMixin):

    configurable_attributes = ['save_journal', 'clusters']
    save_journal = False
    clusters = 2

    def __init__(self, *args, **kwargs):
        common.TestCase.__init__(self, *args, **kwargs)
        initial_documents = dbtools.get_current_initials()

        self.addCleanup(dbtools.reset_documents, initial_documents)

    @defer.inlineCallbacks
    def setUp(self):
        yield common.TestCase.setUp(self)
        bridge = tunneling.Bridge()
        jourfiles = ["%s_%d.sqlite3" % (self._testMethodName, index, )
                     if self.save_journal else None
                     for index in range(self.clusters)]
        self.drivers = [driver.Driver(tunneling_bridge=bridge,
                                      jourfile=jourfile)
                        for jourfile in jourfiles]
        yield defer.DeferredList([x.initiate() for x in self.drivers])
        yield self.prolog()

    @defer.inlineCallbacks
    def tearDown(self):

        def freeze_and_destroy(driver):
            d = driver.freeze_all()
            d.addCallback(defer.drop_param, driver.destroy)
            return d

        yield defer.DeferredList([freeze_and_destroy(x)
                                  for x in self.drivers])

        OverrideConfigMixin.tearDown(self)
        for k, v in self.__dict__.items():
            if str(k)[0] == "_":
                continue
            delattr(self, k)
        yield common.TestCase.tearDown(self)

    @defer.inlineCallbacks
    def wait_for_idle(self, timeout, freq=0.05):

        def all_idle():
            return all([x.is_idle() for x in self.drivers])

        try:
            yield self.wait_for(all_idle, timeout, freq)
        except FailTest:
            for driver, index in zip(self.drivers, range(len(self.drivers))):
                self.info("Inspecting driver #%d", index)
                for agent in driver.iter_agents():
                    activity = agent.show_activity()
                    if activity is None:
                        continue
                    self.info(activity)
            raise

    def process(self, driver, script):
        d = self.cb_after(None, driver._parser, 'on_finish')
        driver.process(script)
        return d
