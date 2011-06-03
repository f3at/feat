import cgi

from feat.gateway import models
from feat.web import http, webserver


class BaseResource(webserver.BasicResource):

    def create_url(self, request, child):
        base = request.path
        if base[-1] == "/":
            return base + child
        return base + "/" + child


class Root(BaseResource):

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IRoot(model)
        self["agencies"] = Agencies(model)
        self["agents"] = Agents(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")

        agencies_url = self.create_url(request, "agencies")
        agents_url = self.create_url(request, "agents")

        doc = ["<HTML><HEAD><TITLE>F3AT Gateway</TITLE></HEAD><BODY>"
                "<H2>F3EAT Gateway</H2><UL>"
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

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IRoot(model)

    def locate_child(self, request, location, remaining):
        agency_id = remaining[0]
        agency = self.model.get_agency(agency_id)
        if agency is not None:
            return Agency(agency), remaining[1:]
        d = self.model.locate_agency(agency_id)
        d.addCallback(self._agency_located, request, location, remaining)
        return d

    def render_resource(self, request, response, location):
        # Only the master agency knows the other ones
        result = self.model.locate_master()
        if result is not None:
            host, port, is_remote = result
            if is_remote:
                url = http.compose(request.path, host=host, port=port)
                raise http.MovedPermanently(location=url)

        # Force mime-type to html
        response.set_mime_type("text/html")

        doc = ["<HTML><HEAD>"
               "<TITLE>F3AT Gateway</TITLE></HEAD><BODY>"
               "<H2>Agencies</H2>"
               "<TABLE border='0'>"]

        for agency_id in self.model.iter_agency_ids():
            agency_url = self.create_url(request, agency_id)
            doc.extend(["<TR><TD><A href='", agency_url, "'>",
                        agency_id, "</A>"
                        "</TD></TR>"])

        doc.extend(["</TABLE>"
                    "</BODY></HTML>"])

        response.writelines(doc)

    ### private ###

    def _agency_located(self, result, request, location, remaining):
        if result is None:
            return None
        host, port, _is_remote = result
        url = http.compose(request.path, host=host, port=port)
        raise http.MovedPermanently(location=url)


class Agents(BaseResource):

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IRoot(model)

    def locate_child(self, request, location, remaining):
        agent_id = remaining[0]
        agent = self.model.get_agent(agent_id)
        if agent is not None:
            return Agent(agent), remaining[1:]
        d = self.model.locate_agent(agent_id)
        d.addCallback(self._agent_located, request, location, remaining)
        return d

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")

        doc = ["<HTML><HEAD>",
               "<TITLE>F3AT Gateway</TITLE>",
               "</HEAD><BODY>",
               "<H2>Agents</H2>",
               "<TABLE border='1'>",
               "<TR><TH>Identifier</TH><TH>Instance</TH><TH>Type</TH></TR>"]

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

        doc.extend(["</TABLE>"
                    "</BODY></HTML>"])

        response.writelines(doc)


    ### private ###

    def _agent_located(self, result, request, location, remaining):
        if result is None:
            return None
        host, port, _is_remote = result
        url = http.compose(request.path, host=host, port=port)
        raise http.MovedPermanently(location=url)


class Agency(BaseResource):

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IAgency(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")

        agent_url = self.create_url(request, self.model.agency_id)

        doc = ["<HTML><HEAD>",
               "<TITLE>F3AT Gateway</TITLE>",
               "</HEAD><BODY>",
               "<H2>Agency</H2>",
               "<TABLE>",
               "<TR><TD><B>Identifier:</B></TD><TD>",
               self.model.agency_id,
               "</TD></TR>",
               "<TR><TD><B>Role:</B></TD><TD>",
               self.model.role.name,
               "</TD></TR>",
               "</TABLE>",
               "</BODY></HTML>"]

        response.writelines(doc)


class Agent(BaseResource):

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IAgent(model)
        self["partners"] = Partners(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")

        partners_url = self.create_url(request, "partners")

        doc = ["<HTML><HEAD>",
               "<TITLE>F3AT Gateway</TITLE>",
               "</HEAD><BODY>",
               "<H2>Agent</H2>",
               "<TABLE>",
               "<TR><TD><B>Agent Type:</B></TD><TD>",
               self.model.agent_type,
               "</TD></TR>",
               "<TR><TD><B>Agent Id:</B></TD><TD>",
               self.model.agent_id,
               "</TD></TR>",
               "<TR><TD><B>Instance Id:</B></TD><TD>",
               str(self.model.instance_id),
               "</TD></TR>",
               "</TABLE>",
               "<UL>",
               "<LI><H4><A href='", partners_url, "'>Partners</A></H4></LI>"
               "</BODY></HTML>"]

        response.writelines(doc)


class Partners(BaseResource):

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IAgent(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")

        doc = ["<HTML><HEAD>",
               "<TITLE>F3AT Gateway</TITLE>",
               "</HEAD><BODY>",
               "<H2>Partners</H2>",
               "<TABLE>",
               "<TR><TH>Relation</TH><TH>Role</TH>"
               "<TH>Agent Id</TH><TH>Shard Id</TH></TR>"]

        for partner in self.model.iter_partners():
            partner_model = models.IPartner(partner)
            agent_url = "/agents/" + partner_model.agent_id
            partner_type = cgi.escape(partner_model.partner_type)
            doc.extend(["<TR>",
                        "<TD>", partner_type, "</TD>",
                        "<TD>", str(partner_model.role), "</TD>",
                        "<TD><A href='", agent_url, "'>",
                        partner_model.agent_id, "</A></TD>",
                        "<TD>", partner_model.shard_id, "</TD>",
                        "</TR>"])

        doc.extend(["</TABLE>",
                    "</BODY></HTML>"])

        response.writelines(doc)
