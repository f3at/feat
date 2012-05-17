Configuring the postgres server
===============================

Feat may be configured to use the postgres server for storing log and journal entries. If this is a case, the database should have the schema loaded upfront. This is different than using sqlite3 database, in which case the journaler creates the schema himself. The reason for this difference is that postgres database should be shared between the instances, unlike the sqlite which is private to the master agency.

It wouldn't be clear which agency is responsable for creating the schema, for this reason this task is moved to administration.


Creating the database and user
------------------------------

Creating *feat* user. ::

   sudo -u postgres createuser feat --no-createrole --login --createdb --superuser

Setting the password. ::

  sudo -u postgres psql -c "ALTER USER feat WITH PASSWORD 'feat'"

Creating the databse. ::

  sudo -u postgres createdb -O feat feat


Language support
----------------

Before loading the schema make sure postgres is configured with support for following languages:

- plpgsql,

- plpythonu.

They should be enabled on the level of template1 database, hence the schema script does not declare them.
To enable a language log in to template1 database and type: ::

  CREATE LANGUAGE plpgsql;
  CREATE LANGUAGE plpythonu;


Loading the schema
------------------


Schema files can be found in conf/postgres directory. To load a file simply run a command : ::

  psql <dbname> -f <file>

The files available:

- schema.pgsql this file needs to be loaded,

- help_global.pgsql test helper, only needed to run tests,

- test_schema.pgsql test case.


Rotating the database
---------------------

The entries are stored using horizontal table partitioning. The reponsability of triggering creation of the partitions is put on the cron task.

The new entries are always stored to the latest partitions. The naming convention used is <tablename_timestamp> where timestamp has a format: year_month_day_hour_minute_second. Loading the schema does not create the first partition, remember to do this seting up your database for the first time. To trigger it run a command: ::

  psql <dbname> -c "select feat.rotate()"


Allowing network access
-----------------------

You need to edit the */var/lib/pgsql/data/pg_hba.conf* file. The example config for devcluster goes as follows: ::

  # allow access from the office
  host	feat        feat        172.17.5.1/8	      md5
  # allow access from inside the cluster
  host	feat        feat        192.168.65.61/8	      md5
