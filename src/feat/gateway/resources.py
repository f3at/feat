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
import cgi
import operator
import socket

from feat.common import defer, time
from feat.gateway import models
from feat.web import http, webserver


class BaseResource(webserver.BasicResource):

    def create_url(self, request, child):
        base = request.path
        if base[-1] == "/":
            return base + child
        return base + "/" + child

    def render_header(self, doc):
        hostname = unicode(socket.gethostbyaddr(socket.gethostname())[0])
        doc.extend(["<HTML><HEAD>"
                    "<TITLE>F3AT Gateway</TITLE></HEAD><BODY>"
                    "<I>"
                    "<A href='/'>top<A>"
                    " on ", hostname,
                    "<I>"])

    def render_footer(self, doc):
        doc.extend(["</BODY></HTML>"])

    def redirect(self, path, host=None, port=None):
        url = http.compose(path, host=host, port=port)
        raise http.MovedPermanently(location=url)


class Root(BaseResource):

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IRoot(model)
        self["agencies"] = Agencies(model)
        self["agents"] = Agents(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")
        response.set_header("Cache-Control", "no-store")
        response.set_header("connection", "close")
        hostname = unicode(socket.gethostbyaddr(socket.gethostname())[0])

        agencies_url = self.create_url(request, "agencies")
        agents_url = self.create_url(request, "agents")

        doc = ["<HTML><HEAD><TITLE>F3AT Gateway</TITLE></HEAD><BODY>"
                "<H2>F3EAT Gateway</H2>"
                "<I>", hostname, "</I>"
                "<UL>"
                "<LI><H2><A href='", agencies_url, "'>Agencies</A></H2></LI>"
                "<LI><H2><A href='", agents_url, "'>Agents</A></H2></LI>"
                "</UL></BODY></HTML>"]

        response.writelines(doc)

    def render_error(self, request, response, e):
        response.set_mime_type("text/html")
        response.write("<HTML><HEAD><TITLE>F3AT Gateway</TITLE></HEAD><BODY>")
        if isinstance(e, http.HTTPError):
            response.write("<H2>ERROR %d: %s</H2>"
                           % (e.status_code, e.error_name))
        else:
            response.write("<H2>ERROR: %s</H2>" % e)
        response.write("</BODY></HTML>")


class Agencies(BaseResource):

    enable_actions = True
    startable_agents = {"dummy_buryme_standalone":
                         "Dummy Bury-Me Standalone",
                        "dummy_local_standalone":
                         "Dummy Local Standalone",
                        "dummy_wherever_standalone":
                         "Dummy Wherever Standalone"}

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IRoot(model)

    def locate_child(self, request, location, remaining):
        agency_id = remaining[0]
        agency = self.model.get_agency(agency_id)
        if agency is not None:
            return Agency(agency), remaining[1:]

        # Only the master agency knows the other ones
        self._ensure_master(request)

        d = self.model.locate_agency(agency_id)
        d.addCallback(self._agency_located, request, location, remaining)
        return d

    def render_resource(self, request, response, location):
        # Only the master agency knows the other ones
        self._ensure_master(request)

        # Force mime-type to html
        response.set_mime_type("text/html")
        response.set_header("Cache-Control", "no-store")
        response.set_header("connection", "close")

        if request.method == http.Methods.POST:
            if self.enable_actions and self.model.is_master():
                data = "\n".join(request.readlines())
                params = http.urldecode(data, request.encoding)

                if 'full_shutdown' in params:
                    time.callLater(0, self.model.full_shutdown)
                    doc = ["<HTML><HEAD>"
                           "<TITLE>F3AT Gateway</TITLE></HEAD><BODY>"
                           "<H2>Offline</H2>"
                           "</BODY></HTML>"]
                    response.writelines(doc)
                    return

                if 'start_agent' in params:
                    agent_type = params['agent_type'][0]
                    if agent_type in self.startable_agents:
                        d = self.model.spawn_agent(agent_type)
                        d.addCallback(defer.drop_param,
                                      self.redirect, request.path)
                        return d

            self.redirect(request.path)

        doc = []
        self.render_header(doc)

        doc.extend(["<H2>Agencies</H2>"
                    "<TABLE border='0'>"])

        for agency_id in self.model.iter_agency_ids():
            agency_url = self.create_url(request, agency_id)
            doc.extend(["<TR><TD><A href='", agency_url, "'>",
                        agency_id, "</A>"
                        "</TD></TR>"])

        doc.extend(["</TABLE>"])

        if self.enable_actions:
            if self.startable_agents and self.model.is_master():
                doc.extend(["</TABLE>"
                            "<H2>Actions</H2>"
                            "<TABLE>"
                            "<TR>"
                            "<TD valign='top'><B>Start Agent:</B></TD>"
                            "<TD>"
                            "<FORM method='post'>"
                            "<DIV>"
                            "<SELECT name='agent_type'>"
                            "<option value='' selected>"
                            "(select type)</option>"])

                startable = self.startable_agents.items()
                startable.sort(key=operator.itemgetter(0))
                for k, v in startable:
                    doc.extend(["<option value='", k, "'>", v, "</option>"])

                doc.extend(["</SELECT>"
                            "<INPUT type='submit' name='start_agent'"
                            " value='Start'>"
                            "</DIV>"
                            "</FORM>"
                            "</TD>"
                            "</TR>"
                            "<TR>"
                            "<TD>"
                            "<FORM method='post'>"
                            "<INPUT type='submit' name='full_shutdown'"
                            " value='Full Shutdown'>"
                            "</FORM>"
                            "</TD>"
                            "</TR>"
                            "</TABLE>"])

        self.render_footer(doc)
        response.writelines(doc)

    ### private ###

    def _ensure_master(self, request):
        result = self.model.locate_master()
        if result is not None:
            host, port, is_remote = result
            if is_remote:
                self.redirect(request.path, host, port)

    def _agency_located(self, result, request, location, remaining):
        if result is None:
            return None
        host, port, _is_remote = result
        self.redirect(request.path, host, port)


class Agents(BaseResource):

    enable_actions = True

    startable_agents = {"dummy_buryme_agent":
                         "Dummy Bury-Me Agent",
                        "dummy_local_agent":
                         "Dummy Local Agent",
                        "dummy_wherever_agent":
                         "Dummy Wherever Agent"}

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IRoot(model)

    def locate_child(self, request, location, remaining):
        agent_id = remaining[0]
        aagent = self.model.get_agent(agent_id)
        if aagent is not None:
            agent_type = aagent.get_agent().descriptor_type
            if agent_type == "monitor_agent":
                return Monitor(aagent), remaining[1:]
            return Agent(aagent), remaining[1:]
        d = self.model.locate_agent(agent_id)
        d.addCallback(self._agent_located, request, location, remaining)
        return d

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")
        response.set_header("Cache-Control", "no-store")
        response.set_header("connection", "close")

        if request.method == http.Methods.POST:
            if self.enable_actions:
                data = "\n".join(request.readlines())
                params = http.urldecode(data, request.encoding)

                if 'start_agent' in params:
                    agent_type = params['agent_type'][0]
                    if agent_type in self.startable_agents:
                        d = self.model.spawn_agent(agent_type)
                        d.addCallback(defer.drop_param,
                                      self.redirect, request.path)
                        return d

            self.redirect(request.path)

        return self.render_response(request, response)

    def render_response(self, request, response):
        doc = []
        self.render_header(doc)
        doc.extend(["<H2>Agents</H2>"
                    "<TABLE border='1'>"
                    "<TR>"
                    "<TH>Identifier</TH>"
                    "<TH>Instance</TH>"
                    "<TH>Type</TH>"
                    "</TR>"])

        for agent in self.model.iter_agents():
            agent_model = models.IAgent(agent)
            agent_url = self.create_url(request, agent_model.agent_id)
            doc.extend(["<TR><TD><A href='", agent_url, "'>",
                        agent_model.agent_id, "</A>",
                        "</TD><TD>",
                        str(agent_model.instance_id),
                        "</TD><TD>",
                        agent_model.agent_type,
                        "</TD></TR>"])

        if self.enable_actions:
            if self.startable_agents and self.model.is_master():
                doc.extend(["</TABLE>"
                            "<H2>Actions</H2>"
                            "<TABLE>"
                            "<TR>"
                            "<TD valign='top'><B>Start Agent:</B></TD>"
                            "<TD>"
                            "<FORM method='post'>"
                            "<DIV>"
                            "<SELECT name='agent_type'>"
                            "<option value='' selected>"
                            "(select type)</option>"])

                startable = self.startable_agents.items()
                startable.sort(key=operator.itemgetter(0))
                for k, v in startable:
                    doc.extend(["<option value='", k, "'>", v, "</option>"])

                doc.extend(["</SELECT>"
                            "<INPUT type='submit' name='start_agent'"
                            " value='Start'>"
                            "</DIV>"
                            "</FORM>"
                            "</TD>"
                            "</TR>"
                            "</TABLE>"])

        self.render_footer(doc)
        response.writelines(doc)


    ### private ###

    def _agent_located(self, result, request, location, remaining):
        if result is None:
            return None
        host, port, _is_remote = result
        url = http.compose(request.path, host=host, port=port)
        raise http.MovedPermanently(location=url)


class Agency(BaseResource):

    enable_actions = True

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IAgency(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")
        response.set_header("Cache-Control", "no-store")
        response.set_header("connection", "close")

        if self.enable_actions and request.method == http.Methods.POST:
            data = "\n".join(request.readlines())
            params = http.urldecode(data, request.encoding)

            if 'set_logging_filter' in params:
                filter = params["filter"][0]
                self.model.set_logging_filter(filter)

            if 'shutdown_agency' in params:
                time.callLater(1, self.model.shutdown_agency)
                return self._redirect_to_top()

            if 'terminate_agency' in params:
                time.callLater(1, self.model.terminate_agency)
                return self._redirect_to_top()

            if 'kill_agency' in params:
                time.callLater(1, self.model.kill_agency)
                return self._redirect_to_top()

        agents_url = "/agents"

        doc = []
        self.render_header(doc)
        doc.extend(["<H2>Agency</H2>"
                    "<TABLE>"
                    "<TR>"
                    "<TD><B>Identifier:</B></TD>"
                    "<TD>", self.model.agency_id, "</TD>"
                    "</TR>",
                    "<TR>"
                    "<TD><B>Role:</B></TD>"
                    "<TD>", self.model.role.name, "</TD>"
                    "</TR>"
                    "</TABLE>"
                    "<UL>"
                    "<LI><H4><A href='", agents_url, "'>Agents</A></H4></LI>"
                    "</UL>"])

        if self.enable_actions:
            dbg = self.model.get_logging_filter()
            doc.extend(["</TABLE>"
                        "<H2>Actions</H2>"
                        "<TABLE>"
                        "<TR>"
                        "<TD valign='top'><B>Global Logging Filter:</TD>"
                        "<TD colspan='2'>"
                        "<DIV>"
                        "<FORM method='post'>"
                        "<INPUT type='text' name='filter' value='", dbg, "'>"
                        "<INPUT type='submit' name='set_logging_filter'"
                        " value='Update'>"
                        "</FORM>"
                        "</DIV>"
                        "</TD>"
                        "</TR>"
                        "<TR>"
                        "<TD>"
                        "<FORM method='post'>"
                        "<INPUT type='submit' name='shutdown_agency'"
                        " value='Shutdown'>"
                        "</FORM>"
                        "</TD>"
                        "<TD>"
                        "<FORM method='post'>"
                        "<INPUT type='submit' name='terminate_agency'"
                        " value='Terminate'>"
                        "</FORM>"
                        "</TD>"
                        "<TD>"
                        "<FORM method='post'>"
                        "<INPUT type='submit' name='kill_agency'"
                        " value='Kill'>"
                        "</FORM>"
                        "</TD>"
                        "</TR>"
                        "</TABLE>"])

        self.render_footer(doc)
        response.writelines(doc)

    def _redirect_to_top(self):
        self.redirect("/", self.model.get_hostname(),
                      self.model.default_gateway_port)


class Agent(BaseResource):

    enable_actions = True

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IAgent(model)
        self["partners"] = Partners(model)
        self["resources"] = Resources(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")
        response.set_header("Cache-Control", "no-store")
        response.set_header("connection", "close")

        if self.enable_actions and request.method == http.Methods.POST:
            data = "\n".join(request.readlines())
            params = http.urldecode(data, request.encoding)

            if 'terminate_agent' in params:
                d = self.model.terminate_agent()
                d.addCallback(self._move_up)
                return d

            if 'kill_agent' in params:
                d = self.model.kill_agent()
                d.addCallback(self._move_up)
                return d

        doc = []
        self.render_header(doc)

        self._update_document(request, response, doc)

        if self.enable_actions:
            self._update_actions(request, response, doc)

        self.render_footer(doc)
        response.writelines(doc)

    def _move_up(self, _):
        raise http.MovedPermanently(location="/agents")

    def _update_document(self, request, response, doc):

        partners_url = self.create_url(request, "partners")
        resources_url = self.create_url(request, "resources")
        agency_url = "/agencies/" + self.model.agency_id

        doc.extend(["<H2>Agent</H2>"
                    "<TABLE>"
                    "<TR>"
                    "<TD><B>Agent Type:</B></TD>"
                    "<TD>", self.model.agent_type, "</TD>"
                    "</TR>"
                    "<TR>"
                    "<TD><B>Agent Id:</B></TD>"
                    "<TD>", self.model.agent_id, "</TD>"
                    "</TR>"
                    "<TR>"
                    "<TD><B>Instance Id:</B></TD>"
                    "<TD>", str(self.model.instance_id), "</TD>"
                    "</TR>"
                    "<TR>"
                    "<TD><B>Status:</B></TD>"
                    "<TD>", self.model.agent_status.name, "</TD>"
                    "</TR>"
                    "<TR>"
                    "<TD><B>Agency:</B></TD>"
                    "<TD>",
                    "<A href='", agency_url, "'>", self.model.agency_id, "</A>"
                    "</TD>"
                    "</TR>"
                    "</TABLE>"
                    "<UL>"
                    "<LI>"
                    "<H4><A href='", partners_url, "'>Partners</A></H4>"
                    "</LI>"])

        if self.model.have_resources():
            doc.extend(["<LI><H4><A href='", resources_url,
                        "'>Resources</A></H4></LI>"])

        doc.extend(["</UL>"])

    def _update_actions(self, request, response, doc):
        doc.extend(["</TABLE>"
                    "<H2>Actions</H2>"
                    "<TABLE>"
                    "<TR>"
                    "<TD>"
                    "<FORM method='post'>"
                    "<INPUT type='submit' name='terminate_agent'"
                    " value='Terminate'>"
                    "</FORM>"
                    "</TD>"
                    "<TD>"
                    "<FORM method='post'>"
                    "<INPUT type='submit' name='kill_agent'"
                    " value='Kill'>"
                    "</FORM>"
                    "</TD>"
                    "</TR>"
                    "</TABLE>"])


class Monitor(Agent):

    def __init__(self, model):
        Agent.__init__(self, model)
        self.monitor_model = models.IMonitor(model)

    def _update_document(self, request, response, doc):
        Agent._update_document(self, request, response, doc)

        status = self.monitor_model.get_monitoring_status()

        doc.extend(["<H2>Monitoring Status</H2>"
                    "<TABLE>"
                    "<TR>"
                    "<TD><B>Monitor Location</B></TD>"
                    "<TD>", str(status["location"]), "</TD>"
                    "</TR>"
                    "<TR>"
                    "<TD><B>Monitor State:</B></TD>"
                    "<TD>", status["state"].name, "</TD>"
                    "</TR>"
                    "</TABLE>"
                    "<H2>Monitoring Locations</H2>"
                    "<TABLE border='1'>"
                    "<TR>"
                    "<TH align='left'>Location</TH>"
                    "<TH align='left'>State</TH>"
                    "<TH align='left'>Patients</TH>"
                    "</TR>"])

        for name, loc in status["locations"].iteritems():
            doc.extend(["<TR>"
                        "<TD valign='top'>", str(name), "</TD>"
                        "<TD valign='top'>", loc["state"].name, "</TD>"
                        "<TD>"
                        "<TABLE border='1'>"
                        "<TR>"
                        "<TH align='left'>Agent Type</TH>"
                        "<TH align='left'>Agent ID</TH>"
                        "<TH align='left'>Shard ID</TH>"
                        "<TH align='left'>State</TH>"
                        "<TH align='left'>Heart Beats</TH>"
                        "</TR>"])
            for recip, pat in loc["patients"].iteritems():
                agent_url = "/agents/" + recip.key
                type_name = pat["patient_type"] or "unknown"
                if type_name == "unknown":
                    type_name = "<I>" + type_name + "</I>"
                else:
                    type_name = "<B>" + type_name + "</B>"
                doc.extend(["<TR>"
                            "<TD>", type_name, "</TD>"
                            "<TD><A href='", agent_url, "'>",
                            recip.key, "</A></TD>",
                            "<TD>", recip.route, "</TD>"
                            "<TD>", pat["state"].name, "</TD>"
                            "<TD align='right'>", str(pat["counter"]), "</TD>"
                            "</TR>"])
            doc.extend(["</TABLE></TD></TR>"])


class Partners(BaseResource):

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IAgent(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")
        response.set_header("Cache-Control", "no-store")
        response.set_header("connection", "close")

        doc = []
        self.render_header(doc)
        doc.extend(["<H2>Partners</H2>",
                    "<TABLE>",
                    "<TR>"
                    "<TH>Relation</TH>"
                    "<TH>Role</TH>"
                    "<TH>Agent Id</TH>"
                    "<TH>Shard Id</TH>"
                    "</TR>"])

        for partner in self.model.iter_partners():
            partner_model = models.IPartner(partner)
            agent_id = partner_model.agent_id
            agent_url = "/agents/" + agent_id
            partner_type = cgi.escape(partner_model.partner_type)
            doc.extend(["<TR>"
                        "<TD>", partner_type, "</TD>"
                        "<TD>", str(partner_model.role), "</TD>"
                        "<TD>"
                        "<A href='", agent_url, "'>", agent_id, "</A>"
                        "</TD>"
                        "<TD>", partner_model.shard_id, "</TD>"
                        "</TR>"])

        doc.extend(["</TABLE>"])
        self.render_footer(doc)
        response.writelines(doc)


class Resources(BaseResource):

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IAgent(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")
        response.set_header("Cache-Control", "no-store")
        response.set_header("connection", "close")

        doc = []
        self.render_header(doc)
        doc.extend(["<H2>Resources</H2>"
                    "<TABLE border='1'>"
                    "<TR>"
                    "<TH align='left'>Name</TH>"
                    "<TH align='right'>Total</TH>"
                    "<TH align='right'>Allocated</TH>"
                    "<TH align='right'>Pre-allocated</TH>"
                    "</TR>"])

        for name, (total, allocated, pending) in self.model.iter_resources():
            doc.extend(["<TR>",
                        "<TD>", name, "</TD>",
                        "<TD align='right'>", str(total), "</TD>",
                        "<TD align='right'>", str(allocated), "</TD>",
                        "<TD align='right'>", str(pending), "</TD>",
                        "</TR>"])

        doc.extend(["</TABLE>"])
        self.render_footer(doc)
        response.writelines(doc)
