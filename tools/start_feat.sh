#!/bin/bash

DB_PORT="5984"
DB_NAME="feat"
NTP_SERVER="ntp.fluendo.net"
ROOT=$(cd $(dirname $0); cd ..; pwd)
ENV="$ROOT/env"
BIN="$ROOT/bin"
SRC="$ROOT/src"
CONF="$ROOT/conf"
FEAT="$BIN/feat"
LOGDIR="$ROOT"
RUNDIR="$ROOT"
JOURNAL="$LOGDIR/journal.sqlite3"
LOGFILES="$LOGDIR/feat.*.log"
PIDFILE="$RUNDIR/feat.pid"
DBLOAD="$BIN/feat-dbload"
MHPUB="$CONF/public.key"
MHPRIV="$CONF/private.key"
MHAUTH="$CONF/authorized_keys"
GW_P12="$CONF/gateway.p12"
TUNNEL_P12="$CONF/tunneling.p12"

no_daemon=
do_cleanup=
db_reset=
master_host="localhost"
debug=
sync_time=
force_host_restart=

while getopts 'fntcrm:d:' OPTION
do
    case $OPTION in
	    f) force_host_restart=1;;
        n) no_daemon=1;;
        t) sync_time=1;;
        c) do_cleanup=1;;
        r) db_reset=1;;
        m) master_host="$OPTARG";;
        d) debug="$OPTARG";;
        ?) printf "Usage: %s: [-cfrt] [-d DEBUG] [-m MASTER_HOSTNAME]\n" $(basename $0) >&2
           exit 2;;
    esac
done
shift $(($OPTIND - 1))

if [ -e "$PIDFILE" ]; then
    echo "FEAT may be running, delete PID file $PIDFILE"
    exit 1
fi

if [ $do_cleanup ]; then
    files=`ls -1 $LOGFILES`
    for l in $files; do
        if [ -e "$l" ]; then
            echo "Cleaning up log file $l"
            rm "$l"
        fi
    done
    if [ -e "$JOURNAL" ]; then
        echo "Cleaning up journal $JOURNAL"
        rm "$JOURNAL"
    fi
fi

if [ $db_reset ]; then
    echo "Dropping database $DB_NAME..."
    url="http://$master_host:$DB_PORT/$DB_NAME"
    curl -X DELETE "$url"
    echo "Initializing database $DB_NAME..."
    $ENV $DBLOAD -H $master_host
fi

if [ $debug ]; then
    export FEAT_DEBUG="$debug"
    export FEAT_VERBOSE=1
fi

if [ $sync_time ]; then
    echo "Synchronizing clock..."
    sudo ntpdate -u "$NTP_SERVER"
fi

if [ $no_daemon ]; then
    daemon_args=
else
    daemon_args="-D"
fi

force_args=
if [ $force_host_restart ]; then
    force_args="${force_args:-" "}--force-host-restart"
fi

echo "Starting F3AT..."
$ENV $FEAT -m "$master_host" -H "$master_host" \
           -L "$LOGDIR" -R "$RUNDIR" $daemon_args \
           -k "$MHPUB" -K "$MHPRIV" -A "$MHAUTH" \
           -G "$GW_P12" -T "$TUNNEL_P12" \
           $force_args "$@"
