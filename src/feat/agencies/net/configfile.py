import sys
import ConfigParser
import StringIO

from feat.agents.base import descriptor
from feat.common.text_helper import format_block
from feat.common.serialization import json
from feat.common import reflect


def parse_file(parser, fp):
    cfg = ConfigParser.RawConfigParser()
    cfg.readfp(fp)
    # we to handle application:* sections before agent:* ones
    sections = sorted(cfg.sections(), reverse=True)
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
                 desc_keywords=dict(), initiate_keywords=dict()):
    desc_factory = descriptor.lookup(agent_type)
    if not desc_factory:
        raise ConfigParser.Error("Uknown agent_type: %s" % (agent_type, ))
    desc = desc_factory(**desc_keywords)
    parser.values.agents.append((desc, initiate_keywords))


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
    import: flt.everything
    '''
    #TODO: Create an Application object here which will manage loading
    #the modules and (in future) reloading them.
    module = cfg.get(section, 'import')
    try:
        reflect.named_module(module)
    except ImportError:
        raise (ConfigParser.Error(
            "Importing module %s failed, requested from section %s" %
            (module, section, )), None, sys.exc_info()[2])


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
            desc_keywords[key] = json.unserialize(value)
        elif name.startswith('initiate'):
            key = name.split('.')[1]
            initiate_keywords[key] = json.unserialize(value)
    append_agent(parser, agent_type, desc_keywords, initiate_keywords)


def _parse_include_section(cfg, parser, section):
    '''
    Example of include section:
    [include]
    flt: /etc/feat/flt.ini
    ducksboard: /etc/feat/ducksboard.ini
    '''
    for _name, filename in cfg.items(section):
        f = open(filename, 'r')
        parse_file(parser, f)


def _is_static_section(section):
    targets = _target_config()
    return targets.has_section(section)


def _get_target(section, option):
    targets = _target_config()
    # may raise ConfigParse.NoOptionError, this is ok, let it fail
    return targets.get(section, option)


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

[manhole]
public_key: pubkey
private_key: privkey
authorized_keys: authorized
port: manhole

[gateway]
port: gateway-port
p12_path: gateway-p12

[host]:
document_id: host-def
resource: host-resource
ports: host-ports-ranges
category: host-category""")
