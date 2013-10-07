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
import optparse
import os
import sys

from feat.common import reflect
from feat import applications
from feat.agencies.net import configfile
from feat.configure import configure
from feat.agencies.net.broker import DEFAULT_SOCKET_PATH
from feat.database.driver import DEFAULT_DB_HOST, DEFAULT_DB_PORT
from feat.database.driver import DEFAULT_DB_NAME

DEFAULT_MSG_HOST = "localhost"
DEFAULT_MSG_PORT = 5672
DEFAULT_MSG_USER = "guest"
DEFAULT_MSG_PASSWORD = "guest"

DEFAULT_JOURFILE = "sqlite://" +\
                   os.path.join(configure.logdir, "journal.sqlite3")

DEFAULT_GW_PORT = 5500
DEFAULT_GW_P12_FILE = os.path.join(configure.confdir, "gateway.p12")
DEFAULT_GW_CLIENT_P12_FILE = os.path.join(configure.confdir, "client.p12")
DEFAULT_ALLOW_TCP_GATEWAY = False

DEFAULT_TUNNEL_PORT = 5400
DEFAULT_TUNNEL_P12_FILE = os.path.join(configure.confdir, "tunneling.p12")

# Only for command-line options
DEFAULT_MH_PUBKEY = os.path.join(configure.confdir, "public.key")
DEFAULT_MH_PRIVKEY = os.path.join(configure.confdir, "private.key")
DEFAULT_MH_AUTH = os.path.join(configure.confdir, "authorized_keys")
DEFAULT_MH_PORT = 2222

DEFAULT_ENABLE_SPAWNING_SLAVE = True
DEFAULT_RUNDIR = configure.rundir
DEFAULT_LOGDIR = configure.logdir
DEFAULT_DAEMONIZE = False

MASTER_LOG_LINK = "feat.master.log"

DEFAULT_LOCK_PATH = os.path.join(configure.lockdir, 'feat.lock')

DEFAULT_NSCA_CONFIG_PATH = '/etc/nagios/send_nsca.cfg'
DEFAULT_SEND_NSCA_PATH = '/usr/sbin/send_nsca'


def add_options(parser):
    add_general_options(parser)
    add_agency_options(parser)
    add_host_options(parser)
    add_db_options(parser)
    add_msg_options(parser)
    add_mh_options(parser)
    add_gw_options(parser)
    add_tunnel_options(parser)
    add_nagios_options(parser)


def add_general_options(parser):
    parser.add_option('-d', '--debug',
                      action="store", type="string", dest="debug",
                      help="Set debug levels.")
    parser.add_option('-i', '--import', help='import specified module',
                      action='callback', callback=_load_module,
                      type="str", metavar="MODULE")
    parser.add_option('--application', help='import an application ',
                      action='callback', callback=_load_application,
                      type="str", metavar="APPLICATION")
    parser.add_option('-C', '--config-file', action='callback',
                      help="Config file, the configuration loaded from the \
                      configuration file will overwrite other \
                      parameters defined",
                      callback=parse_config_file, nargs=1,
                      type="string", dest='config_file')


def add_agency_options(parser):
    group = optparse.OptionGroup(parser, "Agency options")
    group.add_option('-j', '--journal',
                     action="append", dest="agency_journal",
                     help=("journal connection string (default: %s). "
                           "You can specify more than one to be used as "
                           "failover. "
                           % DEFAULT_JOURFILE), default=None)
    group.add_option('-S', '--socket-path', dest="agency_socket_path",
                     help=("path to the unix socket used by the agency"
                           "(default: %s)" % DEFAULT_SOCKET_PATH),
                     metavar="PATH")
    group.add_option('-b', '--no-slave',
                     dest="agency_enable_spawning_slave", action="store_false",
                     help=("Disable spawning slave agency"))
    group.add_option('-R', '--rundir',
                     action="store", dest="agency_rundir",
                     help=("Rundir of the agency (default: %s)" %
                           DEFAULT_RUNDIR))
    group.add_option('-L', '--logdir',
                      action="store", dest="agency_logdir",
                      help=("agent log directory (default: %s)" %
                            DEFAULT_LOGDIR))
    group.add_option('--no-daemonize',
                     action="store_false", dest="agency_daemonize",
                     help="Don't daemonize the process", default=True)
    group.add_option('-a', '--agent', dest="agents", action="callback",
                      help="Start an agent of the specified type.",
                      metavar="AGENT_NAME", default=[], type='str',
                      callback=append_agent)
    group.add_option('--agent-id', dest="agent_id", action="store",
                      help=("Start an agent with specified id. Its descriptor "
                            "will be fetched from the database."),
                      metavar="AGENT_ID", type='str')
    group.add_option('-X', '--standalone',
                      action="store_true", dest="standalone",
                      help="run agent in standalone agency (default: False)",
                      default=False)
    group.add_option('--kwargs',
                      action="store", dest="standalone_kwargs",
                      help="serialized kwargs to pass to standalone agent",
                      default=None)
    group.add_option('--lock-path',
                      action="store", dest="lock_path",
                      help="path for the inter agencies lock (default: %s)" %
                           (DEFAULT_LOCK_PATH, ))
    group.add_option('--hostname',
                      action="store", dest="agency_hostname",
                      help="overrides the host name used by the agency")
    group.add_option('--domainname',
                      action="store", dest="agency_domainname",
                      help="overrides the domain name used by the agency")

    parser.add_option_group(group)


