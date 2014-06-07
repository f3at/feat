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
import pprint
import random
import StringIO
import tempfile
import os
import subprocess

from zope.interface import implements

from feat.agencies import journaler
from feat.agencies.net import agency as net_agency, broker
from feat.agents.base import resource

from feat.common import defer, reflect, error, first
from feat.models import model, value, reference, response
from feat.models import effect, call, getter, action
from feat.gateway.application import featmodels
from feat.web import http
from feat import applications

from feat.agencies.interface import AgencyRoles, IAgencyProtocolInternal
from feat.agents.monitor.interface import MonitorState, LocationState
from feat.agents.monitor.interface import PatientState
from feat.interface.agent import AgencyAgentState, IAgent, IMonitorAgent
from feat.interface.agent import IAlertAgent
from feat.interface.alert import Severity
from feat.models.interface import IModel, IReference, ActionCategories
from feat.models.interface import Unauthorized, NotAvailable


@featmodels.register_adapter(net_agency.Agency, IModel)
@featmodels.register_model
class Root(model.Model):
    """
    Root model over an agency reference.
    For slave agencies, fetching children 'agencies' or 'agents'
    will return a reference the the master agency corresponding
    model while browsing is still allowed to be able to get to
    the slave agency owned models.
    """
    model.identity("feet.root")
    model.reference(call.model_call("_get_reference"))

    model.child("agencies", model="feat.agencies",
                fetch=getter.model_get("_locate_master"),
                label="Agencies", desc="Agencies running on this host.")
    model.child("agents", model="feat.agents",
                fetch=getter.model_get("_locate_master"),
                label="Agents", desc="Agents running on this host.")
    model.child('apps', model='feat.apps',
                label='Api', desc='Api exposed by services')
    model.child('applications', model='feat.applications',
                label='Applications', desc='Loaded applications',
                view=call.model_call('get_applications'))
    model.child('debug', model='feat.debug',
                label='Debug', desc='Debugging the live application')

    model.meta("html-order", "agencies, agents")
    model.item_meta("agencies", "html-render", "array, 1")
    model.item_meta("agents", "html-render", "array, 1")

    ### custom ###

    def get_applications(self):
        return list(applications.get_application_registry().itervalues())

    def _get_reference(self):
        d = self.source.locate_master()
        return d.addCallback(self._master_located, None)

    def _locate_master(self, name):
        d = self.source.locate_master()
        return d.addCallback(self._master_located, self.source, name)

    def _master_located(self, result, default, *location):
        if result is None:
            return None
        host, port, _agency_id, is_remote = result
        if not is_remote:
            return default
        return reference.Absolute((host, port), *location)


_app_names = dict()


def register_app(name, model):
    global _app_names
    _app_names[name] = model


@featmodels.register_model
class Debug(model.Model):

    model.identity('feat.debug')
    model.child('objgraph', model='feat.debug.objgraph')


@featmodels.register_model
class ObjGraph(model.Model):
    model.identity('feat.debug.objgraph')
    model.attribute('most_common_types', value.Binary('text/plain'),
                    getter=call.model_call('get_most_common_types'))
    model.action('show_back_refs', action.MetaAction.new(
        u'show_back_refs',
        category=ActionCategories.retrieve,
        result_info=value.Binary('image/png'),
        is_idempotent=True,
        params=[
            action.Param('obj_type', value.String()),
            action.Param('max_depth', value.Integer(5), is_required=False)],
        effects=[
            call.model_perform('generate_backref_graph')]))

    def init(self):
        try:
            import objgraph
            self.objgraph = objgraph
        except ImportError:
            raise NotAvailable('Failed import objgraph library')

    def get_most_common_types(self):
        output = StringIO.StringIO()
        stats = self.objgraph.most_common_types(limit=20, objects=None)
        width = max(len(name) for name, count in stats)
        for name, count in stats:
            print >> output, ('%-*s %i' % (width, name, count))
        return output.getvalue()

    def generate_backref_graph(self, obj_type, max_depth):
        try:
            dot_name = tempfile.mktemp('.dot')
            output = None
            obj = random.choice(self.objgraph.by_type(obj_type))
            self.objgraph.show_backrefs([obj],
                                        max_depth=max_depth,
                                        filename=dot_name)
            fd, output = tempfile.mkstemp('.png')
            f = os.fdopen(fd, "wb")
            dot = subprocess.Popen(['dot', '-Tpng', dot_name],
                                   stdout=f, close_fds=False)
            dot.wait()
            f.close()
            with open(output, 'r') as f:
                return f.read()
        except IndexError:
            raise http.NotFoundError(obj_type)
        finally:
            for cleanup in (dot_name, output):
                try:
                    if cleanup:
                        os.unlink(cleanup)
                except OSError:
                    pass


