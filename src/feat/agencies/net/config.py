import optparse
import os
import re
import socket

from feat.common import formatable, log
from feat.common.serialization import json, register
from feat.agencies.net import options, configfile

from feat.configure import configure


def parse_service_config():
    parser = optparse.OptionParser()
    options.add_options(parser)
    opts, args = parser.parse_args([])
    feat_ini = os.path.join(configure.confdir, 'feat.ini')
    local_ini = os.path.join(configure.confdir, 'local.ini')
    with open(feat_ini, 'r') as f:
        configfile.parse_file(parser, f)
    if os.path.exists(local_ini):
        with open(local_ini, 'r') as f:
            configfile.parse_file(parser, f)

    c = Config()
    c.load(os.environ, opts)
    return c


@register
class MsgConfig(formatable.Formatable):

    formatable.field('host', options.DEFAULT_MSG_HOST)
    formatable.field('port', options.DEFAULT_MSG_PORT)
    formatable.field('user', options.DEFAULT_MSG_USER)
    formatable.field('password', options.DEFAULT_MSG_PASSWORD)


@register
class DbConfig(formatable.Formatable):

    formatable.field('host', options.DEFAULT_DB_HOST)
    formatable.field('port', options.DEFAULT_DB_PORT)
    formatable.field('name', options.DEFAULT_DB_NAME)
    formatable.field('username', None)
    formatable.field('password', None)
    formatable.field('https', False)


@register
class ManholeConfig(formatable.Formatable):

    formatable.field('public_key', options.DEFAULT_MH_PUBKEY)
    formatable.field('private_key', options.DEFAULT_MH_PRIVKEY)
    formatable.field('authorized_keys', options.DEFAULT_MH_AUTH)
    formatable.field('port', options.DEFAULT_MH_PORT)


@register
class AgencyConfig(formatable.Formatable):

    formatable.field('journal', [options.DEFAULT_JOURFILE])
    formatable.field('socket_path', options.DEFAULT_SOCKET_PATH)
    formatable.field('lock_path', options.DEFAULT_LOCK_PATH)
    formatable.field('rundir', options.DEFAULT_RUNDIR)
    formatable.field('logdir', options.DEFAULT_LOGDIR)
    formatable.field('enable_spawning_slave',
                     options.DEFAULT_ENABLE_SPAWNING_SLAVE)
    formatable.field('daemonize', options.DEFAULT_DAEMONIZE)
    formatable.field('hostname', None)
    formatable.field('domainname', None)

    @property
    def full_hostname(self):
        if not hasattr(self, '_full_hostname'):
            if self.hostname is None:
                self._full_hostname = socket.gethostname()
            else:
                self._full_hostname = self.hostname
            if self.domainname is not None:
                self._full_hostname = ".".join(
                    [self._full_hostname, self.domainname])
            else:
                self._full_hostname = socket.getfqdn(self._full_hostname)
        return self._full_hostname


@register
class GatewayConfig(formatable.Formatable):

    formatable.field('port', options.DEFAULT_GW_PORT)
    formatable.field('p12', options.DEFAULT_GW_P12_FILE)
    formatable.field('client_p12', None)
    formatable.field('allow_tcp', options.DEFAULT_ALLOW_TCP_GATEWAY)


@register
class TunnelConfig(formatable.Formatable):

    formatable.field('host', None)
    formatable.field('port', options.DEFAULT_TUNNEL_PORT)
    formatable.field('p12', options.DEFAULT_TUNNEL_P12_FILE)


@register
class NagiosConfig(formatable.Formatable):

    formatable.field('send_nsca', options.DEFAULT_SEND_NSCA_PATH)
    formatable.field('config_file', options.DEFAULT_NSCA_CONFIG_PATH)
    formatable.field('monitors', list())
    formatable.field('hosts', list())


@register
class Config(formatable.Formatable, log.Logger):

    log_category = 'config'

    formatable.field('msg', MsgConfig())
    formatable.field('db', DbConfig())
    formatable.field('manhole', ManholeConfig())
    formatable.field('agency', AgencyConfig())
    formatable.field('gateway', GatewayConfig())
    formatable.field('tunnel', TunnelConfig())
    formatable.field('nagios', NagiosConfig())

    def __init__(self, **kwargs):
        log.Logger.__init__(self, log.get_default())
        formatable.Formatable.__init__(self, **kwargs)

    def load(self, env, options=None):
        '''
        Loads config from environment.
        Environment values can be overridden by specified options.
        '''
        # First load from env
        matcher = re.compile('\AFEAT_([^_]+)_(.+)\Z')
        for key in env:
            res = matcher.search(key)
            if res:
                c_key = res.group(1).lower()
                c_kkey = res.group(2).lower()
                if not hasattr(self, c_key):
                    continue
                try:
                    value = json.unserialize(env[key])
                except ValueError:
                    self.error("Environment variable does not unserialize"
                               "to json. Variable: %s, Value: %s",
                               key, env[key])
                else:
                    self.log("Setting %s.%s to %r", c_key, c_kkey, value)
                    setattr(getattr(self, c_key), c_kkey, value)

        #Then override with options
        if options:
            # for group_key, conf_group in self.config.items():
            for field in self._fields:
                conf_group = getattr(self, field.name)
                for group_field in conf_group._fields:
                    attr = "%s_%s" % (field.name, group_field.name)
                    if hasattr(options, attr):
                        new_value = getattr(options, attr)
                        old_value = getattr(conf_group, group_field.name)
                        if new_value is not None and (old_value != new_value):
                            if old_value is None:
                                self.log("Setting %s.%s to %r",
                                         field.name, group_field.name,
                                         new_value)
                            else:
                                self.log("Overriding %s.%s to %r",
                                         field.name, group_field.name,
                                         new_value)
                            setattr(conf_group, group_field.name, new_value)

        #set default for tunnel host
        if self.tunnel.host is None:
            self.tunnel.host = self.agency.full_hostname

        _absolutize_path(self.agency, 'socket_path', self.agency.rundir)
        _absolutize_path(self.agency, 'lock_path', self.agency.rundir)

    def store(self, env):
        '''
        Stores agency config into environment to be read by the
        standalone agency.'''
        serializer = json.Serializer(force_unicode=True)
        for field1 in self._fields:
            for field2 in getattr(self, field1.name)._fields:
                var_name = "FEAT_%s_%s" % (field1.name.upper(),
                                           field2.name.upper())
                value = getattr(getattr(self, field1.name), field2.name)
                env[var_name] = serializer.convert(value)


def _absolutize_path(obj, key, base, none_ok=False):
    path = getattr(obj, key)
    if path is None:
        if none_ok:
            return
        else:
            raise ValueError("%s of object %r cannot be None" % (key, obj))
    if os.path.isabs(path):
        return
    path = os.path.join(base, path)
    setattr(obj, key, path)