def add_msg_options(parser):
    # Messaging related options
    group = optparse.OptionGroup(parser, "Messaging options")
    group.add_option('-m', '--msghost', dest="msg_host",
                     help=("host of messaging server to connect to "
                           "(default: %s)" % DEFAULT_MSG_HOST),
                     metavar="HOST")
    group.add_option('-p', '--msgport', dest="msg_port",
                     help=("port of messaging server to connect to "
                           "(default: %s" % DEFAULT_MSG_PORT),
                     metavar="PORT", type="int")
    group.add_option('-u', '--msguser', dest="msg_user",
                     help=("username for messaging server (default: %s)" %
                           DEFAULT_MSG_USER),
                     metavar="USER")
    group.add_option('-c', '--msgpass', dest="msg_password",
                     help=("password to messaging server (default: %s)" %
                           DEFAULT_MSG_PASSWORD),
                     metavar="PASSWORD")
    parser.add_option_group(group)


def add_tunnel_options(parser):
    # Tunneling related options
    group = optparse.OptionGroup(parser, "Tunneling options")
    group.add_option('-n', '--tunneling-host', dest="tunnel_host",
                     help="public tunneling host name",
                     metavar="HOST")
    group.add_option('-l', '--tunneling-port', dest="tunnel_port",
                     help=("first port of tunneling port range"
                           "(default: %s" % DEFAULT_TUNNEL_PORT),
                     metavar="PORT", type="int")
    group.add_option('-T', '--tunnel-p12', type="str", dest='tunnel_p12',
                     help=("tunnel PKCS12 file to use for certificate and "
                           "private key; used for server side and and client "
                           " side; peers will be checked against the "
                           "contained CA certificates (default: %s)"
                           % DEFAULT_GW_P12_FILE), metavar="FILE")
    parser.add_option_group(group)


def add_db_options(parser):
    # database related options
    group = optparse.OptionGroup(parser, "Database options")
    group.add_option('-H', '--dbhost', dest="db_host",
                     help=("host of database server to connect to "
                           "(default: %s)" % DEFAULT_DB_HOST),
                     metavar="HOST")
    group.add_option('-P', '--dbport', dest="db_port",
                     help=("port of database server to connect to "
                           "(default: %s)" % DEFAULT_DB_PORT),
                     metavar="PORT", type="int")
    group.add_option('-N', '--dbname', dest="db_name",
                     help=("name of database to use "
                           "(default: %s)" % DEFAULT_DB_NAME),
                     metavar="NAME")
    group.add_option('--dbusername', dest="db_username",
                     help="username to use for authentication ",
                     metavar="USER")
    group.add_option('--dbpassword', dest="db_password",
                     help="password to use for authentication ",
                     metavar="USER")
    group.add_option('--dbhttps', dest="db_https",
                     help="Use SSL connection",
                     default=False, action="store_true")
    parser.add_option_group(group)


def add_mh_options(parser):
    # manhole specific
    group = optparse.OptionGroup(parser, "Manhole options")
    group.add_option('-k', '--pubkey', dest='manhole_public_key',
                     help=("public key file used by the manhole "
                           "(default: %s)" % DEFAULT_MH_PUBKEY))
    group.add_option('-K', '--privkey', dest='manhole_private_key',
                     help=("private key file used by the manhole "
                           "(default: %s)" % DEFAULT_MH_PRIVKEY))
    group.add_option('-A', '--authorized', dest='manhole_authorized_keys',
                     help=("file with authorized keys to be used by manhole "
                           "(default: %s)" % DEFAULT_MH_AUTH))
    group.add_option('-M', '--manhole', type="int", dest='manhole_port',
                     help=("port for the manhole to listen (default: %s)" %
                           DEFAULT_MH_PORT), metavar="PORT")
    parser.add_option_group(group)


