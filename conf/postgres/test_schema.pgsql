BEGIN;


CREATE OR REPLACE FUNCTION test.test_schema() RETURNS void AS $$
DECLARE
  initial_count int;
  actual_count int;
  global_initial_count int;
  global_actual_count int;
BEGIN
  execute feat.rotate();

  initial_count := (SELECT COUNT(*) FROM ONLY feat.logs);
  global_initial_count := (SELECT COUNT(*) FROM feat.logs);
  PERFORM test.insert_log();
  actual_count := (SELECT COUNT(*) FROM ONLY feat.logs);
  global_actual_count := (SELECT COUNT(*) FROM feat.logs);

  PERFORM test.assert(initial_count = actual_count,
                      'Log was inserted to master table');
  PERFORM test.assert(global_initial_count = global_actual_count - 1,
                      'Log was not inserted at all');

  initial_count := (SELECT COUNT(*) FROM ONLY feat.entries);
  global_initial_count := (SELECT COUNT(*) FROM feat.entries);
  PERFORM test.insert_entry();
  actual_count := (SELECT COUNT(*) FROM ONLY feat.entries);
  global_actual_count := (SELECT COUNT(*) FROM feat.entries);

  PERFORM test.assert(initial_count = actual_count,
                      'Entry was inserted to master table');
  PERFORM test.assert(global_initial_count = global_actual_count - 1,
                      'Entry was not inserted at all');

END;
$$ LANGUAGE plpgsql;

SELECT test.test_schema();

ROLLBACK;

BEGIN;

CREATE OR REPLACE FUNCTION test.test_rotating() RETURNS void AS $$
DECLARE
  name varchar(100);
  coun int;
BEGIN
  PERFORM feat.create_partitions(0);
  name := (SELECT feat.current_entries());
  PERFORM test.assert_equals('entries_1970_01_01_01_00_00', name);
  name := (SELECT feat.current_logs());
  PERFORM test.assert_equals('logs_1970_01_01_01_00_00', name);

  PERFORM test.insert_log();
  coun := (SELECT count(*) FROM ONLY feat.logs_1970_01_01_01_00_00);
  PERFORM test.assert_equals(1, coun);

  PERFORM test.insert_entry();
  coun := (SELECT count(*) FROM ONLY feat.entries_1970_01_01_01_00_00);
  PERFORM test.assert_equals(1, coun);

  -- Now create the new partition and check that entries go there

  PERFORM feat.create_partitions(5);
  name := (SELECT feat.current_entries());
  PERFORM test.assert_equals('entries_1970_01_01_01_00_05', name);
  name := (SELECT feat.current_logs());
  PERFORM test.assert_equals('logs_1970_01_01_01_00_05', name);

  -- One entry for partition for both tables
  PERFORM test.insert_log();
  coun := (SELECT count(*) FROM ONLY feat.logs_1970_01_01_01_00_00);
  PERFORM test.assert_equals(1, coun);
  coun := (SELECT count(*) FROM ONLY feat.logs_1970_01_01_01_00_05);
  PERFORM test.assert_equals(1, coun);

  PERFORM test.insert_entry();
  coun := (SELECT count(*) FROM ONLY feat.entries_1970_01_01_01_00_00);
  PERFORM test.assert_equals(1, coun);
  coun := (SELECT count(*) FROM ONLY feat.logs_1970_01_01_01_00_05);
  PERFORM test.assert_equals(1, coun);


END;
$$ LANGUAGE plpgsql;

SELECT test.test_rotating();


ROLLBACK;