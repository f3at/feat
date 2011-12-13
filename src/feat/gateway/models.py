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

import os
import signal

from zope.interface import implements

from feat.agencies.net import agency as net_agency, broker
from feat.agents.base import resource, agent as base_agent

from feat.common import adapter, defer
from feat.models import model, action, value, reference, response
from feat.models import effect, call, getter, setter

from feat.agencies.interface import AgencyRoles
from feat.interface.agent import AgencyAgentState
from feat.models.interface import IModel, IReference


@adapter.register(net_agency.Agency, IModel)
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
    model.child('api', model='feat.api',
                label='Api', desc='Api exposed by subproject')

    model.meta("html-order", "agencies, agents")
    model.item_meta("agencies", "html-render", "array, 1")
    model.item_meta("agents", "html-render", "array, 1")

    ### custom ###

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


class Api(model.Model):
    model.identity('feat.api')


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

    model.meta("html-render", "array, 2")

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


@adapter.register(broker.AgentReference, IModel)
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

    def _get_agent_type(self):
        return self.source.callRemote('get_agent_type')


@adapter.register(base_agent.BaseAgent, IModel)
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

    model.child("partners",
                model="feat.partners",
                label="Partners", desc="Agent's partners")

    model.child("resources",
                model="feat.resources",
                enabled=call.model_call("_has_resources"),
                label="Resources", desc="Agent's resources.")

    model.meta("html-order", "type, shard, id, instance, "
               "status, partners, resources")
    model.item_meta("id", "html-link", "owner")
    model.item_meta("partners", "html-render", "array, 2")
    model.item_meta("resources", "html-render", "array, 2")

    ### custom ###

    def _has_resources(self):
        return isinstance(self.source, resource.AgentMixin)


class Resources(model.Model):
    model.identity("feat.resources")

    model.child("classes",
                view=call.source_call("get_resource_usage"),
                model="feat.resource_classes",
                label="Classes", desc="Resource classes")

    model.meta("html-order", "classes")
    model.item_meta("classes", "html-render", "array, 3")


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


from feat.agents.monitor import monitor_agent
from feat.agents.monitor.interface import MonitorState
from feat.agents.monitor.interface import LocationState
from feat.agents.monitor.interface import PatientState


@adapter.register(monitor_agent.MonitorAgent, IModel)
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
