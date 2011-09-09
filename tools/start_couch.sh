#!/bin/bash

rm -rf /tmp/couchdb
mkdir -p /tmp/couchdb/db

_my_name=`basename $0`
if [ "`echo $0 | cut -c1`" = "/" ]; then
  _my_path=`dirname $0`
else
  _my_path=`pwd`/`echo $0 | sed -e s/$_my_name//`
fi

echo "
[couchdb]
database_dir = /tmp/couchdb/db
view_index_dir = /tmp/couchdb/db

[query_servers]
python = ${_my_path}/../bin/feat-couchpy

[httpd]
bind_address = ${HOST:-127.0.0.1}
port = ${PORT:-5984}

[log]
file = /tmp/couchdb/couchdb.log
" > /tmp/local.ini

/usr/bin/couchdb -a /tmp/local.ini
