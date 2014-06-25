import sys
import tempfile

from OpenSSL import SSL, crypto

from twisted.internet import ssl
from zope.interface import Interface, Attribute, implements

from feat.common import log

from feat.interface.security import SecurityError, IPeerInfo


### Interfaces ###


class ISecurityPolicy(Interface):

    use_ssl = Attribute("Specifies if the service must use SSL")

    def get_ssl_context_factory(self):
        """Returns an SSL context factory."""

    def get_peer_info(connection):
        """Return peer information from a connection."""


### Implementations ###


class PeerInfo(object):

    implements(IPeerInfo)

    @classmethod
    def from_certificate(cls, x509):
        subj = x509.get_subject()
        parts = [p.strip() for p in unicode(subj.commonName).split(",")]
        identity = parts[0]
        roles = parts[1:]
        email = subj.emailAddress
        return cls(identity, roles, email)

    def __init__(self, identity, roles=None, email=None):
        self._identity = unicode(identity)
        if roles:
            self._roles = set([str(r) for r in roles])
        else:
            self._roles = set()
        self._email = str(email)
        context = [self._identity]
        context.extend(self._roles)
        self._context = (u", ".join(context)).encode("utf8")

    def __repr__(self):
        l = [self._identity]
        l.extend(self._roles)
        return "<User %s>" % (self._context, )

    ### IPeerInfo ###

    @property
    def identity(self):
        return self._identity

    @property
    def email(self):
        return self._email

    @property
    def context(self):
        return self._context

    def has_role(self, role):
        return role in self._roles

    def iter_roles(self):
        return iter(self._roles)


class ContextCache(object):
    """Caches SSL context to be able to set it up and modify it
    only once at policy creation time."""

    def __init__(self, factory):
        self.__dict__["_factory"] = factory
        self.__dict__["_context"] = factory.getContext()

    def __getattr__(self, attr):
        return getattr(self._factory, attr)

    def __setattr__(self, attr, value):
        return setattr(self._factory, attr, value)

    def getContext(self):
        return self._context


class BaseContextFactory(object):

    """
    @type  enforce_cert: C{bool}
    @ivar  enforce_cert: whether to enforce the use of client certificates
    """

    def __init__(self,
                 key_filename=None,
                 cert_filename=None,
                 verify_ca_filename=None,
                 p12_filename=None,
                 verify_ca_from_p12=False,
                 key_pass=None, p12_pass=None,
                 enforce_cert=False):

        self._cert_filename = cert_filename
        self._key_filename = key_filename
        self._p12_filename = p12_filename
        self._verify_ca_filename = verify_ca_filename
        self._verify_ca_from_p12 = verify_ca_from_p12
        self._key_pass = key_pass
        self._p12_pass = p12_pass
        self._enforce_cert = enforce_cert

        log.debug("ssl-context",
            "Created BaseContextFactory, p12 %s, verify_ca_from_p12 %r",
            self._p12_filename,
            self._verify_ca_from_p12)

    def getContext(self):
        ctx = _create_ssl_context(self._key_filename,
                                  self._cert_filename,
                                  self._verify_ca_filename,
                                  self._p12_filename,
                                  self._verify_ca_from_p12,
                                  self._key_pass, self._p12_pass)

        if self._enforce_cert:
            log.debug("ssl-context", "getContext: setting VERIFY_PEER")
            log.debug("ssl-context",
                "getContext: setting VERIFY_FAIL_IF_NO_PEER_CERT")
            opts = SSL.VERIFY_PEER
            opts |= SSL.VERIFY_FAIL_IF_NO_PEER_CERT
            ctx.set_verify(opts, self._verify_callback)

            # Line below solves the problem of
            # "SSL_GET_PREV_SESSION:session id context uninitialized".
            # Citing the explaination from the mail archive of the openssl
            # group.
            ##
            # You need to set the session id context so that sessions which
            # use client authentication which are cached have the same
            # context id value. This is a security measure where servers
            # might have different security requirements for different
            # sessions to ensure that a client can't resume an inappropriate
            # session.
            #
            # What you set it to doesn't matter as long as it is set to
            # something.
            ctx.set_session_id('sessionid')

        return ctx

    ### private ###

    def _verify_callback(self, connection, x509, errnum, errdepth, ok):
        if not ok:
            log.warning("ssl-context", "Invalid certificate: %s",
                        x509.get_subject())
            return False
        return True


