DROP SCHEMA IF EXISTS feat CASCADE;
CREATE SCHEMA feat;


CREATE TABLE feat.logs (
       id serial primary key,
       host_id int,
       message text not null,
       level int not null,
       category varchar(36) not null,
       log_name varchar(36),
       file_path varchar(200),
       line_num int not null,
       timestamp timestamp with time zone not null
);

CREATE TABLE feat.entries (
       id serial primary key,
       host_id int,
       agent_id varchar(36) not null,
       instance_id int not null,
       journal_id bytea,
       function_id varchar(200),
       fiber_id varchar(36),
       fiber_depth int,
       args bytea,
       kwargs bytea,
       side_effects bytea,
       result bytea,
       timestamp timestamp with time zone not null
);


CREATE TABLE feat.hosts (
       id serial primary key,
       hostname varchar(200)
);

ALTER TABLE feat.logs
  ADD CONSTRAINT foreign_hook FOREIGN KEY (host_id) REFERENCES feat.hosts (id);


ALTER TABLE feat.entries
  ADD CONSTRAINT foreign_hook FOREIGN KEY (host_id) REFERENCES feat.hosts (id);


CREATE OR REPLACE FUNCTION feat.host_id_for(varchar(200))
       RETURNS int AS $$
DECLARE
  res int;
  h_name ALIAS FOR $1;
BEGIN
  SELECT INTO res id FROM feat.hosts WHERE hostname = h_name;
  IF res IS NULL THEN
    INSERT INTO feat.hosts (hostname) VALUES(h_name);
    SELECT INTO res id FROM feat.hosts WHERE hostname = h_name;
  END IF;
  RETURN res;
END;
$$ LANGUAGE plpgsql;


CREATE OR REPLACE FUNCTION feat.create_partitions(epoch_time double precision)
      RETURNS void AS
$$
  import time

  localtime = time.localtime(epoch_time)
  postfix = time.strftime('%Y_%m_%d_%H_%M_%S', localtime)
  mapping = {
    'feat.logs': 'feat.logs_%s' % (postfix, ),
    'feat.entries': 'feat.entries_%s' % (postfix, )
  }
  for master, partition in mapping.items():
      plpy.execute('CREATE TABLE %s () INHERITS(%s)' % (partition, master))

      plpy.execute('''
        CREATE OR REPLACE RULE feat_logs_partition AS
          ON INSERT TO %s
          DO INSTEAD
              INSERT INTO %s VALUES ( NEW.* );
      ''' % (master, partition))

$$ LANGUAGE plpythonu;


CREATE OR REPLACE FUNCTION feat.rotate() RETURNS void AS $$
BEGIN
  PERFORM feat.create_partitions((
    SELECT EXTRACT('epoch' FROM current_timestamp)));
END
$$ LANGUAGE plpgsql VOLATILE;


CREATE OR REPLACE FUNCTION feat.current_entries() RETURNS varchar(150) AS $$
DECLARE
  res varchar(150);
BEGIN
  res := (SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'feat' AND
          tablename LIKE 'entries_%'
    ORDER BY tablename DESC
    LIMIT 1);
  RETURN res;
END;
$$ LANGUAGE plpgsql VOLATILE;


CREATE OR REPLACE FUNCTION feat.current_logs() RETURNS varchar(150) AS $$
DECLARE
  res varchar(150);
BEGIN
  res := (SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'feat' AND
          tablename LIKE 'logs_%'
    ORDER BY tablename DESC
    LIMIT 1);
  RETURN res;
END;
$$ LANGUAGE plpgsql VOLATILE;
