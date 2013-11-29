# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
import os
import optparse
import sys

from feat.agencies.net import agency as net_agency, standalone
from feat.agencies.net import options, config as config_module
from feat.agencies.net.options import OptionError

from feat.common import log, defer, resolver, error
from feat.common.serialization import json
from feat.interface.agent import Access, Address, Storage

from twisted.internet import reactor

from feat import applications


def check_options(opts, args):
    if opts.hostdef and (opts.hostres or opts.hostcat):
        raise OptionError("Host resources or categories cannot be "
                          "specified when specifyin"
                          "a host definition document.")

    if (opts.standalone and not
        ((len(opts.agents) == 1 and opts.agent_id is None) or
         (len(opts.agents) == 0 and opts.agent_id is not None))):
        raise OptionError("Running standalone agent requires passing the "
                          "information about what agent to run. You can "
                          "either specify one '--agent AGENT_TYPE' paremeter "
                          "or '--agent-id AGENT_ID'")

    if opts.agent_id and not opts.standalone:
        raise OptionError("--agent-id options should only be used for "
                          "the standalone agent.")

    if opts.standalone_kwargs:
        if not opts.standalone:
            raise OptionError("Passing kwargs for standalone makes sense"
                              " only combined with --standalone option.")

        try:
            opts.standalone_kwargs = json.unserialize(
                opts.standalone_kwargs)
        except (TypeError, ValueError):
            raise OptionError("Error unserializing json dictionary: %s " %
                              opts.standalone_kwargs), None, sys.exc_info()[2]

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


_exit_code = 0


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

    tee = log.init()
    # The purpose of having log buffer here, is to be able to dump the
    # log lines to a journal after establishing connection with it.
    # This is done in stage_configure() of net agency Startup procedure.
    tee.add_keeper('buffer', log.LogBuffer(limit=10000))

    # use the resolver from twisted.names instead of the default
    # the reason for this is that ThreadedResolver behaves strangely
    # after the reconnection - raises the DNSLookupError for names
    # which have been resolved while there was no connection
    resolver.installResolver(reactor)

    if parser is None:
        parser = optparse.OptionParser()
        options.add_options(parser)
    try:
        opts, args = check_options(*parser.parse_args(args))
    except Exception as e:
        error.handle_exception('bootstrap', e, "Failed parsing config")
        sys.exit(1)

    if opts.standalone:
        cls = standalone.Agency
    else:
        cls = net_agency.Agency
    config = config_module.Config()
    config.load(os.environ, opts)
    agency = cls(config)

    applications.load('feat.agents.application', 'feat')
    applications.load('feat.gateway.application', 'featmodels')

    d = defer.Deferred()
    reactor.callWhenRunning(d.callback, None)

    if not opts.standalone:
        # specific to running normal agency

        hostdef = opts.hostdef

        if opts.hostres or opts.hostcat or opts.hostports:
            from feat.agents.common import host
            hostdef = host.HostDef()
            for resdef in opts.hostres:
                parts = resdef.split(":", 1)
                name = parts[0]
                value = 1
                if len(parts) > 1:
                    try:
                        value = int(parts[1])
                    except ValueError:
                        raise OptionError(
                            "Invalid host resource: %s" % resdef), \
                            None, sys.exc_info()[2]
                hostdef.resources[name] = value

            for catdef in opts.hostcat:
                name, value = check_category(catdef)
                hostdef.categories[name] = value

            if opts.hostports:
                hostdef.ports_ranges = dict()
            for ports in opts.hostports:
                group, start, stop = tuple(ports.split(":"))
                hostdef.ports_ranges[group] = (int(start), int(stop))

        agency.set_host_def(hostdef)

        d.addCallback(defer.drop_param, agency.initiate)
        for desc, kwargs, name in opts.agents:
            d.addCallback(defer.drop_param, agency.add_static_agent,
                          desc, kwargs, name)
    else:
        # standalone specific
        kwargs = opts.standalone_kwargs or dict()
        to_spawn = opts.agent_id or opts.agents[0][0]
        d.addCallback(defer.drop_param, agency.initiate)
        d.addCallback(defer.drop_param, agency.spawn_agent,
                      to_spawn, **kwargs)
    queue = None
    if opts.agency_daemonize:
        import multiprocessing
        queue = multiprocessing.Queue()

    d.addCallbacks(_bootstrap_success, _bootstrap_failure,
                   callbackArgs=(queue, ), errbackArgs=(agency, queue))

    if not opts.agency_daemonize:
        reactor.run()
    else:
        logname = "%s.%s.log" % ('feat', agency.agency_id)
        logfile = os.path.join(config.agency.logdir, logname)
        log.info("bootstrap", "Daemon processs will be logging to %s",
                 logfile)

        try:
            pid = os.fork()
        except OSError, e:
            sys.stderr.write("Failed to fork: (%d) %s\n" %
                             (e.errno, e.strerror))
            os._exit(1)

        if pid > 0:
            # original process waits for information about what status code
            # to use on exit
            log.info('bootstrap',
                     "Waiting for deamon process to intialize the agency")
            try:
                exit_code, reason = queue.get(timeout=20)
            except multiprocessing.queues.Empty:
                log.error('bootstrap',
                          "20 seconds timeout expires waiting for agency"
                          " in child process to initiate.")
                os._exit(1)
            else:
                log.info('bootstrap', "Process exiting with %d status",
                         exit_code)
                if exit_code:
                    log.info('bootstrap', 'Reason for failure: %s', reason)
                sys.exit(exit_code)
        else:
            # child process performs second fork
            try:
                pid = os.fork()
            except OSError, e:
                sys.stderr.write("Failed to fork: (%d) %s\n" %
                                 (e.errno, e.strerror))
                os._exit(1)
            if pid > 0:
                # child process just exits
                sys.exit(0)
            else:
                # grandchild runs the reactor and logs to an external log file
                log.FluLogKeeper.redirect_to(logfile, logfile)
                reactor.run()

    global _exit_code
    log.info('bootstrap', 'Process exiting with %d status', _exit_code)
    sys.exit(_exit_code)


def _bootstrap_success(value, queue):
    log.info("bootstrap", "Bootstrap finished successfully")
    if queue:
        # this informs the master process that it can terminate with 0 status
        queue.put((0, ""))


def _bootstrap_failure(fail, agency, queue=None):
    error.handle_failure(agency, fail, 'Agency bootstrap failed, exiting.')
    reason = error.get_failure_message(fail)
    if queue:
        queue.put((1, reason))

    global _exit_code
    _exit_code = 1
    agency.kill(stop_process=True)