class ServerContextFactory(BaseContextFactory, ssl.ContextFactory):
    """A context factory for SSL servers."""

    def __init__(self,
                 key_filename=None,
                 cert_filename=None,
                 verify_ca_filename=None,
                 p12_filename=None,
                 verify_ca_from_p12=False,
                 key_pass=None, p12_pass=None,
                 enforce_cert=False):


        if p12_filename is None:
            if p12_pass:
                raise ValueError("PKCS12 passphrase specified "
                                 "without corresponding filename")
            if key_filename is None:
                if cert_filename is None:
                    raise ValueError("If no server PKCS12 is specified "
                                     "certificate AND private key "
                                     "must be specified")
        else:
            if key_filename is not None:
                if cert_filename is not None:
                    raise ValueError("If a PKCS12 is specified "
                                     "no certificate or private key "
                                     "must be specified")
            elif key_pass:
                raise ValueError("Private key passphrase specified "
                                 "without corresponding filename")

        if verify_ca_from_p12 and verify_ca_filename is not None:
            raise ValueError("If verifying CA from PKCS12 "
                             "no CA certification chain must be specified")

        BaseContextFactory.__init__(self,
                                    key_filename=key_filename,
                                    cert_filename=cert_filename,
                                    verify_ca_filename=verify_ca_filename,
                                    p12_filename=p12_filename,
                                    verify_ca_from_p12=verify_ca_from_p12,
                                    key_pass=key_pass, p12_pass=p12_pass,
                                    enforce_cert=enforce_cert)


class ClientContextFactory(BaseContextFactory, ssl.ClientContextFactory):
    """A context factory for SSL clients."""

    def __init__(self,
                 key_filename=None,
                 cert_filename=None,
                 verify_ca_filename=None,
                 p12_filename=None,
                 verify_ca_from_p12=False,
                 key_pass=None, p12_pass=None):

        if p12_filename is not None:
            if key_filename is not None or cert_filename is not None:
                raise ValueError("If a client PKCS12 is specified "
                                 "no certificate or private key "
                                 "must be specified")
        elif (key_filename is None) != (cert_filename is None):
                raise ValueError("Both client certificate and private key "
                                 "must be specified")

        if verify_ca_from_p12 and verify_ca_filename is not None:
            raise ValueError("If verifying CA from PKCS12 "
                             "no CA certification chain must be specified")

        BaseContextFactory.__init__(self,
                                    key_filename=key_filename,
                                    cert_filename=cert_filename,
                                    verify_ca_filename=verify_ca_filename,
                                    p12_filename=p12_filename,
                                    verify_ca_from_p12=verify_ca_from_p12,
                                    key_pass=key_pass, p12_pass=p12_pass)


class UnsecuredPolicy(object):

    implements(ISecurityPolicy)

    ### ISecurityPolicy Methods ###

    @property
    def use_ssl(self):
        return False

    def get_peer_info(self, connection):
        return None

    def get_ssl_context_factory(self):
        return None


class ServerPolicy(object):

    implements(ISecurityPolicy)

    _factory = None

    def __init__(self, context_factory=None, default_info=None):
        if context_factory is not None:
            if context_factory.isClient:
                raise ValueError("Server security policy needs a server "
                                 "SSL context factory")
            self._factory = ContextCache(context_factory)
            if default_info is not None:
                self._default_info = IPeerInfo(default_info)
            else:
                self._default_info = None

    ### ISecurityPolicy Methods ###

    @property
    def use_ssl(self):
        return self._factory is not None

    def get_peer_info(self, connection):
        if self._factory:
            x509 = connection.getPeerCertificate()
            if x509:
                return PeerInfo.from_certificate(x509)
        return self._default_info

    def get_ssl_context_factory(self):
        return self._factory


