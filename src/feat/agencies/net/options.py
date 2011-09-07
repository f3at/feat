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

from feat.common import reflect

from feat.agencies.net.broker import DEFAULT_SOCKET_PATH
from feat.agencies.net.database import DEFAULT_DB_HOST, DEFAULT_DB_PORT
from feat.agencies.net.database import DEFAULT_DB_NAME

DEFAULT_MSG_HOST = "localhost"
DEFAULT_MSG_PORT = 5672
DEFAULT_MSG_USER = "guest"
DEFAULT_MSG_PASSWORD = "guest"

DEFAULT_JOURFILE = 'journal.sqlite3'
DEFAULT_GW_PORT = 5500

# Only for command-line options
DEFAULT_MH_PUBKEY = "public.key"
DEFAULT_MH_PRIVKEY = "private.key"
DEFAULT_MH_AUTH = "authorized_keys"
DEFAULT_MH_PORT = 6000

DEFAULT_ENABLE_SPAWNING_SLAVE = True
DEFAULT_RUNDIR = "/var/run/feat"
DEFAULT_LOGDIR = "/var/log/feat"
DEFAULT_DAEMONIZE = False

DEFAULT_FORCE_HOST_RESTART = False
MASTER_LOG_LINK = "feat.master.log"


def add_options(parser):
    add_general_options(parser)
    add_agency_options(parser)
    add_host_options(parser)
    add_db_options(parser)
    add_msg_options(parser)
    add_mh_options(parser)
    add_gw_options(parser)


def add_general_options(parser):
    parser.add_option('-d', '--debug',
                      action="store", type="string", dest="debug",
                      help="Set debug levels.")
    parser.add_option('-i', '--import', help='import specified module',
                      action='callback', callback=_load_module,
                      type="str", metavar="MODULE")
    parser.add_option('-C', '--config-file', action='callback',
                      help="Config file, the configuration loaded from the \
                      configuration file will overwrite other \
                      parameters defined",
                      callback=parse_config_file, nargs=1,
                      type="string", dest='config_file')


def add_agency_options(parser):
    group = optparse.OptionGroup(parser, "Agency options")
    group.add_option('-j', '--jourfile',
                     action="store", dest="agency_journal",
                     help=("journal filename (default: %s)"
                           % DEFAULT_JOURFILE))
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
    group.add_option('-D', '--daemonize',
                     action="store_true", dest="agency_daemonize",
                     help="run in background as a daemon")
    group.add_option('--force-host-restart',
                     action="store_true", dest="agency_force_host_restart",
                     help=("force restarting host agent which descriptor "
                           "exists in database."))
    group.add_option('-a', '--agent', dest="agents", action="append",
                      help="Start an agent of specified type.",
                      metavar="AGENT_NAME", default=[])
    group.add_option('-X', '--standalone',
                      action="store_true", dest="standalone",
                      help="run agent in standalone agency (default: False)",
                      default=False)
    group.add_option('--kwargs',
                      action="store", dest="standalone_kwargs",
                      help="serialized kwargs to pass to standalone agent",
                      default=None)

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


def add_db_options(parser):
    # database related options
    group = optparse.OptionGroup(parser, "Database options")
    group.add_option('-H', '--dbhost', dest="db_host",
                     help=("host of database server to connect to "
                           "(default: %s)" % DEFAULT_DB_HOST),
                     metavar="HOST")
    group.add_option('-P', '--dbport', dest="db_port",
                     help=("port of messaging server to connect to "
                           "(default: %s)" % DEFAULT_DB_PORT),
                     metavar="PORT", type="int")
    group.add_option('-N', '--dbname', dest="db_name",
                     help=("host of database server to connect to "
                           "(default: %s)" % DEFAULT_DB_NAME),
                     metavar="NAME")
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
                     help=("port for the gateway to listen (default: %s)" %
                           DEFAULT_GW_PORT), metavar="PORT")
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


def _load_module(option, opt, value, parser):
    try:
        reflect.named_module(value)
    except ImportError:
        raise OptionError("Unknown module %s" % value)


def parse_config_file(option, opt_str, value, parser):
    import ConfigParser
    try:
        cfg = ConfigParser.ConfigParser()
        cfg.readfp(open(value, 'r'))
        for dest, value in cfg.items('Feat'):
            values = value.split()
            opt = parser.get_option('--' + dest)
            if not opt:
                print ("Ignoring unknown option %s defined in config file" %
                       (dest, ))
                continue
            for value in values:
                opt.process(opt_str, value, parser.values, parser)
    except IOError:
        print 'Config file not found, skipping ...'


class OptionError(Exception):
    pass