@featmodels.register_model
class Apps(model.Collection):
    model.identity('feat.apps')
    model.child_names(call.model_call('get_names'))
    model.child_model(getter.model_get('get_model'))
    model.child_source(getter.model_attr('source'))

    def get_names(self):
        global _app_names
        return _app_names.keys()

    def get_model(self, name):
        global _app_names
        return _app_names.get(name)


@featmodels.register_model
class Applications(model.Collection):
    model.identity('feat.applications')
    model.child_names(call.model_call('get_names'))
    model.child_model('feat.applications.<name>')
    model.child_source(getter.model_get('get_app'))
    model.child_view(effect.context_value('source'))

    def get_names(self):
        return [x.name for x in self.view]

    def get_app(self, name):
        return applications.get_application_registry().lookup(name)


class ReloadApplication(action.Action):
    action.label('Reload the application')
    action.category(ActionCategories.command)
    action.result(value.Response())

    action.effect(call.action_call('terminate_agents'))
    action.effect(call.action_perform('do_reload'))
    action.effect(call.action_perform('restart_agents'))
    action.effect(response.done("Done"))

    @defer.inlineCallbacks
    def terminate_agents(self):
        self._agency = self.model.view
        self._agency._starting_host = True
        application = self.model.source

        agent_ids = []
        for medium in list(self._agency.iter_agents()):
            if medium.agent.application != application:
                self._agency.info(
                    "Leaving in peace the agent %s, he belongs to application"
                    " %s", medium.get_agent_type(),
                    medium.agent.application.name)
                continue
            a_id = medium.get_agent_id()
            agent_ids.append(a_id)
            self._agency.info("Terminating %s with id: %s",
                              medium.get_agent_type(), a_id)
            try:
                yield medium.terminate_hard()
            except Exception as e:
                error.handle_exception('restart', e, "Error termination.")
        defer.returnValue(agent_ids)

    def do_reload(self, value):
        applications.unload(self.model.source.name)
        applications.load(self.model.source.module, self.model.source.name)
        return value

    @defer.inlineCallbacks
    def restart_agents(self, value):
        db = self._agency._database.get_connection()
        for agent_id in value:
            d = db.get_document(agent_id)
            d.addCallback(self._agency.start_agent_locally)
            yield d
        self._agency._starting_host = False


@featmodels.register_model
class Application(model.Model):
    model.identity('feat.applications.<name>')

    model.attribute('name', value.String(), getter.source_attr('name'),
                    label="Name")
    model.attribute('version', value.String(), getter.source_attr('version'),
                    label="Version")
    model.attribute('module', value.String(), getter.source_attr('module'),
                    label="Module", desc="Module the application is defined")

    model.action('reload', ReloadApplication)


@featmodels.register_model
class Agencies(model.Collection):
    """
    Could only be fetched from the master agency.
    List all agencies and gives redirections to slave agencies.
    """
    model.identity("feat.agencies")

    model.child_model(call.model_filter("_get_agency_model"))
    model.child_names(call.source_call("iter_agency_ids"))
    model.child_source(getter.model_get("_locate_agency"))

    #FIXME: use another mean to specify the default action than name
    model.delete("del",
                 effect.delay(call.source_call("full_kill",
                                               stop_process=True)),
                 response.deleted("Full Terminate Succeed"),
                 label="Terminate",
                 desc=("Terminate all agencies on this host, "
                       "without stopping any agents"))

    model.delete("shutdown",
                 effect.delay(call.source_call("full_shutdown",
                                               stop_process=True)),
                 response.deleted("Full Shutdown Succeed"),
                 label="Shutdown",
                 desc=("Shutdown all agencies on this host, "
                       "stopping all agents properly"))

    model.meta("html-render", "array, 1")

    def init(self):
        if not self.officer.peer_info.has_role("admin"):
            raise Unauthorized("You are not administrator")

    ### custom ###

    def _locate_agency(self, name):
        if name == self.source.agency_id:
            return self.source
        if name == u"master":
            d = self.source.locate_master()
            return d.addCallback(self._master_located)
        return self.source._broker.slaves.get(name)

    def _get_agency_model(self, agency):
        if isinstance(agency, net_agency.Agency):
            return "feat.agency"
        return "feat.remote_agency"

    def _master_located(self, result):
        if result is None:
            return None
        host, port, agency_id, _is_remote = result
        return reference.Absolute((host, port), "agencies", agency_id)


