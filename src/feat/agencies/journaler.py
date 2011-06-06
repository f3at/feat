# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import sqlite3
import operator
import types
import signal

from zope.interface import implements
from twisted.enterprise import adbapi
from twisted.spread import pb, jelly

from feat.common import (log, text_helper, error_handler, defer,
                         formatable, enum, decorator, time, manhole, )
from feat.agencies import common
from feat.common.serialization import banana

from feat.interface.journal import *
from feat.interface.serialization import *
from feat.agencies.interface import *


class State(enum.Enum):

    '''
    disconnected - there is no connection to database
    connected - connection is ready, entries can be insterted
    '''
    (disconnected, connected, ) = range(2)


class EntriesCache(object):
    '''
    Helper class storing the data and giving the back in transactional way.
    '''

    def __init__(self):
        self._cache = list()
        self._fetched = None

    def append(self, entry):
        self._cache.append(entry)

    def fetch(self):
        '''
        Gives all the data it has stored, and remembers what it has given.
        Later we need to call commit() to actually remove the data from the
        cache.
        '''
        if self._fetched is not None:
            raise RuntimeError('fetch() was called but the previous one has '
                               'not yet been applied. Not supported')
        if self._cache:
            self._fetched = len(self._cache)
        return self._cache[0:self._fetched]

    def commit(self):
        '''
        Actually remove data returned by fetch() from the cache.
        '''
        if self._fetched is None:
            raise RuntimeError('commit() was called but nothing was fetched')
        self._cache = self._cache[self._fetched:]
        self._fetched = None

    def rollback(self):
        if self._fetched is None:
            raise RuntimeError('rollback() was called but nothing was fetched')
        self._fetched = None

    def is_locked(self):
        '''
        Tells if we are currently in the locked state (need commit or rollback)
        '''
        return self._fetched is not None

    def __len__(self):
        return len(self._cache)


@decorator.parametrized_function
def in_state(func, *states):

    def wrapper(self, *args, **kwargs):
        d = defer.succeed(None)
        if not self._cmp_state(states):
            d.addCallback(defer.drop_param, self.wait_for_state, *states)
        d.addCallback(defer.drop_param, func, self, *args, **kwargs)
        return d

    return wrapper


class Journaler(log.Logger, log.LogProxy, common.StateMachineMixin):
    implements(IJournaler)

    log_category = 'journaler'

    _error_handler = error_handler

    def __init__(self, logger):
        log.Logger.__init__(self, logger)
        log.LogProxy.__init__(self, logger)

        common.StateMachineMixin.__init__(self, State.disconnected)
        self._writer = None
        self._flush_task = None
        self._cache = EntriesCache()
        self._notifier = defer.Notifier()

    def configure_with(self, writer):
        self._ensure_state(State.disconnected)
        self._writer = IJournalWriter(writer)
        self._set_state(State.connected)
        self._schedule_flush()

    def close(self):
        self._writer = None
        self._set_state(State.disconnected)

    ### IJournaler ###

    def get_connection(self, externalizer):
        externalizer = IExternalizer(externalizer)
        instance = JournalerConnection(self, externalizer)
        return instance

    def prepare_record(self):
        return Record(self)

    @in_state(State.connected)
    def get_histories(self):
        return self._writer.get_histories()

    @in_state(State.connected)
    def get_entries(self, history):
        return self._writer.get_entries(history)

    def insert_entry(self, **data):
        self._cache.append(data)
        self._schedule_flush()
        return self._notifier.wait('flush')

    @in_state(State.connected)
    def get_filename(self):
        return self._writer.get_filename()

    ### private ###

    def _schedule_flush(self):
        if self._flush_task is None:
            self._flush_task = time.callLater(0, self._flush)

    @in_state(State.connected)
    def _flush(self):
        entries = self._cache.fetch()
        if entries:
            d = self._writer.insert_entries(entries)
            d.addCallbacks(defer.drop_param, self._flush_error,
                           callbackArgs=(self._flush_complete, ))
            return d
        else:
            self._flush_complete()

    def _flush_complete(self):
        if self._cache.is_locked():
            self._cache.commit()
        self._flush_task = None
        self._notifier.callback('flush', None)
        if len(self._cache) > 0:
            self._schedule_flush()

    def _flush_error(self, fail):
        self._cache.rollback()
        fail.raiseException()


class BrokerProxyWriter(log.Logger, common.StateMachineMixin):
    implements(IJournalWriter)

    log_category = 'broker-proxy-writer'

    _error_handler = error_handler

    def __init__(self, broker):
        '''
        @param encoding: Optional encoding to be used for blob fields.
        @type encoding: Should be a valid parameter for str.encode() method.
        @param filename: File to use for entries. Defaults to :memory:
        @param logger: ILogger to use
        '''
        log.Logger.__init__(self, broker)
        common.StateMachineMixin.__init__(self, State.disconnected)

        self._broker = broker
        self._set_writer(None)
        self._cache = EntriesCache()
        self._semaphore = defer.DeferredSemaphore(1)

    def initiate(self):
        d = self._broker.get_journal_writer()
        d.addCallback(self._set_writer)
        d.addCallback(defer.drop_param, self._set_state, State.connected)
        return d

    def close(self):
        d = self._flush_next()
        d.addCallback(defer.drop_param, self._set_state, State.disconnected)
        d.addCallback(defer.drop_param, self._set_writer, None)
        return d

    @in_state(State.connected)
    def get_histories(self):
        return self._writer.callRemote('get_histories')

    @in_state(State.connected)
    def get_entries(self, history):
        return self._writer.callRemote('get_entries', history)

    def insert_entries(self, entries):
        for data in entries:
            self._cache.append(data)
        return self._flush_next()

    @in_state(State.connected)
    def get_filename(self):
        return self._writer.callRemote('get_filename')


    ### private ###

    @in_state(State.connected)
    def _flush_next(self):
        if len(self._cache) == 0:
            return defer.succeed(None)
        else:
            d = self._semaphore.run(self._push_entries)
            d.addCallback(defer.drop_param, self._flush_next)
            return d

    def _push_entries(self):
        entries = self._cache.fetch()
        if entries:
            d = self._writer.callRemote('insert_entries', entries)
            d.addCallbacks(defer.drop_param, defer.drop_param,
                           callbackArgs=(self._cache.commit, ),
                           errbackArgs=(self._cache.rollback, ))
            return d

    def _set_writer(self, writer):
        self._writer = writer


