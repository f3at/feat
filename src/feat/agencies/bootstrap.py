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
import tempfile
import os
import optparse
import sys

from feat import everything
from feat.agents.base import descriptor
from feat.agents.common import host
from feat.agencies.net import agency as net_agency, standalone, database
from feat.agencies.net.options import add_options, OptionError
from feat.common import log, run, defer
from feat.common.serialization import json
from feat.utils import host_restart
from feat.interface.agent import Access, Address, Storage

from twisted.internet import reactor


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
        except (TypeError, ValueError):
            raise OptionError("Error unserializing json dictionary: %s " %
                              opts.standalone_kwargs), None, sys.exc_info()[2]
    if opts.agents_kwargs:
        if len(opts.agents_kwargs) > len(opts.agents):
            msg = "Received keywords for %d agents and only %d to spawn." % (
                              len(opts.agents_kwargs), len(opts.agents))
            log.debug("feat", msg)
            log.debug("feat", "keywords: %r, agents: %r",
                opts.agents_kwargs, opts.agents)
            raise OptionError(msg)
        parsed = list()
        for element in opts.agents_kwargs:
            try:
                p = json.unserialize(element)
                if not isinstance(p, dict):
                    raise TypeError(element)
                parsed.append(p)
            except (TypeError, ValueError):
                raise OptionError("Error unserializing json dictionary: %s " %
                                  element)
        opts.agents_kwargs = parsed

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

    with _Bootstrap(parser=parser, args=args) as bootstrap:
        agency = bootstrap.agency
        opts = bootstrap.opts
        args = bootstrap.args
        opts, args = check_options(opts, args)

        descriptors = descriptors or []

        d = defer.succeed(None)

        if not opts.standalone:
            # specific to running normal agency
            if opts.force_host_restart:
                dbc = agency.config['db']
                db = database.Database(
                    dbc['host'], int(dbc['port']), dbc['name'])
                connection = db.get_connection()
                d.addCallback(defer.drop_param, host_restart.do_cleanup,
                              connection, agency._get_host_agent_id())

            for name in opts.agents:
                factory = descriptor.lookup(name)
                if factory is None:
                    msg = "No descriptor factory found for agent %s" % name
                    raise OptionError(msg)
                descriptors.append(factory())

            hostdef = opts.hostdef

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
            for desc in descriptors:
                kwargs = (opts.agents_kwargs.pop(0)
                          if opts.agents_kwargs else {})
                log.debug("feat", ("Starting agent with descriptor %r "
                                   "Passing %r to his initiate()"),
                          desc, kwargs)
                d.addCallback(defer.drop_param, agency.spawn_agent, desc,
                              **kwargs)
        else:
            # standalone specific
            kwargs = opts.standalone_kwargs or dict()
            d.addCallback(defer.drop_param, agency.initiate)
            d.addCallback(defer.drop_param, agency.spawn_agent,
                          opts.agents[0], **kwargs)
        return d


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
            log.info("run", "Logging will temporarily be done to: %s", tmp)
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