@featmodels.register_model
class RemoteAgency(model.Model):

    model.identity("feat.remote_agency")

    model.reference(getter.model_attr("_reference"))

    model.attribute("id", value.String(),
                    getter.source_attr("slave_id"),
                    label="Identifier", desc="Agency unique identifier")
    model.attribute("role", value.Enum(AgencyRoles),
                    getter.model_attr("_role"),
                    label="Agency Role", desc="Current role of the agency")

    model.meta("html-order", "id, role")
    model.item_meta("id", "html-link", "owner")

    ### custom ###

    @defer.inlineCallbacks
    def init(self):
        if self.source.is_standalone:
            self._role = AgencyRoles.standalone
        else:
            self._role = AgencyRoles.slave
        agency_ref = yield self.source.broker.callRemote("get_agency")
        gateway_host = yield agency_ref.callRemote("get_hostname")
        gateway_port = yield agency_ref.callRemote("get_gateway_port")
        root = (gateway_host, gateway_port)
        self._reference = reference.Absolute(root, "agencies", self.name)


@featmodels.register_model
class Agency(model.Model):
    model.identity("feat.agency")

    model.attribute("id", value.String(),
                    getter.source_attr("agency_id"),
                    label="Identifier", desc="Agency unique identifier")
    model.attribute("role", value.Enum(AgencyRoles),
                    getter.source_attr("role"),
                    label="Agency Role", desc="Current role of the agency")
    model.attribute("log_filter", value.String(),
                    getter=call.source_call("get_logging_filter"),
                    setter=call.source_filter("set_logging_filter"),
                    label="Logging Filter",
                    desc="Rules to filter log entries generated by the agency")

    model.child("agents",
                model="feat.agency.agents",
                label="Agency's Agents",
                desc="Agents running on this agency.")

    model.child("journaler",
                source=getter.source_attr('_journaler'),
                model='feat.agency.journaler',
                label='Journaler')

    model.child('database',
                source=getter.source_attr('_database'),
                label="Database")

    #FIXME: use another mean to specify the default action than name
    model.delete("del",
                 effect.delay(call.source_call("kill",
                                               stop_process=True)),
                 response.deleted("Agency Terminated"),
                 label="Terminate", desc=("Terminate the agency, "
                                          "without stopping any agents"))

    model.delete("shutdown",
                 effect.delay(call.source_call("shutdown",
                                               stop_process=True)),
                 response.deleted("Agency Shutdown"),
                 label="Shutdown", desc=("Shutdown the agency, "
                                         "stopping all agents properly"))

    model.meta("html-order", "id, role, log_filter, agents")
    model.item_meta("id", "html-link", "owner")
    model.item_meta("agents", "html-render", "array, 2")


class ReconnectToPrimary(action.Action):
    action.label('Reconnect to primary journaler target')
    action.category(ActionCategories.command)

    action.enabled(call.action_call('is_enabled'))
    action.effect(call.source_call('reconnect_to_primary_writer'))
    action.effect(effect.relative_ref())
    action.effect(response.done("Reconnected"))

    def is_enabled(self):
        return self.model.source.current_target_index != 0


@featmodels.register_model
class Journaler(model.Model):
    model.identity("feat.agency.journaler")
    model.attribute('pending_entries', value.Integer(),
                    getter=call.model_call('get_pending'),
                    label='Entries in cache')
    model.attribute('state', value.Enum(journaler.State),
                    getter=getter.source_attr('state'),
                    label='Connection state')
    model.collection('possible_targets',
                     child_names=getter.source_list_names('possible_targets'),
                     child_view=getter.source_list_get('possible_targets'),
                     child_model="feat.agency.journaler.target",
                     model_meta=[('html-render', 'array, 1')],
                     label="Possible targets")
    model.item_meta("possible_targets", "html-render", "array, 1")

    model.action('reconnect', ReconnectToPrimary)

    model.child('writer', source=getter.source_attr('_writer'),
                label='Journal writer')

    def get_pending(self):
        return len(self.source._cache)


