#!/bin/bash

ROOT=$(cd $(dirname $0); cd ..; pwd)
RUNDIR="$ROOT"
PIDFILE="$RUNDIR/feat.host.pid"

if [ -e $PIDFILE ]; then
    PID=$(cat $PIDFILE)
    echo "Killing process $PID..."
    kill "$PID"
    rm "$PIDFILE"
else
    echo "PID file not found."
fi
