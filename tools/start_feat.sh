#!/bin/bash

DB_PORT="5984"
DB_NAME="feat"
NTP_SERVER="ntp.fluendo.net"
ROOT=$(cd $(dirname $0); cd ..; pwd)
ENV="$ROOT/env"
BIN="$ROOT/bin"
SRC="$ROOT/src"
FEAT="$BIN/feat"
LOGDIR="$ROOT"
RUNDIR="$ROOT"
JOURNAL="$LOGDIR/journal.sqlite3"
LOGFILES=( "$LOGDIR/feat.host.log" "$SRCDIR/standalone.log" )
PIDFILE="$RUNDIR/feat.host.pid"
DBLOAD="$SRC/feat/bin/dbload.py"
MHDIR="$SRC/feat/bin"
MHPUB="$MHDIR/public.key"
MHPRIV="$MHDIR/private.key"
MHAUTH="$MHDIR/authorized_keys"

no_daemon=
do_cleanup=
db_reset=
master_host="localhost"
debug=
sync_time=

while getopts 'ntcrm:d:' OPTION
do
    case $OPTION in
        n) no_daemon=1;;
        t) sync_time=1;;
        c) do_cleanup=1;;
        r) db_reset=1;;
        m) master_host="$OPTARG";;
        d) debug="$OPTARG";;
        ?) printf "Usage: %s: [-crt] [-d DEBUG] [-h HOSTNAME]\n" $(basename $0) >&2
           exit 2;;
    esac
done
shift $(($OPTIND - 1))

if [ -e "$PIDFILE" ]; then
    echo "FEAT may be running, delete PID file $PIDFILE"
    exit 1
fi

if [ $do_cleanup ]; then
    for l in $LOGFILES; do
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
    daemon_args="-R "$RUNDIR" -D"
fi

echo "Starting F3AT..."
$ENV $FEAT -m "$master_host" -H "$master_host" -L "$LOGDIR" $daemon_args -k "$MHPUB" -K "$MHPRIV" -A "$MHAUTH"