@featmodels.register_model
class JournalTarget(model.Model):
    model.identity('feat.agency.journaler.target')
    model.attribute('class', value.String(), call.model_call('get_class'),
                    desc='Class of writer', label='Class')
    model.attribute('keywords', value.String(), call.model_call('get_params'),
                    desc='Keywords to create the writer instance',
                    label="Keywords")
    model.attribute('current', value.Boolean(), call.model_call('is_current'),
                    desc='Is it currently used', label='Current')

    def get_class(self):
        return reflect.canonical_name(self.view[0])

    def get_params(self):
        return pprint.pformat(self.view[1])

    def is_current(self):
        index = self.source.current_target_index
        current = self.source.possible_targets[index]
        return self.view == current


@featmodels.register_model
@featmodels.register_adapter(journaler.BrokerProxyWriter, IModel)
class BaseJournalWriter(model.Model):
    model.identity("feat.agency.journaler.base_writer")
    model.attribute('type', value.String(), getter=call.model_call('get_type'))
    model.attribute('pending_entries', value.Integer(),
                    getter=call.model_call('get_pending'),
                    label='Entries in cache')
    model.attribute('state', value.Enum(journaler.State),
                    getter=getter.source_attr('state'),
                    label='Connection state')

    def get_type(self):
        return type(self.source).__name__

    def get_pending(self):
        return len(self.source._cache)


@featmodels.register_model
@featmodels.register_adapter(journaler.PostgresWriter, IModel)
class PostgresWriter(BaseJournalWriter):

    model.identity('feat.agency.journaler.postgres_writer')
    model.attribute('host', value.String(), getter=getter.source_attr('host'))
    model.attribute('database', value.String(),
                    getter=getter.source_attr('dbname'))
    model.attribute('user', value.String(),
                    getter=getter.source_attr('user'))
    model.attribute('password', value.String(),
                    getter=getter.source_attr('password'))
    model.meta("html-order", "type, state, host, database, user, password, "
               "pending_entries")


@featmodels.register_model
@featmodels.register_adapter(journaler.SqliteWriter, IModel)
class SQLiteWriter(BaseJournalWriter):

    model.identity('feat.agency.journaler.sqlite_writer')
    model.attribute('filename', value.String(),
                    getter=getter.source_attr('_filename'))


@featmodels.register_model
class AgencyAgents(model.Collection):
    model.identity("feat.agency.agents")

    model.child_model("feat.agency_agent")
    model.child_names(call.model_call("_iter_agents"))
    model.child_source(getter.source_get("get_agent"))

    model.meta("html-render", "array, 1")

    ### custom ###

    def _iter_agents(self):
        res = [x.get_agent_id() for x in self.source.iter_agents()]
        return res


@featmodels.register_model
class AgencyAgent(model.Model):

    implements(IReference)

    model.identity("feat.agency_agent")

    model.attribute("id", value.String(), call.source_call("get_agent_id"),
                    label="Agent id", desc="Agent's unique identifier")
    model.attribute("instance", value.Integer(),
                    call.source_call("get_instance_id"),
                    label="Instance", desc="Agent's instance number")
    model.attribute("status", value.Enum(AgencyAgentState),
                    getter=call.source_call("get_status"),
                    label="Status", desc="Agent current status")
    model.attribute("type", value.String(),
                    getter=call.source_call("get_agent_type"),
                    label="Agent type", desc="Agent type")

    model.meta("html-order", "type, id, instance, status")
    model.item_meta("id", "html-link", "owner")

    ### IReference ###

    def resolve(self, context):
        ref = reference.Local("agents", self.name)
        return ref.resolve(context)


@featmodels.register_model
@featmodels.register_adapter(IAgencyProtocolInternal, IModel)
class Protocol(model.Model):
    model.identity('feat.IAgencyProtocolInternal')

    model.attribute('protocol_id', value.String(),
                    getter=getter.source_attr('protocol_id'))
    model.attribute('agent_class', value.String(),
                    getter=call.model_call('get_agent_class'))
    model.item_meta("agent_class", "html-link", "owner")
    model.attribute('idle', value.Boolean(),
                    getter=call.source_call('is_idle'))
    model.delete('del',
                 call.model_call('force_termination'),
                 response.deleted("Protocol terminated"),
                 label="Force termination")

    def get_agent_class(self):
        return reflect.canonical_name(self.source.get_agent_side())

    def force_termination(self):
        result = error.FeatError("Termianted via gateway")
        self.source.finalize(result)


