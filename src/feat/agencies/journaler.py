# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import sqlite3
import operator
import types

from zope.interface import implements
from twisted.enterprise import adbapi

from feat.common import log, text_helper, error_handler, defer, formatable
from feat.common.serialization import banana

from feat.interface.journal import *
from feat.interface.serialization import *
from feat.agencies.interface import *


class Journaler(log.Logger, log.LogProxy):
    implements(IJournaler)

    log_category = 'journaler'

    _error_handler = error_handler

    def __init__(self, logger, filename=":memory:", encoding=None):
        '''
        @param encoding: Optional encoding to be used for blob fields.
        @type encoding: Should be a valid parameter for str.encode() method.
        @param filename: File to use for entries. Defaults to :memory:
        @param logger: ILogger to use
        '''
        log.Logger.__init__(self, logger)
        log.LogProxy.__init__(self, logger)

        self.running = False
        self._encoding = encoding
        self._db = None
        self._filename = filename
        # (agent_id, instance_id, ) -> history_id
        self._history_id_cache = dict()

    def initiate(self):
        self._db = adbapi.ConnectionPool('sqlite3', self._filename,
                                         cp_min=1, cp_max=1, cp_noisy=True,
                                         check_same_thread=False,
                                         timeout=3)
        return self._check_schema()

    def close(self):
        self._db.close()
        self.running = False


    ### IJournaler ###

    def get_connection(self, externalizer):
        externalizer = IExternalizer(externalizer)
        instance = JournalerConnection(self, externalizer)
        return instance

    def prepare_record(self):
        return Record(self)

    def get_histories(self):
        return History.fetch(self._db)

    def get_entries(self, history):
        '''
        Returns a list of journal entries  for the given history_id.
        '''
        if not isinstance(history, History):
            raise AttributeError(
                'First paremeter is expected to be History instance, got %r'
                % history)

        command = text_helper.format_block("""
        SELECT histories.agent_id,
               histories.instance_id,
               entries.journal_id,
               entries.function_id,
               entries.fiber_id,
               entries.fiber_depth,
               entries.args,
               entries.kwargs,
               entries.side_effects,
               entries.result,
               entries.timestamp
          FROM entries
          LEFT JOIN histories ON histories.id = entries.history_id
          WHERE entries.history_id = ?
          ORDER BY entries.rowid ASC
        """)
        d = self._db.runQuery(command, (history.history_id, ))
        d.addCallback(self._decode)
        return d

    def insert_entry(self, **data):
        assert self.running

        def do_insert(connection, history_id, data):
            command = text_helper.format_block("""
            INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                                        strftime('%s', 'now'))
            """)
            connection.execute(
                command, (history_id,
                          data['journal_id'], data['function_id'],
                          data['fiber_id'], data['fiber_depth'],
                          data['args'], data['kwargs'],
                          data['side_effects'], data['result'], ))

        def transaction(connection, data):
            history_id = self._get_history_id(
                connection, data['agent_id'], data['instance_id'])
            do_insert(connection, history_id, data)

        data = self._encode(data)
        return self._db.runWithConnection(transaction, data)

    def get_filename(self):
        return self._filename

    ### Private ###

    def _get_history_id(self, connection, agent_id, instance_id):
        '''
        Checks own cache for history_id for agent_id and instance_id.
        If information is missing fetch it from database. If it is not there
        create the new record.

        BEWARE: This method runs in a thread.
        '''
        cache_key = (agent_id, instance_id, )
        if cache_key in self._history_id_cache:
            history_id = self._history_id_cache[cache_key]
            return history_id
        else:
            command = text_helper.format_block("""
            SELECT id FROM histories WHERE agent_id = ? AND instance_id = ?
            """)
            cursor = connection.cursor()
            cursor.execute(command, (agent_id, instance_id, ))
            res = cursor.fetchall()
            if res:
                history_id = res[0][0]
                self._history_id_cache[cache_key] = history_id
                return history_id
            else:
                command = 'INSERT INTO histories VALUES (NULL, ?, ?)'
                cursor.execute(command, (agent_id, instance_id, ))
                history_id = cursor.lastrowid
                self._history_id_cache[cache_key] = history_id
                return history_id

    def _decode(self, entries):
        '''
        Takes the list of rows returned by sqlite.
        Returns rows in readable format.
        '''

        def decode_blobs(row):
            row = list(row)
            for index, value in zip(range(len(row)), row):
                if isinstance(value, types.BufferType):
                    value = str(value)
                    if self._encoding:
                        value = value.decode(self._encoding)
                    row[index] = value
            return row

        return map(decode_blobs, entries)

    def _encode(self, data):
        result = dict()

        # just copy, caring open escapes
        result['fiber_depth'] = data['fiber_depth']
        result['instance_id'] = data['instance_id']

        for key in ('agent_id', 'function_id', 'fiber_id', ):
            result[key] = data[key].decode("utf-8")

        # encode the blobs
        for key in ('journal_id', 'args', 'kwargs',
                    'side_effects', 'result', ):
            safe = data[key]
            if self._encoding:
                safe = safe.encode(self._encoding)
            result[key] = sqlite3.Binary(safe)

        return result

    def _check_schema(self):
        d = self._db.runQuery(
            'SELECT value FROM metadata WHERE name = "encoding"')
        d.addCallbacks(self._got_encoding, self._create_schema)
        return d

    def _got_encoding(self, res):
        encoding = res[0][0]
        if self._encoding is not None and encoding != self._encoding:
            self.warning("Journaler created with encoding %r but the one "
                         "loaded from existing database is %r. Using "
                         "the value of: %r",
                         self._encoding, encoding, encoding)
        self._encoding = encoding
        self._initiated_ok()

    def _create_schema(self, fail):
        fail.trap(sqlite3.OperationalError)
        self.log('Creating entries table.')
        commands = [
            text_helper.format_block("""
            CREATE TABLE entries (
              history_id INTEGER NOT NULL,
              journal_id BLOB,
              function_id VARCHAR(200),
              fiber_id VARCHAR(36),
              fiber_depth INTEGER,
              args BLOB,
              kwargs BLOB,
              side_effects BLOB,
              result BLOB,
              timestamp INTEGER
            )
            """),
            text_helper.format_block("""
            CREATE TABLE histories (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              agent_id VARCHAR(36),
              instance_id INTEGER
            )
            """),
            text_helper.format_block("""
            CREATE TABLE metadata (
              name VARCHAR(100),
              value VARCHAR(100)
            )
            """),
            text_helper.format_block("""
            CREATE INDEX history_idx ON entries(history_id)
            """),
            text_helper.format_block("""
            CREATE INDEX instance_idx ON histories(agent_id, instance_id)
            """)]

        def run_all(connection, commands):
            for command in commands:
                self.log('Executing command:\n %s', command)
                connection.execute(command)

        d = self._db.runWithConnection(run_all, commands)


        insert_meta = "INSERT INTO metadata VALUES(?, ?)"
        d.addCallback(defer.drop_result, self._db.runOperation,
                      insert_meta, (u'encoding', self._encoding, ))
        d.addCallbacks(self._initiated_ok, self._error_handler)
        return d

    def _initiated_ok(self, *_):
        self.log('Journaler initiated correctly for the filename %r',
                 self._filename)
        self.running = True


