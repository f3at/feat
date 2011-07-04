#!/usr/bin/python2.6
import tempfile
import os
import optparse
import sys

from feat import everything
from feat.agents.base import descriptor
from feat.agents.common import host
from feat.agencies.net import agency as net_agency, standalone
from feat.common import log, run, defer, reflect
from feat.common.serialization import json
from feat.interface.agent import Access, Address, Storage

from twisted.internet import reactor


def parse_config_file(option, opt_str, value, parser):
    import ConfigParser
    try:
        cfg = ConfigParser.ConfigParser()
        cfg.readfp(open(value, 'r'))
        for dest, value in cfg.items('Feat'):
            values = value.split()
            opt = parser.get_option('--'+dest)
            if not opt:
                raise OptionError("Invalid option %s defined in"
                                  "config file" % dest)
            for value in values:
                opt.process(opt_str, value, parser.values, parser)
    except IOError:
        print 'Config file not found, skipping ...'


def _load_module(option, opt, value, parser):
    try:
        reflect.named_module(value)
    except ImportError:
        raise OptionError("Unknown module %s" % value)


def add_options(parser):
    parser.add_option('-d', '--debug',
                      action="store", type="string", dest="debug",
                      help="Set debug levels.")
    parser.add_option('-i', '--import', help='import specified module',
                      action='callback', callback=_load_module,
                      type="str", metavar="MODULE")
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
    parser.add_option('-z', '--host-ports-ranges', dest="hostports",
                      help="Add available port ranges by groups to the "
                      "host agent. Format: GROUP_NAME:PORT_MIN:PORT_MAX. "
                      "Example: 'worker:1000:2000'.",
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
    parser.add_option('-X', '--standalone',
                      action="store_true", dest="standalone",
                      help="run agent in standalone agency (default: False)",
                      default=False)
    parser.add_option('--kwargs',
                      action="store", dest="standalone_kwargs",
                      help="serialized kwargs to pass to standalone agent",
                      default=None)


def check_options(opts, args):
    if opts.hostdef and (opts.hostres or opts.hostcat):
        raise OptionError("Host resources or categories cannot be "
                          "specified when specifyin"
                          "a host definition document.")

    if opts.standalone and len(opts.agents) != 1:
        raise OptionError("Running standalone agency requires passing "
                          "run host_id with --agent option.")

    if opts.standalone_kwargs:
        if not opts.standalone:
            raise OptionError("Passing kwargs for standalone makes sense"
                              " only combined with --standalone option.")

        try:
            opts.standalone_kwargs = json.unserialize(
                opts.standalone_kwargs)
        except TypeError:
            raise OptionError("Error unserializing json dictionary: %s " %
                              opts.standalone_kwargs)


    if args:
        raise OptionError("Unexpected arguments: %r" % args)

    return opts, args


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
    raise OptionError("Invalid host category: %s" % catdef)


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
    net_agency.add_options(parser)

    with _Bootstrap(parser=parser, args=args) as bootstrap:
        agency = bootstrap.agency
        opts = bootstrap.opts
        args = bootstrap.args
        opts, args = check_options(opts, args)

        descriptors = descriptors or []
        for name in opts.agents:
            factory = descriptor.lookup(name)
            if factory is None:
                msg = "No descriptor factory found for agent %s" % name
                raise run.OptionError(msg)
            descriptors.append(factory())

        if opts.hostres or opts.hostcat or opts.hostports:
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

            ports_ranges = []
            for ports in opts.hostports:
                group, start, stop = tuple(ports.split(":"))
                ports_ranges.append((group, int(start), int(stop)))
            hostdef.ports_ranges = ports_ranges

        agency.set_host_def(hostdef)
        d = agency.initiate()

        if not opts.standalone:
            # specific to running normal agency
            for name in opts.agents:
                factory = descriptor.lookup(name)
                if factory is None:
                    msg = "No descriptor factory found for agent %s" % name
                    raise OptionError(msg)
                descriptors.append(factory())

            hostdef = opts.hostdef
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
                            raise OptionError("Invalid host resource: %s"
                                              % resdef)
                    hostdef.resources[name] = value

                for catdef in opts.hostcat:
                    name, value = check_category(catdef)
                    hostdef.categories[name] = value

            agency.set_host_def(hostdef)

            for desc in descriptors:
                log.debug("feat", "Starting agent with descriptor %r", desc)
                d.addCallback(defer.drop_param, agency.spawn_agent, desc)
        else:
            # standalone specific
            kwargs = opts.standalone_kwargs or dict()
            d.addCallback(defer.drop_param, agency.spawn_agent,
                          opts.agents[0], **kwargs)
        return d


class OptionError(Exception):
    pass


class _Bootstrap(object):

    def __init__(self, parser=None, args=None):
        self._parser = parser
        self.args = args
        self.opts = None
        self.agency = None

    def __enter__(self):
        log.FluLogKeeper.init()
        self._parse_opts()
        if self.opts.debug:
            log.FluLogKeeper.set_debug(self.opts.debug)
        if self.opts.agency_daemonize:
            tmp = tempfile.mktemp(suffix="feat.temp.log")
            run.daemonize(stdout=tmp, stderr=tmp)
        self.agency = self._run_agency()
        return self

    def __exit__(self, type, value, traceback):
        if type is not None:
            if issubclass(type, OptionError):
                print >> sys.stderr, "ERROR: %s" % str(value)
                return True
            return

        reactor.run()

    def _parse_opts(self):
        self.opts, self.args = self._parser.parse_args(args=self.args)

    def _run_agency(self):
        if self.opts.standalone:
            cls = standalone.Agency
        else:
            cls = net_agency.Agency
        a = cls.from_config(os.environ, self.opts)
        return a