class AgentTypeValue(value.String):
    value.label("Agent Type")
    value.desc("Agents type allowed to be started")
    value.option("dummy_buryme_agent", "Dummy Bury-Me Agent")
    value.option("dummy_local_agent", "Dummy Local Agent")
    value.option("dummy_wherever_agent", "Dummy Wherever Agent")
    value.option("dummy_buryme_standalone", "Dummy Bury-Me Standalone")
    value.option("dummy_local_standalone", "Dummy Local Standalone")
    value.option("dummy_wherever_standalone", "Dummy Wherever Standalone")
    value.options_only()


@featmodels.register_model
class Agents(model.Collection):
    model.identity("feat.agents")

    model.child_names(call.model_call("_iter_agents"))
    model.child_source(getter.model_get("_locate_agent"))

    #FIXME: use another mean to specify the default action than name
    model.create("post",
                 call.source_filter("spawn_agent"),
                 call.model_filter("_extract_reference"),
                 response.created("Agent Created"),
                 value=AgentTypeValue(),
                 label="Spawn Agent", desc="Spawn a new agent on this host")

    model.meta("html-render", "array, 1")
    model.meta("html-render",
               "array-columns, Agent Id, Agent type, Status, Description, "
               "Application")

    def init(self):
        if not self.officer.peer_info.has_role("admin"):
            raise Unauthorized("You are not administrator")

    ### custom ###

    def _iter_agents(self):
        res = [x.get_agent_id() for x in self.source.iter_agents()]
        for slave in self.source._broker.iter_slave_references():
            res.extend(slave.agents.keys())
        return res

    def _locate_agent(self, name):

        def agent_located(result):
            if result is None:
                return None
            host, port, is_remote = result
            assert is_remote, "Should not be a local agent"
            return reference.Absolute((host, port), "agents", name)

        agency = self.source

        medium = agency.get_agent(name)
        if medium is not None:
            return medium.get_agent()

        agent_ref = agency._broker.get_agent_reference(name)
        if agent_ref is not None:
            return agent_ref

        return agency.locate_agent(name).addCallback(agent_located)

    def _extract_reference(self, recipient):
        return reference.Local("agents", recipient.key)


@featmodels.register_model
@featmodels.register_adapter(broker.AgentReference, IModel)
class RemoteAgent(model.Model):
    model.identity("feat.remote_agent")
    model.reference(getter.model_attr("_reference"))

    model.attribute("id", value.String(), getter.source_attr('agent_id'),
                    label="Agent Id", desc="Agent's unique identifier")
    model.attribute("status", value.Enum(AgencyAgentState),
                    getter=call.source_call("get_status"),
                    label="Status", desc="Agent current status")
    model.attribute("type", value.String(),
                    getter=call.model_call("_get_agent_type"),
                    label="Agent type", desc="Agent type")
    model.attribute("description", value.String(),
                    label="Description",
                    getter=getter.model_attr('agent_description'))

    model.meta("html-order", "type, id, status")
    model.item_meta("id", "html-link", "owner")

    ### custom ###

    @defer.inlineCallbacks
    def init(self):
        agency_ref = yield self.source.reference.callRemote("get_agency")
        gateway_host = yield agency_ref.callRemote("get_hostname")
        gateway_port = yield agency_ref.callRemote("get_gateway_port")
        root = (gateway_host, gateway_port)
        self._reference = reference.Absolute(root, "agents", self.name)
        self.agent_description = yield self.source.reference.callRemote(
            'get_description')

    def _get_agent_type(self):
        return self.source.callRemote('get_agent_type')


