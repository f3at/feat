# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import sqlite3
import operator
import types

from zope.interface import implements
from twisted.enterprise import adbapi
from twisted.spread import pb

from twisted.python import log as twisted_log

from feat.common import (log, text_helper, error_handler, defer,
                         formatable, enum, decorator, time, manhole,
                         fiber, signal, )
from feat.agencies import common
from feat.common.serialization import banana
from feat.extern.log import log as flulog

from feat.interface.journal import IJournalSideEffect, IJournalEntry
from feat.interface.serialization import IExternalizer
from feat.interface.log import ILogKeeper
from feat.agencies.interface import (IJournaler, IJournalWriter, IRecord,
                                     IJournalerConnection)


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


class Journaler(log.Logger, common.StateMachineMixin):
    implements(IJournaler, ILogKeeper)

    log_category = 'journaler'

    _error_handler = error_handler

    # FIXME: at some point switch to False and remove this attribute
    should_keep_on_logging_to_flulog = True

    def __init__(self, logger):
        log.Logger.__init__(self, self)

        common.StateMachineMixin.__init__(self, State.disconnected)
        self._writer = None
        self._flush_task = None
        self._cache = EntriesCache()
        self._notifier = defer.Notifier()

    def configure_with(self, writer):
        self._ensure_state(State.disconnected)
        twisted_log.addObserver(self.on_twisted_log)
        self._writer = IJournalWriter(writer)
        self._set_state(State.connected)
        self._schedule_flush()

    def close(self, flush_writer=True):

        def set_disconnected():
            self._writer = None
            self._set_state(State.disconnected)

        try:
            twisted_log.removeObserver(self.on_twisted_log)
        except ValueError:
            # it should be safe to call close() multiple times,
            # in this case we are not registered as the observer anymore
            pass

        d = self._close_writer(flush_writer)
        d.addCallback(defer.drop_param, set_disconnected)
        return d

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

    def is_idle(self):
        if len(self._cache) > 0:
            return False
        if self._writer:
            return self._writer.is_idle()
        return True

    ### ILogObserver provider ###

    def on_twisted_log(self, event_dict):
        edm = event_dict['message']
        if not edm:
            if event_dict['isError'] and 'failure' in event_dict:
                fail = event_dict['failure']
                self.error("A twisted traceback occurred. Exception: %r.",
                           fail.value)
                if flulog.getCategoryLevel("twisted") < flulog.WARN:
                    self.debug(
                        "Run with debug level >= 2 to see the traceback.")
                else:
                    self.error("%s", fail.getTraceback())

    ### ILogKeeper Methods ###

    def do_log(self, level, object, category, format, args,
               depth=-1, file_path=None, line_num=None):
        level = int(level)
        if category is None:
            category = 'feat'
        if level > flulog.getCategoryLevel(category):
            return

        if file_path is None and line_num is None:
            file_path, line_num = flulog.getFileLine(where=-depth-2)

        if args:
            message = format % args
        else:
            message = str(format)

        data = dict(
            entry_type='log',
            level=level,
            log_name=object,
            category=category,
            file_path=file_path,
            line_num=line_num,
            message=message,
            timestamp=int(time.time_no_sfx()))
        self.insert_entry(**data)

        if self.should_keep_on_logging_to_flulog:
            flulog.doLog(level, object, category, format, args,
                         where=depth, filePath=file_path, line=line_num)

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

    def _close_writer(self, flush_writer=True):
        d = defer.succeed(None)
        if self._writer:
            d.addCallback(defer.drop_param, self._writer.close,
                          flush=flush_writer)
        return d


class BrokerProxyWriter(log.Logger, common.StateMachineMixin):
    implements(IJournalWriter)

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

    def close(self, flush=True):
        d = defer.succeed(None)
        if flush:
            d.addCallback(defer.drop_param, self._flush_next)
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

    def is_idle(self):
        if len(self._cache) > 0:
            return False
        return True

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
            try:
                d = self._writer.callRemote('insert_entries', entries)
                d.addCallbacks(defer.drop_param, defer.drop_param,
                               callbackArgs=(self._cache.commit, ),
                               errbackArgs=(self._cache.rollback, ))
                return d
            except pb.DeadReferenceError:
                # for some reason callRemote raises this error
                # instead of giving failed Deferred
                self._cache.rollback()

    def _set_writer(self, writer):
        self._writer = writer
        if isinstance(self._writer, pb.RemoteReference):
            self._writer.notifyOnDisconnect(self._on_disconnect)

    def _on_disconnect(self, writer):
        self._set_state(State.disconnected)
        self._set_writer(None)


