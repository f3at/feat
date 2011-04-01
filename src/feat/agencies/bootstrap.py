#!/usr/bin/python2.6

import optparse

from feat import everything
from feat.agents.base import descriptor
from feat.agents.common import host
from feat.common import log, run, defer


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


def check_options(opts, args):
    if opts.hostdef and opts.hostres:
        raise run.OptionError("Host resources cannot be specified when "
                              "specifying a host definition document.")
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

        if opts.hostres:
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

        conn = run.get_db_connection(agency)

        d = defer.succeed(None)

        # Starting the host agent
        host_desc = everything.host_agent.Descriptor(shard=u'lobby')
        host_kwargs = dict(bootstrap=True, hostdef=hostdef)
        d.addCallback(defer.drop_result, conn.save_document, host_desc)
        d.addCallbacks(agency.start_agent, agency._error_handler,
                       callbackKeywords=host_kwargs)

        # Starting the other agents

        for desc in descriptors:
            log.debug("feat", "Starting agent with descriptor %r", desc)
            d.addCallback(start_agent, desc)

        return d