def add_gw_options(parser):
    # gateway specific
    group = optparse.OptionGroup(parser, "Gateway options")
    group.add_option('-w', '--gateway-port', type="int", dest='gateway_port',
                     help=("first port for the gateway port range "
                           "for the gateway to listen on (default: %s)" %
                           DEFAULT_GW_PORT), metavar="PORT")
    group.add_option('-G', '--gateway-p12', type="str", dest='gateway_p12',
                     help=("gateway PKCS12 file to use for certificate and "
                           "private key; connecting client certificate will "
                           " be checked against the contained CA "
                           "certificates (default: %s)" % DEFAULT_GW_P12_FILE),
                           metavar="FILE")
    group.add_option('--allow-tcp-gateway', action="store_true",
                     dest='gateway_allow_tcp',
                     help=("if no PKCS12 is specified start the gateway "
                           "anyway without SSL."))
    group.add_option('--gateway-client-p12', action="store",
                     dest='gateway_client_p12',
                     default=DEFAULT_GW_CLIENT_P12_FILE,
                     help=("Client to be used by service script for commands "
                           "requiring using gateway"))
    parser.add_option_group(group)


def add_host_options(parser):
    parser.add_option('-t', '--host-def', dest="hostdef",
                      help="Host definition document identifier.",
                      metavar="HOST_DEF_ID", default=None)
    parser.add_option('-r', '--host-resource', dest="hostres",
                      help="Add a resource to the host agent. "
                           "Format: RES_NAME:RES_MAX. Example: 'epu:42'.",
                      metavar="HOST_DEF_ID", action="append", default=[])
    parser.add_option('-z', '--host-ports-ranges', dest="hostports",
                      help=("Add available port ranges by groups to the "
                            "host agent. "
                            "Format: GROUP_NAME:PORT_MIN:PORT_MAX. Example: "
                            "'worker:1000:2000'."),
                      metavar="HOST_DEF_ID", action="append", default=[])
    parser.add_option('-g', '--host-category', dest="hostcat",
                    help="Add a category to the host agent. "
                         "Format: CAT_NAME:CAT_VALUE.",
                    metavar="HOST_DEF_ID", action="append", default=[])


def add_nagios_options(parser):
    # gateway specific
    group = optparse.OptionGroup(parser, "Nagios options")
    group.add_option('--send-nsca-path', type="str",
                     dest='nagios_send_nsca_path',
                     help=("path to send_nsca executable (default: %s)" %
                           (DEFAULT_SEND_NSCA_PATH, )), metavar="PATH")
    group.add_option('--nsca-config-path', type="str",
                     dest='nagios_nsca_config_path',
                     help=("path to config file of send_nsca (default: %s)" %
                           (DEFAULT_NSCA_CONFIG_PATH, )), metavar="PATH")
    group.add_option('--nagios-monitor', default=[], action="append",
                     dest='nagios_monitors',
                     help=("host to push nsca notifications to "
                           "(multiple allowed)"), metavar="HOST")
    group.add_option('--nagios-host', default=[], action="append",
                     dest='nagios_hosts',
                     help=("hostname from which to accept incoming alerts"
                           "(multiple allowed)"), metavar="HOST")


def _load_module(option, opt, value, parser):
    try:
        reflect.named_module(value)
    except ImportError, e:
        from feat.common import error
        raise OptionError("Cannot import module %s: %s" % (
            value, error.get_exception_message(e))), None, sys.exc_info()[2]


def _load_application(option, opt, value, parser):
    splitted = value.split('.')
    if len(splitted) < 2:
        raise OptionError("Invalid application name to load: %r" % (value, ))

    module = '.'.join(splitted[:-1])
    name = splitted[-1]
    try:
        applications.load(module, name)
    except ImportError:
        raise (
            OptionError(
                "Loading application %s.%s failed" % (module, name)),
            None, sys.exc_info()[2])


def parse_config_file(option, opt_str, value, parser):
    f = open(value, 'r')
    configfile.parse_file(parser, f)


def append_agent(option, opt_str, value, parser):
    configfile.append_agent(parser, value)


class OptionError(Exception):
    pass
