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
import json
import sys
import os

from twisted.trial.unittest import FailTest, SkipTest

from feat.test import common
from feat.common import text_helper, defer, reflect, error, log
from feat.common.serialization import base
from feat.process import couchdb, rabbitmq
from feat.process.base import DependencyError
from feat.simulation import driver
from feat.agencies import replay
from feat.agencies.messaging import tunneling
from feat.database import driver as database, tools

from feat.agents.application import feat
from feat import applications
from feat.gateway.resources import Context
from feat.web import document, http

from feat.test.test_models_applicationjson import DummyContext

from feat.database.interface import NotFoundError
from feat.models.interface import IModel, ActionCategories, Unauthorized
from feat.models.interface import IQueryModel, NotSupported, IAttribute

attr = common.attr
delay = common.delay
delay_errback = common.delay_errback
delay_callback = common.delay_callback
break_chain = common.break_chain
break_callback_chain = common.break_callback_chain
break_errback_chain = common.break_errback_chain


class IntegrationTest(common.TestCase):
    skip_coverage = True

    def setUp(self):
        self.assert_not_skipped()
        feat.load_adapters()
        self.addCleanup(feat.unload_adapters)

        return common.TestCase.setUp(self)

    def assert_not_skipped(self):
        if self.skip_coverage and sys.gettrace():
            raise SkipTest("Test Skipped during coverage")


class FullIntegrationTest(IntegrationTest):

    configurable_attributes = ['run_rabbit', 'run_couch', 'shutdown']
    start_couch = True
    start_rabbit = True
    run_rabbit = True
    run_couch = True

    def start_couch_process(self):
        try:
            self.db_process = couchdb.Process(self)
        except DependencyError:
            raise SkipTest("No CouchDB server found.")

    def start_rabbit_process(self):
        try:
            self.msg_process = rabbitmq.Process(self)
        except DependencyError:
            raise SkipTest("No RabbitMQ server found.")

    @defer.inlineCallbacks
    def run_and_configure_db(self):
        yield self.db_process.restart()
        c = self.db_process.get_config()
        db_host, db_port, db_name = c['host'], c['port'], 'test'
        db = database.Database(db_host, db_port, db_name)
        self.addCleanup(db.disconnect)
        self.db = db.get_connection()
        yield tools.create_db(self.db)

        yield tools.push_initial_data(self.db)
        defer.returnValue((db_host, db_port, db_name, ))

    @defer.inlineCallbacks
    def run_and_configure_msg(self):
        yield self.msg_process.restart()
        c = self.msg_process.get_config()
        msg_host, msg_port = '127.0.0.1', c['port']
        defer.returnValue((msg_host, msg_port, ))

    @defer.inlineCallbacks
    def setUp(self):
        yield IntegrationTest.setUp(self)

        tee = log.get_default()
        tee.add_keeper('buffer', log.LogBuffer(limit=10000))

        self.tempdir = os.path.abspath(os.path.curdir)
        self.socket_path = os.path.abspath(
            os.path.join(os.path.curdir, 'feat-test.socket'))

        bin_dir = os.path.abspath(os.path.join(
            os.path.curdir, '..', '..', 'bin'))
        os.environ["PATH"] = ":".join([bin_dir, os.environ["PATH"]])

        if self.start_rabbit:
            self.start_rabbit_process()

        if self.start_couch:
            self.start_couch_process()

        if self.run_couch:
            self.db_host, self.db_port, self.db_name =\
                          yield self.run_and_configure_db()
        else:
            self.db_host, self.db_name = '127.0.0.1', 'test'
            self.db_port = self.db_process.get_free_port()

        if self.run_rabbit:
            self.msg_host, self.msg_port = yield self.run_and_configure_msg()
        else:
            self.msg_host = '127.0.0.1'
            self.msg_port = self.msg_process.get_free_port()

        self.jourfile = "%s.sqlite3" % (self._testMethodName, )
        self.pid_path = os.path.abspath(
            os.path.join(os.path.curdir, 'feat.pid'))

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.db_process.terminate()
        yield self.msg_process.terminate()
        yield IntegrationTest.tearDown(self)

    def wait_for_host_agent(self, timeout):

        def check():
            medium = self.agency._get_host_medium()
            return medium is not None

        return self.wait_for(check, timeout)

    def wait_for_standalone(self, timeout=20):

        host_a = self.agency.get_host_agent()
        self.assertIsNot(host_a, None)

        def has_partner():
            part = host_a.query_partners_with_role('all', 'standalone')
            return len(part) == 1

        return self.wait_for(has_partner, timeout)

    def wait_for_pid(self, pid_path):

        def pid_created():
            return os.path.exists(pid_path)

        return self.wait_for(pid_created, timeout=20)

    def wait_for_slave(self, timeout=20):

        def is_slave():
            return self.agency._broker.is_slave()

        return  self.wait_for(is_slave, timeout)

    def wait_for_master(self, timeout=20):

        def became_master():
            return self.agency._broker.is_master()

        return self.wait_for(became_master, timeout)

    def wait_for_backup(self, timeout=20):
        return self.wait_for(self.agency._broker.has_slave, timeout)


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

    def override_agent(self, agent_type, factory, application=feat):
        r = applications.get_agent_registry()
        if not hasattr(self, 'snapshot_agents'):
            self.snapshot_agents = r.get_snapshot()
            self.snapshot_restorators = base.get_registry().get_snapshot()

        application.register_agent(agent_type)(factory)

    def revert_overrides_agents(self):
        if not hasattr(self, 'snapshot_agents'):
            return
        else:
            r = applications.get_agent_registry()
            r.reset(self.snapshot_agents)
            base.get_registry().reset(self.snapshot_restorators)
            del(self.snapshot_agents)
            del(self.snapshot_restorators)

    def override_config(self, agent_type, config):
        if not hasattr(self, 'overriden_configs'):
            self.overriden_configs = dict()
        factory = applications.lookup_agent(agent_type)
        self.overriden_configs[agent_type] = factory.configuration_doc_id
        factory.configuration_doc_id = config.doc_id

    def revert_overrides_config(self):
        if not hasattr(self, 'overriden_configs'):
            return
        for key, value in self.overriden_configs.iteritems():
            factory = applications.lookup_agent(key)
            factory.configuration_doc_id = value

    def tearDown(self):
        self.revert_overrides_agents()
        self.revert_overrides_config()


