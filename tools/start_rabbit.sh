#!/bin/bash

export RABBITMQ_NODE_IP_ADDRESS=''
export RABBITMQ_NODE_PORT=${RABBITMQ_NODE_PORT:-5672}
export RABBITMQ_LOG_BASE=/tmp
export RABBITMQ_MNESIA_DIR=${RABBITMQ_MNESIA_DIR:-'/tmp/rabbitmq-rabbit-mnesia'}
export RABBITMQ_PLUGINS_EXPAND_DIR=/tmp/rabbitmq-rabbit-plugins-scratch
export RABBITMQ_ALLOW_INPUT=true
export RABBITMQ_SERVER_START_ARGS=
/usr/lib/rabbitmq/bin/rabbitmq-server
