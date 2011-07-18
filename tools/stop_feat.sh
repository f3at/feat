#!/bin/bash

ROOT=$(cd $(dirname $0); cd ..; pwd)
RUNDIR="$ROOT"
PIDFILE="$RUNDIR/feat.pid"

if [ -e $PIDFILE ]; then
    echo "Shutting down FEAT..."
    ssh localhost -p 6000 "shutdown()"
    echo "Done"
else
    echo "PID file not found."
fi
