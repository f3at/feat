DROP SCHEMA test CASCADE;

CREATE SCHEMA test;

CREATE FUNCTION test.assert(p_assertion BOOLEAN,
                            p_message_on_error VARCHAR(255))
			    RETURNS VOID AS $$
BEGIN
  IF p_assertion IS NULL THEN
    RAISE EXCEPTION 'Assertion test is null, that is not supported.';
  END IF;

  IF NOT p_assertion THEN
    RAISE EXCEPTION '%', p_message_on_error;
  END IF;
END;
$$ LANGUAGE plpgsql;


CREATE FUNCTION test.assert_equals(a text, b text)
			    RETURNS VOID AS $$
BEGIN
  PERFORM test.assert(a = b, 'Not equal a=' || a || ' b=' || b);
END;
$$ LANGUAGE plpgsql;


CREATE FUNCTION test.assert_equals(a int, b int)
			    RETURNS VOID AS $$
BEGIN
  PERFORM test.assert(a = b, 'Not equal a=' || a || ' b=' || b);
END;
$$ LANGUAGE plpgsql;


CREATE OR REPLACE FUNCTION test.insert_log() RETURNS void AS $$
BEGIN
  INSERT INTO feat.logs VALUES ('message', 2, 'feat', NULL, NULL, 0,
                                 current_timestamp);
END;
$$ LANGUAGE plpgsql;


CREATE OR REPLACE FUNCTION test.insert_entry() RETURNS void AS $$
BEGIN
  INSERT INTO feat.entries VALUES ('agent_id', 0, NULL, NULL, NULL, 0,
                                  NULL, NULL, NULL, NULL, current_timestamp);
END;
$$ LANGUAGE plpgsql;

