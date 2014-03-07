import json
import urlparse

from feat.common import log, defer, error
from feat.web import httpclient, http


class Client(log.Logger, log.LogProxy):

    def __init__(self, security_policy=None, logger=None):
        log.Logger.__init__(self, logger)
        log.LogProxy.__init__(self, logger)
        self.security_policy = security_policy
        # (host, port) -> httpclient.Connection
        self.connections = dict()

    def get_connection(self, host, port):
        if (host, port) not in self.connections:
            self.connections[(host, port)] = httpclient.Connection(
                host, port, security_policy=self.security_policy, logger=self)
        return self.connections[(host, port)]

    def disconnect(self):
        for x in self.connections.itervalues():
            x.disconnect()
        self.connections.clear()

    def get(self, host, port, location):
        return self.request(http.Methods.GET, host, port, location)

    def post(self, host, port, location, **params):
        return self.request(http.Methods.POST, host, port, location, **params)

    def put(self, host, port, location, **params):
        return self.request(http.Methods.PUT, host, port, location, **params)

    def delete(self, host, port, location):
        return self.request(http.Methods.DELETE, host, port, location)

    @defer.inlineCallbacks
    def request(self, method, host, port, location, **params):
        headers = {'content-type': 'application/json',
                   'accept': ['application/json', '*; q=0.6']}
        if params:
            body = json.dumps(params)
        else:
            body = None
        visited = list()
        while True:
            if (host, port, location) in visited:
                raise error.FeatError("Redirect loop detected for locations: "
                                      "%r" % (visited, ))
            connection = self.get_connection(host, port)
            response = yield connection.request(
                method, location, headers, body)
            if response.status == 301:
                visited.append((host, port, location))
                url = urlparse.urlparse(response.headers['location'])
                host = url.netloc.split(':')[0]
                port = url.port
                location = url.path
                if url.query:
                    location += '?' + url.query
            else:
                if response.headers['content-type'] == 'application/json':
                    try:
                        parsed = json.loads(response.body)
                    except ValueError:
                        self.error(
                            "Failed to parse: %s, headers: %s, status: %s",
                            response.body, response.headers,
                            response.status.name)
                        raise
                    else:
                        defer.returnValue((response.status, parsed))


                else:
                    defer.returnValue((response.status, response.body))