@featmodels.register_model
@featmodels.register_adapter(IAgent, IModel)
class Agent(model.Model):
    model.identity("feat.agent")

    model.attribute("id", value.String(), call.source_call("get_agent_id"),
                    label="Agent Id", desc="Agent's unique identifier")
    model.attribute("shard", value.String(), call.source_call("get_shard_id"),
                    label="Shard Id", desc="Agent's shard identifier")
    model.attribute("instance", value.Integer(),
                    call.source_call("get_instance_id"),
                    label="Instance", desc="Agent's instance number")
    model.attribute("status", value.Enum(AgencyAgentState),
                    getter=call.source_call("get_agent_status"),
                    label="Status", desc="Agent current status")
    model.attribute("type", value.String(),
                    getter=call.source_call("get_agent_type"),
                    label="Agent type", desc="Agent type")
    model.attribute("application", value.String(),
                    getter=call.model_call("get_application"),
                    label="Application",
                    desc="Application the agent belongs to")
    model.attribute("description", value.String(),
                    getter=call.model_call("get_description"),
                    label="Description",
                    desc="Description specific to the agent's instance")

    model.child("partners",
                model="feat.partners",
                label="Partners", desc="Agent's partners")

    model.child("resources",
                model="feat.resources",
                enabled=call.model_call("_has_resources"),
                label="Resources", desc="Agent's resources.")

    model.collection("protocols",
                     label="Protocols",
                     child_names=call.model_call("get_protocols"),
                     child_source=getter.model_get('get_protocol'),
                     model_meta=[("html-render", "array, 2")])

    #FIXME: use another mean to specify the default action than name
    model.delete("del",
                 call.model_call("_terminate"),
                 response.deleted("Agent Terminated"),
                 label="Terminate", desc=("Terminate the agent, "
                                          "without saying goodbye"))

    model.delete("shutdown",
                 call.model_call("_shutdown"),
                 response.deleted("Agent Shutdown"),
                 label="Shutdown", desc=("Shutdown the agent, "
                                         "saying goodbye to partners"))

    model.command('restart',
                  call.model_call('_restart'),
                  response.done("Restarted"),
                  result=value.Response(),
                  label="Restart", desc="Restart the agent")

    model.meta("html-order", "type, shard, id, instance, "
               "status, partners, resources")
    model.item_meta("id", "html-link", "owner")
    model.item_meta("partners", "html-render", "array, 2")
    model.item_meta("resources", "html-render", "array, 2")

    ### custom ###

    def init(self):
        self._medium = self.source._get_state().medium

    def _has_resources(self):
        return isinstance(self.source, resource.AgentMixin)

    def _shutdown(self):
        self._medium.terminate()
        return reference.Local("agents")

    def _terminate(self):
        self._medium.terminate_hard()
        return reference.Local("agents")

    def _restart(self):
        d = self._medium.terminate_hard()
        d.addCallback(defer.drop_param, self._medium.agency.start_agent,
                      self._medium.get_descriptor())
        return d

    def get_application(self):
        return self.source.application.name

    def get_protocols(self):
        return self._medium._protocols.keys()

    def get_protocol(self, key):
        return self._medium._protocols.get(key)

    def get_description(self):
        return self.source.get_description()


@featmodels.register_model
class Resources(model.Model):
    model.identity("feat.resources")

    model.child("classes",
                view=call.source_call("get_resource_usage"),
                model="feat.resource_classes",
                label="Classes", desc="Resource classes")

    model.meta("html-order", "classes")
    model.item_meta("classes", "html-render", "array, 3")


@featmodels.register_model
class ResourceClasses(model.Collection):
    model.identity("feat.resource_classes")

    model.meta("html-render", "array, 2")

    model.child_model(getter.model_get("_child_model"))
    model.child_names(call.view_call("keys"))
    model.child_view(getter.view_get("get"))

    ### custom ####

    _models_lookup = {"scalar_def": "feat.scalar_resource",
                      "range_def": "feat.range_resource"}

    def _child_model(self, name):
        return self._models_lookup.get(self.view[name][0])


@featmodels.register_model
class ScalarResourceClass(model.Model):
    model.identity("feat.scalar_resource")

    model.attribute("name", value.String(), getter.model_attr("name"))
    model.attribute("total", value.Integer(),
                    call.view_call("__getitem__", 1))
    model.attribute("allocated", value.Integer(),
                    call.view_call("__getitem__", 2))
    model.attribute("reserved", value.Integer(),
                    call.view_call("__getitem__", 3))

    model.meta("html-order", "name, total, allocated, reserved")


class RangeTotal(value.Collection):
    value.allows(value.Integer())
    value.min_size(2)
    value.max_size(2)


class RangeItems(value.Collection):
    value.allows(value.Integer())


@featmodels.register_model
class RangeResourceClass(model.Model):
    model.identity("feat.range_resource")

    model.attribute("name", value.String(), getter.model_attr("name"))
    model.attribute("total", RangeTotal(),
                    call.view_call("__getitem__", 1))
    model.attribute("allocated", RangeItems(),
                    call.view_call("__getitem__", 2))
    model.attribute("reserved", RangeItems(),
                    call.view_call("__getitem__", 3))

    model.meta("html-order", "name, total, allocated, reserved")