class SimulationTest(common.TestCase, OverrideConfigMixin):

    configurable_attributes = ['skip_replayability', 'jourfile', 'save_stats']
    skip_replayability = False
    skip_coverage = True
    jourfile = None
    save_stats = False

    def __init__(self, *args, **kwargs):
        common.TestCase.__init__(self, *args, **kwargs)
        initial_documents = tools.get_current_initials()
        self.addCleanup(tools.reset_documents, initial_documents)

    def assert_not_skipped(self):
        if self.skip_coverage and sys.gettrace():
            raise SkipTest("Test Skipped during coverage")

    @defer.inlineCallbacks
    def setUp(self):
        self.assert_not_skipped()
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
        if not self.skip_replayability:
            self.info("Test finished, now validating replayability.")
            yield self.wait_for(self.driver._journaler.is_idle, 10, 0.01)
            self.driver.snapshot_all_agents()

            histories = yield self.driver._jourwriter.get_histories()
            for history in histories:
                entries = yield self.driver._jourwriter.get_entries(history)
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
    skip_coverage = True

    def __init__(self, *args, **kwargs):
        common.TestCase.__init__(self, *args, **kwargs)
        initial_documents = tools.get_current_initials()

        self.addCleanup(tools.reset_documents, initial_documents)

    def assert_not_skipped(self):
        if self.skip_coverage and sys.gettrace():
            raise SkipTest("Test Skipped during coverage")

    @defer.inlineCallbacks
    def setUp(self):
        self.assert_not_skipped()
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