class Record(object):
    implements(IRecord)

    def __init__(self, journaler):
        self._journaler = journaler

    def commit(self, **data):
        self._journaler.insert_entry(**data)


class JournalerConnection(log.Logger):
    implements(IJournalerConnection)

    def __init__(self, journaler, externalizer):
        log.Logger.__init__(self, journaler)

        self.serializer = banana.Serializer(externalizer=externalizer)
        self.journaler = IJournaler(journaler)

    ### IJournalerConnection ###

    def new_entry(self, agent_id, instance_id, journal_id, function_id,
                  *args, **kwargs):
        record = self.journaler.prepare_record()
        entry = AgencyJournalEntry(
            self.serializer, record, agent_id, instance_id,
            journal_id, function_id, *args, **kwargs)
        return entry

    def get_filename(self):
        return self.journaler.get_filename()


class AgencyJournalSideEffect(object):

    implements(IJournalSideEffect)

    ### IJournalSideEffect ###

    def __init__(self, serializer, record, function_id, *args, **kwargs):
        self._serializer = serializer
        self._record = record
        self._fun_id = function_id
        # FIXME: This is ugly hack introduced by the fact that we cannot
        # serialize methods, hence if side effect param is a method it has
        # to be skipped
        if function_id != "SIDE EFFECT SKIPPED":
            self._args = serializer.convert(args or None)
            self._kwargs = serializer.convert(kwargs or None)
        else:
            self._args = serializer.convert(None)
            self._kwargs = serializer.convert(None)
        self._effects = []
        self._result = None

    ### IJournalSideEffect Methods ###

    def add_effect(self, effect_id, *args, **kwargs):
        assert self._record is not None
        data = (effect_id,
                self._serializer.convert(args),
                self._serializer.convert(kwargs))
        self._effects.append(data)

    def set_result(self, result):
        assert self._record is not None
        self._result = self._serializer.convert(result)
        return self

    def commit(self):
        assert self._record is not None
        data = (self._fun_id, self._args, self._kwargs,
                self._effects, self._result)
        self._record.extend(data)
        self._record = None
        return self


class History(formatable.Formatable):
    '''
    Mapping for objects in history database.
    '''

    formatable.field('history_id', None)
    formatable.field('agent_id', None)
    formatable.field('instance_id', None)

    @classmethod
    def fetch(cls, db):
        d = db.runQuery(
            "SELECT id, agent_id, instance_id FROM histories")
        d.addCallback(cls._parse_resp)
        return d

    @classmethod
    def _parse_resp(cls, resp):
        columns = map(operator.attrgetter('name'), cls._fields)
        return map(lambda row: cls(**dict(zip(columns, row))), resp)


class AgencyJournalEntry(object):

    implements(IJournalEntry)

    def __init__(self, serializer, record, agent_id, instance_id, journal_id,
                 function_id, *args, **kwargs):
        self._serializer = serializer
        self._record = record

        self._data = {
            'agent_id': agent_id,
            'instance_id': instance_id,
            'journal_id': self._serializer.convert(journal_id),
            'function_id': function_id,
            'args': self._serializer.convert(args or None),
            'kwargs': self._serializer.convert(kwargs or None),
            'fiber_id': None,
            'fiber_depth': None,
            'result': None,
            'side_effects': list()}

    ### IJournalEntry Methods ###

    def set_fiber_context(self, fiber_id, fiber_depth):
        assert self._record is not None
        self._data['fiber_id'] = fiber_id
        self._data['fiber_depth'] = fiber_depth
        return self

    def set_result(self, result):
        assert self._record is not None
        self._data['result'] = self._serializer.freeze(result)
        return self

    def new_side_effect(self, function_id, *args, **kwargs):
        assert self._record is not None
        record = []
        self._data['side_effects'].append(record)
        return AgencyJournalSideEffect(self._serializer, record,
                                       function_id, *args, **kwargs)

    def commit(self):
        self._data['side_effects'] = self._serializer.convert(
            self._data['side_effects'])
        self._record.commit(**self._data)
        self._record = None
        return self
