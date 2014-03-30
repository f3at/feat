#!/bin/bash

COUCHDBDIR=/tmp/couchdb-feat
rm -rf $COUCHDBDIR
mkdir -p $COUCHDBDIR

_my_name=`basename $0`
if [ "`echo $0 | cut -c1`" = "/" ]; then
  _my_path=`dirname $0`
else
  _my_path=`pwd`/`echo $0 | sed -e s/$_my_name//`
fi

echo "
[couchdb]
database_dir = $COUCHDBDIR/db
view_index_dir = $COUCHDBDIR/db
uri_file = $COUCHDBDIR/couch.uri

[query_servers]
python = ${_my_path}/../bin/feat-couchpy --log-file $COUCHDBDIR/couchpy.log

[httpd]
bind_address = ${HOST:-127.0.0.1}
port = ${PORT:-5985}

[log]
file = $COUCHDBDIR/couchdb.log
" > $COUCHDBDIR/local.ini

/usr/bin/couchdb -a $COUCHDBDIR/local.ini
