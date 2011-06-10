#!/usr/bin/python2.6
import operator
import optparse

from feat import everything
from feat.agents.base import descriptor
from feat.agents.common import host
from feat.common import log, run
from feat.interface.agent import (Access, Address, Storage,
                                 AgencyAgentState, )


def parse_config_file(option, opt_str, value, parser):
    import ConfigParser
    try:
        cfg = ConfigParser.ConfigParser()
        cfg.readfp(open(value, 'r'))
        for dest, value in cfg.items('Feat'):
            values = value.split()
            opt = parser.get_option('--'+dest)
            if not opt:
                raise run.OptionError("Invalid option %s defined in"
                                      "config file" % dest)
            for value in values:
                opt.process(opt_str, value, parser.values, parser)
    except IOError:
        print 'Config file not found, skipping ...'


def add_options(parser):
    parser.add_option('-a', '--agent', dest="agents", action="append",
                      help="Start an agent of specified type.",
                      metavar="AGENT_NAME", default=[])
    parser.add_option('-t', '--host-def', dest="hostdef",
                      help="Host definition document identifier.",
                      metavar="HOST_DEF_ID", default=None)
    parser.add_option('-r', '--host-resource', dest="hostres",
                      help="Add a resource to the host agent. "
                           "Format: RES_NAME:RES_MAX. Example: 'epu:42'.",
                      metavar="HOST_DEF_ID", action="append", default=[])
    parser.add_option('-g', '--host-category', dest="hostcat",
                    help="Add a category to the host agent. "
                         "Format: CAT_NAME:CAT_VALUE.",
                    metavar="HOST_DEF_ID", action="append", default=[])
    parser.add_option('-C', '--config-file', action='callback',
                      help="Config file, the configuration loaded from the \
                      configuration file will overwrite other \
                      parameters defined",
                      callback=parse_config_file, nargs=1,
                      type="string", dest='config_file')


def check_options(opts, args):
    if opts.hostdef and (opts.hostres or opts.hostcat):
        raise run.OptionError("Host resources or categories cannot be "
                              "specified when specifyin"
                              "a host definition document.")
    if args:
        raise run.OptionError("Unexpected arguments: %r" % args)

    return opts, args


def start_agent(host_medium, desc, *args, **kwargs):
    agent = host_medium.get_agent()
    d = host_medium.save_document(desc)
    d.addCallback(
        lambda desc: agent.start_agent(desc.doc_id, *args, **kwargs))
    d.addErrback(host_medium.agency._error_handler)
    d.addCallback(lambda _: host_medium)
    return d


def check_category(catdef):
    parts = catdef.split(":", 1)
    name = parts[0].lower()
    value = 'none'
    if len(parts) > 1:
        value = parts[1].lower()

    if name == 'access' and value in Access.values():
        return name, Access.get(value)
    if name == 'address' and value in Address.values():
        return name, Address.get(value)
    if name == 'storage' and value in Storage.values():
        return name, Storage.get(value)
    raise run.OptionError("Invalid host category: %s" % catdef)


def bootstrap(parser=None, args=None, descriptors=None):
    """Bootstrap a feat process, handling command line arguments.
    @param parser: the option parser to use; more options will be
                   added to the parser; if not specified or None
                   a new one will be created
    @type  parser: optparse.OptionParser or None
    @param args: the command line arguments to parse; if not specified
                 or None, sys.argv[1:] will be used
    @type  args: [str()] or None
    @param descriptors: the descriptors of the agent to starts in addition
                        of the host agent; if not specified or None
                        no additional agents will be started
    @type  descriptors: [Descriptor()] or None
    @return: the deferred of the bootstrap chain
    @rtype:  defer.Deferred()"""

    parser = parser or optparse.OptionParser()
    add_options(parser)

    with run.bootstrap(parser=parser, args=args) as bootstrap:
        agency = bootstrap.agency
        opts = bootstrap.opts
        args = bootstrap.args
        descriptors = descriptors or []
        hostdef = opts.hostdef

        # Checking options
        opts, args = check_options(opts, args)
        for name in opts.agents:
            factory = descriptor.lookup(name)
            if factory is None:
                msg = "No descriptor factory found for agent %s" % name
                raise run.OptionError(msg)
            descriptors.append(factory())

        if opts.hostres or opts.hostcat:
            hostdef = host.HostDef()
            for resdef in opts.hostres:
                parts = resdef.split(":", 1)
                name = parts[0]
                value = 1
                if len(parts) > 1:
                    try:
                        value = int(parts[1])
                    except ValueError:
                        raise run.OptionError("Invalid host resource: %s"
                                              % resdef)
                hostdef.resources[name] = value

            for catdef in opts.hostcat:
                name, value = check_category(catdef)
                hostdef.categories[name] = value

        d = agency.initiate()
        d.addCallback(run.get_db_connection)

        # Starting the host agent
        host_desc = everything.host_agent.Descriptor(shard=u'lobby')
        host_kwargs = dict(hostdef=hostdef)
        d.addCallback(operator.methodcaller('save_document', host_desc))
        d.addCallbacks(agency.start_agent, agency._error_handler,
                       callbackKeywords=host_kwargs)
        d.addCallback(lambda medium:
                      medium.wait_for_state(AgencyAgentState.ready))
        # Starting the other agents

        for desc in descriptors:
            log.debug("feat", "Starting agent with descriptor %r", desc)
            d.addCallback(start_agent, desc)

        return d
