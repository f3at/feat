import os
import re
import glob
import ConfigParser
import StringIO
import sys

from feat import applications
from feat.common.text_helper import format_block
from feat.common import serialization, error
from feat.configure import configure


def parse_file(parser, fp):
    cfg = ConfigParser.RawConfigParser()
    cfg.readfp(fp)

    def ordering(section):
        if _is_static_section(section):
            return 1
        elif section.startswith('application:'):
            return 2
        elif section.startswith('agent:'):
            return 3
        elif section == "include":
            return 4
        else:
            return 0

    sections = sorted(cfg.sections(), key=ordering)
    for section in sections:
        if _is_static_section(section):
            _parse_static_section(cfg, parser, section)
        elif section.startswith('application:'):
            _parse_application_section(cfg, parser, section)
        elif section.startswith('agent:'):
            _parse_agent_section(cfg, parser, section)
        elif section == "include":
            _parse_include_section(cfg, parser, section)
        else:
            raise ConfigParser.Error('Unknown config file section %s' %
                                     (section, ))


def append_agent(parser, agent_type,
                 desc_keywords=dict(), initiate_keywords=dict(), name=None):
    desc_factory = serialization.lookup(agent_type)
    if not desc_factory:
        raise ConfigParser.Error("Unknown agent_type: %s" % (agent_type, ))
    desc = desc_factory(**desc_keywords)
    parser.values.agents.append((desc, initiate_keywords, name))


### private module methods ###


def _parse_static_section(cfg, parser, section):
    for name, value in cfg.items(section):
        target = _get_target(section, name)
        opt_str = '--' + target
        opt = parser.get_option(opt_str)
        if opt is None:
            raise ConfigParser.Error("This is a bug. Mapping gave us wrong "
                                     "target. Option name %s in section %s "
                                     "should match the option with abrev %s"
                                     % (name, section, target))
        if opt.action == 'append':
            values = value.split()
            for value in values:
                opt.process(opt_str, value, parser.values, parser)
        else:
            opt.process(opt_str, value, parser.values, parser)


def _parse_application_section(cfg, parser, section):
    '''
    Example of application section:
    [application:flt]
    import: flt.application
    name: flt
    # pythonpath is optional
    pythonpath: /etc/flt/python
    '''
    try:
        sys.path.append(cfg.get(section, 'pythonpath'))
    except ConfigParser.NoOptionError:
        pass

    module = cfg.get(section, 'import')
    name = cfg.get(section, 'name')
    try:
        applications.load(module, name)
    except ImportError as e:
        raise error.FeatError(
            "Loading application %s.%s failed, requested from section %s" %
            (module, name, section, ), cause=e)


def _parse_agent_section(cfg, parser, section):
    '''
    Example of agent section:
    [agent:dns_production]
    application: feat
    agent_type: dns_agent
    descriptor.some_integer: 5
    descriptor.some_string: "hello"
    initiate.suffix: "service.lan"
    initiate.array_of_strings: ["string1", "string2"]
    '''
    agent_type = cfg.get(section, 'agent_type')
    desc_keywords = dict()
    initiate_keywords = dict()
    for name, value in cfg.items(section):
        if name.startswith('descriptor'):
            key = name.split('.')[1]
            desc_keywords[key] = _unserialize_json_field(
                section, name, value)
        elif name.startswith('initiate'):
            key = name.split('.')[1]
            initiate_keywords[key] = _unserialize_json_field(
                section, name, value)
    name = section.split(':', 2)[1]
    append_agent(parser, agent_type, desc_keywords, initiate_keywords, name)


def _unserialize_json_field(section, key, value):
    try:
        return serialization.json.unserialize(value)
    except ValueError:
        raise ConfigParser.Error("Value: %r is not a valid json. Section=%s "
                                 "Key=%s" % (value, section, key))


def _parse_include_section(cfg, parser, section):
    '''
    Example of include section:
    [include]
    flt: /etc/feat/flt.ini
    ducksboard: /etc/feat/ducksboard.ini
    '''
    for _name, pattern in cfg.items(section):
        if not os.path.isabs(pattern):
            pattern = os.path.join(configure.confdir, pattern)
        matches = glob.glob(pattern)
        matches.sort()
        for filename in matches:
            f = open(filename, 'r')
            parse_file(parser, f)


def _is_static_section(section):
    targets = _target_config()
    return targets.has_section(section)


def _get_target(section, option):
    targets = _target_config()
    try:
        return targets.get(section, option)
    except ConfigParser.NoOptionError:
        # this is to handle multiple options combined into the lists
        # subsitute the string like monitor1 to monitor??
        new_option = re.sub(r'[0-9]*$', '??', option)
        if new_option == option:
            raise
        # may raise ConfigParser.NoOptionError, this is ok, let it fail
        return targets.get(section, new_option)


def _target_config():
    global _targets
    if not _targets:
        _targets = ConfigParser.RawConfigParser()
        _targets.readfp(StringIO.StringIO(_targets_ini))

    return _targets


_targets = None

# Config file below defines the binding between the command line options
# and the section/keys of the config files. This is not a full list,
# sections which are not included below (because they are dinamic) are:
# 'application:*', 'agent:*' and 'include'

_targets_ini = format_block("""
[agency]
journal: journal
unix: socket-path
rundir: rundir
logdir: logdir
lock: lock-path
hostname: hostname
domainname: domainname

[rabbitmq]
host: msghost
port: msgport
user: msguser
password: msgpass

[tunneling]
host: tunneling-host
port: tunneling-port
p12_path: tunnel-p12

[couchdb]
host: dbhost
port: dbport
name: dbname
username: dbusername
password: dbpassword
https: dbhttps

[manhole]
public_key: pubkey
private_key: privkey
authorized_keys: authorized
port: manhole

[gateway]
port: gateway-port
p12_path: gateway-p12
client_p12: gateway-client-p12

[host]:
document_id: host-def
resource: host-resource
ports: host-ports-ranges
category: host-category

[nagios]:
send_nsca: send-nsca-path
config_path: nsca-config-path
monitor??: nagios-monitor
host??: nagios-host
""")