@featmodels.register_model
class Partners(model.Collection):
    model.identity("feat.partners")

    model.view(call.source_call("query_partners", "all"))

    model.child_label("Partner")
    model.child_model("feat.partner")
    model.child_names(call.model_call("iter_partner_names"))
    model.child_view(getter.model_get("get_partner"))

    model.meta("html-render", "array, 2")

    ### custom ###

    def iter_partner_names(self):
        return [p.recipient.key for p in self.view]

    def get_partner(self, name):
        for partner in self.view:
            if partner.recipient.key == name:
                return partner
        return None


@featmodels.register_model
class Partner(model.Model):
    #FIXME: should be more dynamic and dynamically add attribute
    model.identity("feat.partner")

    model.attribute("type", value.String(),
                    getter.view_attr("type_name"), label="Type")
    model.attribute("role", value.String("unknown"),
                    getter.view_getattr(), label="Role")

    model.child("recipient",
                source=getter.view_getattr(),
                model="feat.recipient",
                label="Recipient")

    model.meta("html-order", "type, role, recipient")
    model.item_meta("recipient", "html-render", "array, 1")


@featmodels.register_model
class Recipient(model.Model):
    model.identity("feat.recipient")
    model.reference(call.model_call("_get_reference"))

    model.attribute("key", value.String(),
                    getter.source_attr("key"),
                    label="Key")
    model.attribute("route", value.String(),
                    getter.source_attr("route"),
                    label="Route")

    model.meta("html-order", "key, route")
    model.item_meta("key", "html-link", "owner")

    ### custom ###

    def _get_reference(self):
        return reference.Local("agents", self.source.key)


@featmodels.register_model
@featmodels.register_adapter(IMonitorAgent, IModel)
class MonitorAgent(Agent):
    model.identity("feat.agent.monitor")
    model.view(call.source_call("get_monitoring_status"))

    model.attribute("state", value.Enum(MonitorState),
                    getter.view_get("__getitem__"),
                    label="State", desc="Current monitor state")
    model.attribute("location", value.String(),
                    getter.view_get("__getitem__"),
                    label="Monitor's Location")

    model.collection("locations",
                     child_names=call.model_call("_get_location_names"),
                     child_view=getter.model_get("_get_location"),
                     child_model="feat.monitored_location",
                     model_meta=[("html-render", "array, 4")],
                     label="Monitored Locations")

    model.meta("html-order", "state, location")
    model.item_meta("locations", "html-render", "array, 4")

    ### custom ###

    def _get_location_names(self):
        return self.view["locations"].keys()

    def _get_location(self, name):
        return self.view["locations"][name]


@featmodels.register_model
class MonitoredLocation(model.Model):
    model.identity("feat.monitored_location")

    model.attribute("hostname", value.String(),
                    getter.model_attr("name"),
                    label="Host Name", desc="Monitored host")
    model.attribute("state", value.Enum(LocationState),
                    getter.view_get("__getitem__"),
                    label="Location State",
                    desc="Monitored location's state")

    model.collection("agents",
                     child_names=call.model_call("_get_agent_names"),
                     child_view=getter.model_get("_get_agent"),
                     child_model="feat.monitored_agent",
                     model_meta=[("html-render", "array, 2")],
                     label="Monitored Agents")

    model.meta("html-render", "array, 3")
    model.meta("html-order", "state, agents")

    ### custom ###

    def _get_agent_names(self):
        return self.view["patients"].keys()

    def _get_agent(self, name):
        return self.view["patients"][name]


@featmodels.register_model
class MonitoredAgent(model.Model):
    model.identity("feat.monitored_agent")

    model.attribute("type", value.String(),
                    call.view_call("__getitem__", "patient_type"),
                    label="Type", desc="Monitored agent's type")
    model.attribute("state", value.Enum(PatientState),
                    getter.view_get("__getitem__"),
                    label="Agent State",
                    desc="Monitored agent's state")
    model.attribute("heartbeats", value.Integer(),
                    call.view_call("__getitem__", "counter"),
                    label="Heartbeats", desc="Received heartbeats")

    model.child("recipient",
                source=call.view_call("__getitem__", "recipient"),
                model="feat.recipient", label="Recipient")

    model.meta("html-order", "type, state, recipient, heartbeats")
    model.item_meta("recipient", "html-render", "array, 1")



### Models for alert agent ###