class SqliteWriter(log.Logger, log.LogProxy, common.StateMachineMixin,
                   manhole.Manhole):
    implements(IJournalWriter)

    log_category = 'sqlite-writer'

    _error_handler = error_handler

    def __init__(self, logger, filename=":memory:", encoding=None,
                 on_rotate=None):
        '''
        @param encoding: Optional encoding to be used for blob fields.
        @type encoding: Should be a valid parameter for str.encode() method.
        @param filename: File to use for entries. Defaults to :memory:
        @param logger: ILogger to use
        '''
        log.Logger.__init__(self, logger)
        log.LogProxy.__init__(self, logger)
        common.StateMachineMixin.__init__(self, State.disconnected)

        self._encoding = encoding
        self._db = None
        self._filename = filename
        self._reset_history_id_cache()
        self._cache = EntriesCache()
        # the semaphore is used to always have at most running
        # .perform_instert() method
        self._semaphore = defer.DeferredSemaphore(1)

        self._old_sighup_handler = None
        self._sighup_installed = False

        self._on_rotate_cb = on_rotate

    def initiate(self):
        self._db = adbapi.ConnectionPool('sqlite3', self._filename,
                                         cp_min=1, cp_max=1, cp_noisy=True,
                                         check_same_thread=False,
                                         timeout=10)
        self._install_sighup()
        return self._check_schema()

    ### IJournalWriter ###

    def close(self):
        self._db.close()
        self._uninstall_sighup()
        self._set_state(State.disconnected)

    @manhole.expose()
    @in_state(State.connected)
    def get_histories(self):
        return History.fetch(self._db)

    @manhole.expose()
    @in_state(State.connected)
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

    @manhole.expose()
    def insert_entries(self, entries):
        for data in entries:
            self._cache.append(data)
        return self._flush_next()

    @manhole.expose()
    def get_filename(self):
        return self._filename

    ### Private ###

    def _reset_history_id_cache(self):
        # (agent_id, instance_id, ) -> history_id
        self._history_id_cache = dict()

    def _install_sighup(self):
        if self._sighup_installed:
            return

        def sighup(signum, frame):
            if callable(self._old_sighup_handler):
                self._old_sighup_handler(signum, frame)

            self.log("Received SIGHUP, reopening the journal.")
            self.close()
            self.initiate()
            if callable(self._on_rotate_cb):
                self._on_rotate_cb()

        self.log('Installing SIGHUP handler.')
        handler = signal.signal(signal.SIGHUP, sighup)
        if handler == signal.SIG_DFL or handler == signal.SIG_IGN:
            self._old_sighup_handler = None
        else:
            self._old_sighup_handler = handler
        self._sighup_installed = True

    def _uninstall_sighup(self):
        if not self._sighup_installed:
            return

        self.log('Reverting old SIGHUP handler.')
        handler = self._old_sighup_handler or signal.SIG_DFL
        signal.signal(signal.SIGHUP, handler)
        self._sighup_installed = False
        self._old_sighup_handler = None

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

        insert_meta = "INSERT INTO metadata VALUES('%s', '%s')"
        commands += [insert_meta % (u'encoding', self._encoding, )]

        self._reset_history_id_cache()
        # insert_history = "INSERT INTO histories VALUES(%d, '%s', %d)"
        # for (a_id, i_id), h_id in self._history_id_cache.iteritems():
        #     commands += [insert_history % (h_id, a_id, i_id)]

        d = self._db.runWithConnection(run_all, commands)
        d.addCallbacks(self._initiated_ok, self._error_handler)
        return d

    def _initiated_ok(self, *_):
        self.log('Journaler initiated correctly for the filename %r',
                 self._filename)
        self._set_state(State.connected)
        return self._flush_next()

    def _perform_inserts(self, cache):

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

        def transaction(connection, cache):
            entries = cache.fetch()
            if not entries:
                return
            entries = map(self._encode, entries)
            try:
                for data in entries:
                    history_id = self._get_history_id(
                        connection, data['agent_id'], data['instance_id'])
                    do_insert(connection, history_id, data)
                cache.commit()
            except Exception:
                cache.rollback()
                raise

        return self._db.runWithConnection(transaction, cache)

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

    @in_state(State.connected)
    def _flush_next(self):
        if len(self._cache) == 0:
            return defer.succeed(None)
        else:
            d = self._semaphore.run(self._perform_inserts, self._cache)
            d.addCallback(defer.drop_param, self._flush_next)
            return d


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
        self._args = serializer.freeze(args or tuple())
        self._kwargs = serializer.freeze(kwargs or dict())
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


class History(formatable.Formatable, pb.Copyable):
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


jelly.globalSecurity.allowInstancesOf(History)


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