class SqliteWriter(log.Logger, log.LogProxy, common.StateMachineMixin,
                   manhole.Manhole):
    implements(IJournalWriter)

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

    def close(self, flush=True):
        d = defer.succeed(None)
        if self._cmp_state(State.disconnected):
            return d
        if flush:
            d.addCallback(defer.drop_param, self._flush_next)
        d.addCallback(defer.drop_param, self._db.close)
        d.addCallback(defer.drop_param, self._uninstall_sighup)
        d.addCallback(defer.drop_param, self._set_state,
                      State.disconnected)
        return d

    @manhole.expose()
    @in_state(State.connected)
    def get_histories(self):
        return History.fetch(self._db)

    @manhole.expose()
    @in_state(State.connected)
    def get_entries(self, history, start_date=0, limit=None):
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
          WHERE entries.history_id = ?""")
        if start_date:
            command += " AND entries.timestamp >= %s" % (start_date, )
        command += " ORDER BY entries.rowid ASC"
        if limit:
            command += " LIMIT %s" % (limit, )
        d = self._db.runQuery(command, (history.history_id, ))
        d.addCallback(self._decode)
        return d

    @in_state(State.connected)
    def get_log_entries(self, start_date=None, end_date=None, filters=list()):
        '''
        @param start_date: epoch time to start search
        @param end_date: epoch time to end search
        @param filters: list of dictionaries with the following keys:
                        level - mandatory, display entries with lvl <= level
                        category - optional, limit to log_category
                        name - optional, limit to log_name
                        Leaving optional fields blank will match all the
                        entries. The entries in this list are combined with
                        OR operator.
        '''
        query = text_helper.format_block('''
        SELECT logs.message,
               logs.level,
               logs.category,
               logs.log_name,
               logs.file_path,
               logs.line_num,
               logs.timestamp
        FROM logs
        WHERE 1
        ''')
        query = self._add_timestamp_condition_sql(query, start_date, end_date)

        def transform_filter(filter):
            level = filter.get('level', None)
            category = filter.get('category', None)
            name = filter.get('name', None)
            if level is None:
                raise AttributeError("level is mandatory parameter.")
            resp = "(logs.level <= %d" % (int(level), )
            if category is not None:
                resp += " AND logs.category == '%s'" % (category, )
            if name is not None:
                resp += " AND logs.log_name == '%s'" % (name, )
            resp += ')'
            return resp

        filter_strings = map(transform_filter, filters)
        if filter_strings:
            query += " AND (%s)\n" % (' OR '.join(filter_strings), )
        d = self._db.runQuery(query)
        d.addCallback(self._decode)
        return d

    @in_state(State.connected)
    def get_log_categories(self, start_date=None, end_date=None):
        '''
        @param start_date: epoch time to start search
        @param end_date: epoch time to end search
        '''
        query = text_helper.format_block('''
        SELECT DISTINCT logs.category
        FROM logs
        WHERE 1
        ''')
        query = self._add_timestamp_condition_sql(query, start_date, end_date)
        d = self._db.runQuery(query)

        def unpack(res):
            return map(operator.itemgetter(0), res)

        d.addCallback(unpack)
        return d

    def get_log_names(self, category, start_date=None, end_date=None):
        '''
        Fetches log names for the given category.
        @param start_date: epoch time to start search
        @param end_date: epoch time to end search
        '''
        query = text_helper.format_block('''
        SELECT DISTINCT logs.log_name
        FROM logs
        WHERE category = ?
        ''')
        query = self._add_timestamp_condition_sql(query, start_date, end_date)
        d = self._db.runQuery(query, (category, ))

        def unpack(res):
            return map(operator.itemgetter(0), res)

        d.addCallback(unpack)
        return d

    def get_log_time_boundaries(self):
        '''
        @returns: a tuple of log entry timestaps (first, last) or None
        '''
        query = text_helper.format_block('''
        SELECT min(logs.timestamp),
               max(logs.timestamp)
        FROM logs''')

        def unpack(res):
            if res:
                return res[0]

        d = self._db.runQuery(query)
        d.addCallback(unpack)
        return d

    @manhole.expose()
    def insert_entries(self, entries):
        for data in entries:
            self._cache.append(data)
        return self._flush_next()

    @manhole.expose()
    def get_filename(self):
        return self._filename

    def is_idle(self):
        if len(self._cache) > 0:
            return False
        return True

    ### Private ###

    def _add_timestamp_condition_sql(self, query, start_date, end_date):
        if start_date is not None:
            query += "  AND logs.timestamp >= %d\n" % (int(start_date), )
        if end_date is not None:
            query += "  AND logs.timestamp <= %d\n" % (int(end_date), )
        return query

    def _reset_history_id_cache(self):
        # (agent_id, instance_id, ) -> history_id
        self._history_id_cache = dict()

    def _sighup_handler(self, signum, frame):
        self.log("Received SIGHUP, reopening the journal.")
        self.close()
        self.initiate()
        if callable(self._on_rotate_cb):
            self._on_rotate_cb()

    def _install_sighup(self):
        if self._sighup_installed:
            return
        if self._filename == ':memory:':
            return
        self.log('Installing SIGHUP handler.')
        signal.signal(signal.SIGHUP, self._sighup_handler)
        self._sighup_installed = True

    def _uninstall_sighup(self):
        if not self._sighup_installed:
            return

        try:
            signal.unregister(signal.SIGHUP, self._sighup_handler)
            self.log("Uninstalled SIGHUP handler.")
        except ValueError:
            self.warning("Unregistering of sighup failed. Straaange!")
        self._sighup_installed = False

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

        if data['entry_type'] == 'journal':
            to_copy = ('fiber_depth', 'instance_id', 'entry_type', 'timestamp')
            to_decode = ('agent_id', 'function_id', 'fiber_id', )
            to_blob = ('journal_id', 'args', 'kwargs', 'side_effects',
                       'result', )
        elif data['entry_type'] == 'log':
            to_copy = ('level', 'log_name', 'category', 'line_num',
                       'entry_type', 'timestamp')
            to_decode = ('file_path', )
            to_blob = ('message', )
        else:
            raise RuntimeError('Unknown entry type %r' % data['entry_type'])

        # just copy, caring open escapes
        for key in to_copy:
            result[key] = data[key]

        for key in to_decode:
            if data[key] is None:
                data[key] = ""
            result[key] = data[key].decode("utf-8")

        # encode the blobs
        for key in to_blob:
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
        if encoding == 'None':
            encoding = None
        if self._encoding is not None and encoding != self._encoding:
            self.warning("Journaler created with encoding %r but the one "
                         "loaded from existing database is %r. Using "
                         "the value of: %r",
                         self._encoding, encoding, encoding)
        self._encoding = encoding
        self._initiated_ok()

    def _create_schema(self, fail):
        fail.trap(sqlite3.OperationalError)
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
            CREATE TABLE logs (
              message BLOB,
              level INTEGER,
              category VARCHAR(36),
              log_name VARCHAR(36),
              file_path VARCHAR(200),
              line_num INTEGER,
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

        def do_insert_entry(connection, history_id, data):
            command = text_helper.format_block("""
            INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """)
            connection.execute(
                command, (history_id,
                          data['journal_id'], data['function_id'],
                          data['fiber_id'], data['fiber_depth'],
                          data['args'], data['kwargs'],
                          data['side_effects'], data['result'],
                          data['timestamp']))

        def do_insert_log(connection, data):
            command = text_helper.format_block("""
            INSERT INTO logs VALUES (?, ?, ?, ?, ?, ?, ?)
            """)
            connection.execute(
                command, (data['message'], int(data['level']),
                          data['category'], data['log_name'],
                          data['file_path'], data['line_num'],
                          data['timestamp']))

        def transaction(connection, cache):
            entries = cache.fetch()
            if not entries:
                return
            try:
                entries = map(self._encode, entries)
                for data in entries:
                    if data['entry_type'] == 'journal':
                        history_id = self._get_history_id(
                            connection, data['agent_id'], data['instance_id'])
                        do_insert_entry(connection, history_id, data)
                    elif data['entry_type'] == 'log':
                        do_insert_log(connection, data)
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
        data['entry_type'] = 'journal'
        self._journaler.insert_entry(**data)


class JournalerConnection(log.Logger, log.LogProxy):
    implements(IJournalerConnection)

    def __init__(self, journaler, externalizer):
        log.LogProxy.__init__(self, journaler)
        log.Logger.__init__(self, self)

        self.serializer = banana.Serializer(externalizer=externalizer)
        self.snapshot_serializer = banana.Serializer()
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

    def snapshot(self, agent_id, instance_id, snapshot):
        record = self.journaler.prepare_record()
        entry = AgencyJournalEntry(
            self.snapshot_serializer, record, agent_id, instance_id,
            'agency', 'snapshot', snapshot)
        entry.set_result(None)
        entry.commit()
        f = entry.get_result()
        if f:
            self.error('Error snapshoting the agent: %r. It will produce '
                       'manlformed snapshot.', f.trigger_param)


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
            'fiber_id': None,
            'fiber_depth': None,
            'side_effects': list(),
            'timestamp': int(time.time_no_sfx())}

        self._not_serialized = {
            'args': args or None,
            'kwargs': kwargs or None,
            'result': None}

    ### IJournalEntry Methods ###

    def set_fiber_context(self, fiber_id, fiber_depth):
        assert self._record is not None
        self._data['fiber_id'] = fiber_id
        self._data['fiber_depth'] = fiber_depth
        return self

    def set_result(self, result):
        assert self._record is not None
        self._not_serialized['result'] = result

    def get_result(self):
        return self._not_serialized['result']

    def new_side_effect(self, function_id, *args, **kwargs):
        assert self._record is not None
        record = []
        self._data['side_effects'].append(record)
        return AgencyJournalSideEffect(self._serializer, record,
                                       function_id, *args, **kwargs)

    def commit(self):
        try:
            self._data['args'] = self._serializer.convert(
                    self._not_serialized['args'])
            self._data['kwargs'] = self._serializer.convert(
                    self._not_serialized['kwargs'])
            self._data['result'] = self._serializer.freeze(
                    self._not_serialized['result'])
            self._data['side_effects'] = self._serializer.convert(
                    self._data['side_effects'])
            self._record.commit(**self._data)
            self._record = None
            return self
        except TypeError as e:
            self.set_result(fiber.fail(e))
            self._not_serialized['args'] = None
            self._not_serialized['kwargs'] = None
            self.commit()
