#!/bin/bash

ROOT=$(cd $(dirname $0); cd ..; pwd)
RUNDIR="$ROOT"
PIDFILE="$RUNDIR/feat.pid"

if [ -e $PIDFILE ]; then
    echo "Shutting down FEAT..."
    ssh localhost -p 6000 "shutdown()"
    if [ $? -ne 0 ]; then
    	PID=$(cat $PIDFILE)
    	echo "Error while shutting down process $PID"
    	echo "Removing $PIDFILE..."
    	rm $PIDFILE > /dev/null 2>&1
    fi
else
    echo "PID file not found."
fi
