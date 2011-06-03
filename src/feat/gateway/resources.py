from feat.gateway import models
from feat.web import http, webserver


class BaseResource(webserver.BasicResource):
    pass


class Root(BaseResource):

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IRoot(model)
        self["agencies"] = Agencies(model)
        self["agents"] = Agents(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")
        return ("<HTML><HEAD><TITLE>F3AT Gateway</TITLE></HEAD><BODY>"
                "<H1>F3EAT Gateway</H1><UL>"
                "<LI><H2><A href='agencies'>Agencies</A></H2></LI>"
                "<LI><H2><A href='agents'>Agents</A></H2></LI>"
                "</UL></BODY></HTML>")

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
        # Force mime-type to html
        response.set_mime_type("text/html")
        response.write("<HTML><HEAD><TITLE>F3AT Gateway</TITLE></HEAD><BODY>")
        response.write("<H1>Agencies</H1><TABLE border='1'>")
        response.write("<TR><TH>Identifier</TH><TH>Role</TH></TR>")
        for agency in self.model.iter_agencies():
            agency_model = models.IAgency(agency)
            response.write("<TR><TD><A href='agencies/")
            response.write(agency_model.agency_id)
            response.write("'>")
            response.write(agency_model.agency_id)
            response.write("</TD><TD>")
            response.write(agency.role.name)
            response.write("</TD></TR>")
        response.write("</TABLE></BODY></HTML>")

    ### private ###

    def _agency_located(self, result, request, location, remaining):
        if result is None:
            return None
        host, port, _is_local = result
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
        response.write("<HTML><HEAD><TITLE>F3AT Gateway</TITLE></HEAD><BODY>")
        response.write("<H1>Agents</H1><TABLE border='1'>")
        response.write("<TR><TH>Identifier</TH>")
        response.write("<TH>Instance</TH><TH>Type</TH></TR>")
        for agent in self.model.iter_agents():
            agent_model = models.IAgent(agent)
            response.write("<TR><TD><A href='agents/")
            response.write(agent_model.agent_id)
            response.write("'>")
            response.write(agent_model.agent_id)
            response.write("</TD><TD>")
            response.write(str(agent_model.instance_id))
            response.write("</TD><TD>")
            response.write(agent_model.agent_type)
            response.write("</TD></TR>")
        response.write("</TABLE></BODY></HTML>")

    ### private ###

    def _agent_located(self, result, request, location, remaining):
        if result is None:
            return None
        host, port, _is_local = result
        url = http.compose(request.path, host=host, port=port)
        raise http.MovedPermanently(location=url)


class Agency(BaseResource):

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IAgency(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")
        response.write("<HTML><HEAD><TITLE>F3AT Gateway</TITLE></HEAD><BODY>")
        response.write("<H1>Agency ")
        response.write(self.model.agency_id)
        response.write("</H1></BODY></HTML>")


class Agent(BaseResource):

    def __init__(self, model):
        BaseResource.__init__(self)
        self.model = models.IAgent(model)

    def render_resource(self, request, response, location):
        # Force mime-type to html
        response.set_mime_type("text/html")
        response.write("<HTML><HEAD><TITLE>F3AT Gateway</TITLE></HEAD><BODY>")
        response.write("<H1>Agent ")
        response.write(self.model.agent_id)
        response.write(" ")
        response.write(self.model.agent_type)
        response.write("</H1></BODY></HTML>")
