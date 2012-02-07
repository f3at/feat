#!/bin/bash

ROOT=$(cd $(dirname $0); cd ..; pwd)
RUNDIR="$ROOT"
PIDFILE="$RUNDIR/feat.pid"

if [ -e $PIDFILE ]; then
    echo "Shutting down FEAT..."
    ssh localhost -p 6000 "shutdown()"
    exit_code=$?
    if [ $exit_code -ne 0 ]; then
        if [ -e $PIDFILE ]; then
            PID=$(cat $PIDFILE)
            echo "Error while shutting down process $PID"
            echo "Consider removing $PIDFILE..."
            # rm $PIDFILE > /dev/null 2>&1
        else
            echo "Could not shutdown through ssh, and $PIDFILE not found."
            exit $exit_code
        fi
    fi
else
    echo "PID file not found."
fi
