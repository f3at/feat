#!/bin/bash

_my_name=`basename $0`
if [ "`echo $0 | cut -c1`" = "/" ]; then
  _my_path=`dirname $0`
else
  _my_path=`pwd`/`echo $0 | sed -e s/$_my_name//`
fi


echo "Creating 'feat_test' user."
sudo -u postgres createuser -l feat_test -R -l -d -s
echo "Setting password."
sudo -u postgres psql -c "ALTER USER feat_test WITH PASSWORD 'feat_test'"
echo "Creating 'feat_test' database."
sudo -u postgres createdb -O feat_test feat_test

echo "Loading schema."
psql -U feat_test -f ${_my_path}/../conf/postgres/schema.pgsql || (\
    echo "Failed! If you are seing problems with IDENT authentication "
    echo "You need to allow logins. Edit the file "
    echo "/etc/postgresql/8.4/main/pb_hba.conf and change the policy to "
    echo "'trusted' for the local connections")