class ClientPolicy(object):

    implements(ISecurityPolicy)

    _factory = None

    def __init__(self, context_factory):
        if context_factory is not None:
            if not context_factory.isClient:
                raise ValueError("Client security policy needs a client "
                                 "SSL context factory")
            self._factory = ContextCache(context_factory)

    ### ISecurityPolicy Methods ###

    @property
    def use_ssl(self):
        return self._factory is not None

    def get_peer_info(self, connection):
        return None

    def get_ssl_context_factory(self):
        return self._factory


### Utility Functions ###


def ensure_policy(policy):
    if policy is None:
        return UnsecuredPolicy()
    return ISecurityPolicy(policy)


def write_certificates(file_or_filename, *certs):

    def write_to(f):
        for cert in certs:
            f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
            f.write("\n")

    if isinstance(file_or_filename, (str, unicode)):
        with open(file_or_filename, "wb") as f:
            write_to(f)
    else:
        write_to(file_or_filename)

    return file_or_filename


### private ###


def _create_ssl_context(key_filename=None,
                        cert_filename=None,
                        verify_ca_filename=None,
                        p12_filename=None,
                        verify_ca_from_p12=False,
                        key_pass=None, p12_pass=None):
    """
    @param verify_ca_from_p12: for a server, setting this to true will present
                               the full CA chain's certificates stored in
                               the .p12
    @type  verify_ca_from_p12: C{bool}
    """

    ctx = SSL.Context(SSL.SSLv23_METHOD)

    if p12_filename is not None:

        with open(p12_filename) as f:
            try:
                p12 = crypto.load_pkcs12(f.read(), p12_pass or "")
            except crypto.Error as e:
                raise SecurityError("Invalid PKCS12 or passphrase for %s: %s"
                                    % (p12_filename, e), cause=e), \
                      None, sys.exc_info()[2]

            ctx.use_certificate(p12.get_certificate())
            ctx.use_privatekey(p12.get_privatekey())
            if verify_ca_from_p12:
                #FIXME: is there no way to set the chain directly ?
                with tempfile.NamedTemporaryFile() as f:
                    certs = p12.get_ca_certificates()
                    write_certificates(f, *certs)
                    f.flush()
                    ctx.load_verify_locations(f.name)

    elif cert_filename is not None and key_filename is not None:

        try:
            with open(cert_filename) as f:
                ft = crypto.FILETYPE_PEM
                cert = crypto.load_certificate(ft, f.read())
        except IOError as e:
            raise SecurityError("Certificate file access error for %s: %s"
                                % (cert_filename, e), cause=e), \
                  None, sys.exc_info()[2]
        except crypto.Error as e:
            raise SecurityError("Invalid certificate %s: %s"
                                % (cert_filename, e), cause=e), \
                  None, sys.exc_info()[2]

        try:
            with open(key_filename) as f:
                ft = crypto.FILETYPE_PEM
                key = crypto.load_privatekey(ft, f.read(), key_pass or "")
        except IOError as e:
            raise SecurityError("Private key file error for %s: %s"
                                % (cert_filename, e), cause=e), \
                  None, sys.exc_info()[2]
        except crypto.Error as e:
            raise SecurityError("Invalid private key or passphrase for %s: %s"
                                % (key_filename, e), cause=e), \
                  None, sys.exc_info()[2]

        ctx.use_certificate(cert)
        ctx.use_privatekey(key)

        try:
            ctx.check_privatekey()
        except crypto.Error as e:
            raise SecurityError("Certificate and private key files do not "
                                "match; certificate: %s; private key: %s"
                                % (cert_filename, key_filename, ), cause=e), \
                  None, sys.exc_info()[2]

    if not verify_ca_from_p12 and verify_ca_filename is not None:
        ctx.load_verify_locations(verify_ca_filename)

    return ctx
