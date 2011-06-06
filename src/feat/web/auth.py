import weakref

from zope.interface import Interface, Attribute, implements

from feat.web import http


### Interfaces ###


class IHTTPChallenge(Interface):

    method_name = Attribute("")
    header_value = Attribute("")


class IBasicHTTPChallenge(IHTTPChallenge):

    realm_name = Attribute("")


class IHTTPCredentials(Interface):

    method_name = Attribute("")
    header_value = Attribute("")
    username = Attribute("")

    def __hash__():
        """Hash function."""

    def __eq__(other):
        """Equality operator."""

    def __ne__(other):
        """Non equality operator."""


class IBasicHTTPCredentials(IHTTPCredentials):

    password = Attribute("")


class IAuthenticator(Interface):

    def authenticate(request, credentials, location):
        """
        Returns a http.IHTTPCredentials instance if authenticated,
        a http.IHTTPChallenge instance if authentication is needed,
        None if no authentication is needed.
        May returns a Deferred fired with the equivalent values.
        """


class IAuthorizer(Interface):

    def authorize(request, credentials, location):
        """
        Returns true if authorized or false otherwise.
        May returns a Deferred with the equivalent values.
        """


### Classes ###


class BasicHTTPChallenge(object):

    implements(IBasicHTTPChallenge)

    def __init__(self, realm):
        self._realm = realm

    ### IHTTPChallenge ###

    @property
    def method_name(self):
        return "Basic"

    @property
    def header_value(self):
        #FIXME: Need some way of escaping characters '"'
        return 'Basic realm="%s"' % self._realm

    ### IBasicHTTPChallenge ###

    @property
    def realm_name(self):
        return self._realm


class BasicHTTPCredentials(object):

    implements(IBasicHTTPCredentials)

    @classmethod
    def from_header_value(cls, header):
        parts = header.lstrip().split(None, 1)
        method = parts[0].lower()
        if method != "basic":
            #FIXME: Better handling of invalid authentication method.
            #       Maybe returning again a 401, but with witch realm name ?
            raise http.InternalServerError("Invalid Authentication Method '%s'"
                                           % method)
        if len(parts) < 2:
            raise http.InternalServerError("Invalid Authentication Data")
        decoded = parts[1].strip().decode("base64")
        username, password = decoded.split(':', 1)
        return cls(username, password)

    def __init__(self, username, password):
        self._username = username
        self._password = password


    ### IHTTPCredentials ###

    @property
    def method_name(self):
        return "Basic"

    @property
    def header_value(self):
        creds = "%s:%s" % (self._username, self._password)
        return "Basic %s" % creds.encode("base64")

    @property
    def username(self):
        return self._username

    def __hash__(self):
        return hash(self._username) ^ hash(self._password)

    def __eq__(self, other):
        if not isinstance(other, BasicHTTPCredentials):
            return NotImplemented
        return (self._username == other._username
                and self._password == other._password)

    def __ne__(self, other):
        if not isinstance(other, BasicHTTPCredentials):
            return NotImplemented
        return (self._username != other._username
                or self._password != other._password)

    ### IBasicHTTPCredentials ###

    @property
    def password(self):
        return self._password


class BaseAuthenticator(object):

    def __init__(self):
        self._credentials = weakref.WeakKeyDictionary()

    ### protected ###

    def is_authenticated(self, credentials):
        return (IBasicHTTPCredentials.providedBy(credentials)
                and IBasicHTTPCredentials(credentials) in self._credentials)

    def _add_authenticated(self, credentials):
        self._credentials[IBasicHTTPCredentials(credentials)] = True


class BasicAuthenticator(BaseAuthenticator):

    implements(IAuthenticator)

    def __init__(self, realm, users):
        BaseAuthenticator.__init__(self)
        self._users = users
        self._challenge = BasicHTTPChallenge(realm)

    ### IAuthenticator ###

    def authenticate(self, request, credentials, location):
        if self.is_authenticated(credentials):
            return credentials

        if not IBasicHTTPCredentials.providedBy(credentials):
            return self._challenge

        credentials = IBasicHTTPCredentials(credentials)
        username = credentials.username
        password = credentials.password

        if username not in self._users:
            return self._challenge

        if self._users[username] != password:
            return self._challenge

        self._add_authenticated(credentials)

        return credentials