class ModelTestMixin(object):
    '''
    Mix me in to be able to valide the visualisation part of the models.
    The base class should provide ILogger and ITestCase.
    '''

    validated_mime_types = ['text/html', 'application/json']

    def validate_model_tree(self, model):
        visited = list()
        model = IModel(model)
        context = Context(http.Schemes.HTTPS,
                          [model], [(model.name, 5500)], [])

        self.info("Starting validating model tree. The root object: %r",
                  model)
        return self._model_tree_iteration(model, visited, context)

    @defer.inlineCallbacks
    def model_descend(self, model, *path):
        i = model
        for part in path:
            i = yield i.fetch_item(part)
            if i is None:
                return
            i = yield i.fetch()
        defer.returnValue(i)

    @defer.inlineCallbacks
    def _model_tree_iteration(self, model, visited, context):
        model = IModel(model)
        if model in visited:
            self.log('Skiping already validated model: %r', model)
            return
        visited.append(model)
        yield self._validate_model(model, context)

        if IQueryModel.providedBy(model):
            querymodel = yield model.query_items(offset=0, limit=10)
            items = yield querymodel.fetch_items()
        else:
            try:
                items = yield model.fetch_items()
            except NotSupported:
                self.info('Not iteration further down the model %r because '
                          'it doesnt support fetching items', model)
                return
        for item in items:
            try:
                submodel = yield item.fetch()
            except Unauthorized:
                continue
            if IModel.providedBy(submodel):
                subcontext = context.descend(submodel)
                yield self._model_tree_iteration(submodel, visited, subcontext)

    @defer.inlineCallbacks
    def _validate_model(self, model, context):
        self.info("Validating model %r", model)

        # check writing it to supported mime types
        for mime_type in self.validated_mime_types:
            doc = document.WritableDocument(mime_type)
            d = document.write(doc, model, context=context)
            d.addErrback(self._writing_errback, mime_type, model)
            yield d
            self.info('Result of rendering for mimetype: %s\n%s',
                      mime_type, doc.get_data())

        # call querying actions
        actions = yield model.fetch_actions()
        for action in actions:
            if action.category != ActionCategories.retrieve:
                self.info("Not validating action name: %s, label: %s, "
                          "as it's category is: %s", action.name,
                          action.label, action.category)
                continue
            enabled = yield action.fetch_enabled()
            if not enabled:
                self.info("Not validating disabled action name: %s, "
                          "label: %s,", action.name, action.label)
                continue
            if action.parameters:
                self.info("Not validating action name: %s, because it requires"
                          " passing parameters: %r", action.name,
                          [x.name for x in action.parameters])
                continue

            d = action.perform()
            d.addErrback(self._action_errback, action, model)

            result = yield d
            self.info("Successfully performed action %s with result %r",
                      action.name, result)

    def _writing_errback(self, fail, mime_type, model):
        if fail.check(NotSupported):
            self.info("Model %r doesn't support fetching items", model)
            return
        if IAttribute.providedBy(model) and fail.check(ValueError):
            return
        error.handle_failure(
            self, fail,
            "Failed writing the model for the mime type: %r, \n"
            "model: %r\nsource: %r", mime_type, model, model.source)
        self.fail("Failed writing model, look at logs.")

    def _action_errback(self, fail, action, model):
        if IAttribute.providedBy(model) and fail.check(ValueError):
            return
        error.handle_failure(self, fail,
            "Failed running action name: %s on model: %r",
            action.name, model)
        self.fail("Calling action %s on model %s failed, look at logs." %
                  (action.name, model.identity, ))

    def modelattr(self, model, attr):
        d = model.fetch_item(attr)
        d.addCallback(defer.call_param, 'fetch')
        d.addCallback(defer.call_param, 'perform_action', 'get')
        return d

    @defer.inlineCallbacks
    def model_as_json(self, model):
        doc = document.WritableDocument("application/json",
                                        encoding='utf-8')
        ctx = DummyContext(("ROOT", ), ("root", ))
        yield document.write(doc, model, context=ctx, format="compact")
        defer.returnValue(json.loads(doc.get_data()))