ALERT_TABLE_ORDER=('array-columns, Service name, Hostname, Agent id, '
                   'Count, Last status, Severity')


class RescanShardAction(action.Action):
    action.label('Trigger rescanning the shard')
    action.category(ActionCategories.command)
    action.result(value.Response())
    action.effect(call.source_call('rescan_shard'))
    action.effect(response.done("Done"))


@featmodels.register_model
@featmodels.register_adapter(IAlertAgent, IModel)
class AlertAgent(Agent):
    model.identity("feat.agent.alert")

    model.child('services',
                view=call.source_call("get_alerts"),
                model="feat.agent.alert.services",
                label='Services', desc='Services known to this agent')
    model.item_meta('services', 'html-render', 'array, 4')
    model.item_meta('services', "html-render", ALERT_TABLE_ORDER)

    model.attribute('nagios_service.cfg', value.Binary('text/ascii'),
                    call.source_call('generate_nagios_service_cfg'))

    model.action('rescan', RescanShardAction)


@featmodels.register_model
class AlertServices(model.Collection):
    model.identity("feat.agent.alert.services")

    model.child_names(call.model_call('get_names'))
    model.child_view(getter.model_get('get_for_host'))
    model.child_model("feat.agent.alert.services.<hostname>")
    model.meta('html-render', 'array, 3')
    model.meta("html-render", ALERT_TABLE_ORDER)

    def get_names(self):
        return set([x.hostname for x in self.view])

    def get_for_host(self, hostname):
        return [x for x in self.view if x.hostname == hostname]


@featmodels.register_model
class AlertAgentsOnHost(model.Collection):
    model.identity("feat.agent.alert.services.<hostname>")

    model.child_names(call.model_call('get_names'))
    model.child_view(getter.model_get('getter'))
    model.child_model("feat.agent.alert.services.<hostname>.<description>")
    model.meta("html-render", ALERT_TABLE_ORDER)

    def get_names(self):
        return set([x.description or x.agent_id for x in self.view])

    def getter(self, description):
        return [x for x in self.view
                if description in (x.description, x.agent_id)]


@featmodels.register_model
class AlertServicesOfAgent(model.Collection):
    model.identity("feat.agent.alert.services.<hostname>.<description>")

    model.child_names(call.model_call('get_names'))
    model.child_source(getter.model_get('getter'))
    model.child_view(effect.context_value('source'))
    model.child_model(
        "feat.agent.alert.services.<hostname>.<description>.service")
    model.meta('html-render', 'array, 3')
    model.meta("html-render", ALERT_TABLE_ORDER)

    def get_names(self):
        return set([x.name for x in self.view])

    def getter(self, name):
        return first(x for x in self.view if x.name == name)


class _AlertAction(action.Action):
    action.result(value.Response())
    action.effect(call.action_call('call_agent'))
    action.effect(response.done("Done"))

    def call_agent(self):
        raise NotImplementedError("override me")


class RaiseAlert(_AlertAction):
    action.label("Simulate raising this alert")

    def call_agent(self):
        return self.model.view.alert_raised(self.model.source)


class ResolveAlert(_AlertAction):
    action.label("Simulate resolving this alert")

    def call_agent(self):
        return self.model.view.alert_resolved(self.model.source)


@featmodels.register_model
class AlertService(model.Model):
    model.identity("feat.agent.alert.services.<hostname>.<description>"
                   ".service")
    model.attribute('count', value.Integer(),
                    getter.source_attr('received_count'),
                    label='Count')
    model.attribute('name', value.String(),
                    getter.source_attr('name'),
                    label="Service name")
    model.attribute('agent_id', value.String(),
                    getter.source_attr('agent_id'),
                    label='Agent id')
    model.attribute('severity', value.Enum(Severity),
                    getter.source_attr('severity'),
                    label='Severity')
    model.attribute('hostname', value.String(),
                    getter.source_attr('hostname'),
                    label='Hostname')
    model.attribute('status_info', value.String(default=''),
                    getter.source_attr('status_info'),
                    label='Last status')
    model.attribute('description', value.String(default=''),
                    getter.source_attr('description'),
                    label='Description used in Nagios')
    model.item_meta("name", "html-link", "owner")

    model.action('raise', RaiseAlert)
    model.action('resolve', ResolveAlert)
    model.delete('del',
                 effect.context_value('source'),
                 call.view_filter('delete_alert'),
                 response.deleted("Deleted"),
                 desc="Delete the alert",
                 label="Delete")
