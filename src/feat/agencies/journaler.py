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
import socket
import sqlite3
import operator
import types
import sys

from zope.interface import implements
from twisted.enterprise import adbapi
from twisted.spread import pb
from twisted.python import log as twisted_log, failure

from feat.common import (log, text_helper, defer,
                         formatable, enum, decorator, time, manhole,
                         fiber, signal, error, connstr)
from feat.agencies import common
from feat.common.serialization import banana
from feat.extern.log import log as flulog

from feat.interface.journal import IJournalSideEffect, IJournalEntry
from feat.interface.serialization import IExternalizer
from feat.interface.log import ILogKeeper
from feat.agencies.interface import (IJournaler, IJournalWriter, IRecord,
                                     IJournalerConnection, IJournalReader)


class State(enum.Enum):
    '''
    disconnected - there is no connection to database
    connected - connection is ready, entries can be insterted
    '''
    (disconnected, connected) = range(2)


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
            self.debug("State now is %s, waiting to switch to: %r", self.state,
                       states)
            d.addCallback(defer.drop_param, self.wait_for_state, *states)
        d.addCallback(defer.drop_param, func, self, *args, **kwargs)
        d.addErrback(failure.Failure.trap, defer.CancelledError)
        return d

    return wrapper


class Journaler(log.Logger, common.StateMachineMixin, manhole.Manhole):
    implements(IJournaler, ILogKeeper)

    log_category = 'journaler'

    def __init__(self, on_rotate_cb=None, on_switch_writer_cb=None,
                 hostname=None):
        log.Logger.__init__(self, log.get_default() or self)

        common.StateMachineMixin.__init__(self, State.disconnected)
        self._writer = None
        self._flush_task = None
        self._cache = EntriesCache()
        self._notifier = defer.Notifier()

        self._on_rotate_cb = on_rotate_cb
        self._on_switch_writer_cb = on_switch_writer_cb
        # [(klass, params)]
        self._possible_targets = list()
        self._current_target_index = None

        self._hostname = hostname

    @property
    def possible_targets(self):
        return self._possible_targets

    @property
    def current_target_index(self):
        return self._writer is not None and self._current_target_index

    def set_connection_strings(self, con_strings):
        self.debug("set_connection_strings() called with: %r", con_strings)
        for con_str in con_strings:
            try:
                self._possible_targets.append(parse_connstr(con_str))
                self.debug("Adding journaler target: %r",
                           self._possible_targets[-1])
            except error.FeatError, e:
                error.handle_exception(None, e, 'Connection string is wrong.')
                continue
        if self._writer is None:
            return self.use_next_writer()

    def use_next_writer(self, force_index=None):
        self.debug("Will use next journaler target on the list")
        if not self._possible_targets:
            raise ValueError("_possible targets are empty")

        if force_index:
            self._current_target_index = force_index
        elif self._current_target_index is None:
            self._current_target_index = 0
        else:
            self._current_target_index += 1
            self._current_target_index %= len(self._possible_targets)

        klass, kwargs = self._possible_targets[self._current_target_index]
        kwargs['hostname'] = self._hostname

        writer = klass(logger=log.get_default(), **kwargs)
        d = self.close(flush_writer=False)
        d.addCallback(defer.drop_param, self.configure_with, writer)
        d.addCallback(defer.drop_param, writer.initiate)
        d.addCallback(defer.drop_param, self._schedule_flush)
        if callable(self._on_switch_writer_cb):
            d.addCallback(defer.drop_param, self._on_switch_writer_cb,
                          self._current_target_index)
        return d

    def reconnect_to_primary_writer(self):
        if self._current_target_index == 0:
            raise ValueError("Journaler is already using primary writer.")
        old_writer = None
        if self._writer is not None:
            old_writer = self._writer
            self._writer = None
            self._set_state(State.disconnected)
        d = self.use_next_writer(force_index=0)
        if old_writer:
            try:
                reader = IJournalReader(old_writer)
            except TypeError:
                self.error("Could not adapt writer: %r to IJournalReader "
                           "interface. Migration of entries will be skipped.",
                           old_writer)
            else:
                d.addCallback(defer.drop_param, self.migrate_entries,
                              reader)
                d.addBoth(defer.keep_param, old_writer.close)
        return d

    @defer.inlineCallbacks
    def migrate_entries(self, reader):
        self.log("Migrating entries from reader: %r", reader)
        while True:
            entries = yield reader.get_bare_journal_entries()
            if not entries:
                break
            self.log("Inserting %d journal entries", len(entries))
            yield self.insert_entries(entries)
            yield reader.delete_top_journal_entries(len(entries))

        while True:
            entries = yield reader.get_log_entries(limit=1000)
            if not entries:
                break
            self.log("Inserting %d log entries", len(entries))
            yield self.insert_entries(entries)
            yield reader.delete_top_log_entries(len(entries))

    def configure_with(self, writer):
        if not self._ensure_state(State.disconnected):
            return
        twisted_log.addObserver(self.on_twisted_log)
        self._writer = IJournalWriter(writer)
        self._writer.configure_with(self)
        self._set_state(State.connected)
        self._schedule_flush()
        self.on_rotate()

    def close(self, flush_writer=True):
        self.debug('In journaler.close(), flush_writer=%r, self.state=%r',
                   flush_writer, self.state)

        def set_disconnected():
            self._writer = None
            self._set_state(State.disconnected)

        def errback(fail):
            error.handle_failure(self, fail, "Closing journal writer failed")

        try:
            twisted_log.removeObserver(self.on_twisted_log)
        except ValueError:
            # it should be safe to call close() multiple times,
            # in this case we are not registered as the observer anymore
            pass

        d = self._close_writer(flush_writer)
        d.addErrback(errback)
        d.addBoth(defer.drop_param, set_disconnected)
        return d

    ### IJournaler ###

    def get_connection(self, externalizer):
        externalizer = IExternalizer(externalizer)
        instance = JournalerConnection(self, externalizer)
        return instance

    def prepare_record(self):
        return Record(self)

    def insert_entry(self, **data):
        self._cache.append(data)
        self._schedule_flush()
        return self._notifier.wait('flush')

    def insert_entries(self, entries):
        for entry in entries:
            self._cache.append(entry)
        self._schedule_flush()
        return self._notifier.wait('flush')

    # used by remote ProxyBrokerWriter

    remote_insert_entries = insert_entries

    def is_idle(self):
        if len(self._cache) > 0:
            self.debug("Journaler has nonempty cache, hence is not idle")
            return False
        if self._writer:
            writer_idle = self._writer.is_idle()
            self.debug("The writer (%r) is not idle, hence journaler neither",
                     self._writer)
            return writer_idle
        return True

    ### methods called by journaler writers ###

    def on_rotate(self):
        if callable(self._on_rotate_cb):
            self._on_rotate_cb()

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
            timestamp=time.time())
        self.insert_entry(**data)

    ### private ###

    def _schedule_flush(self):
        if not self._cmp_state(State.connected):
            return
        if self._flush_task is None:
            self._flush_task = time.call_next(self._flush)

    def _flush(self):
        d = defer.succeed(None)
        if not self._cmp_state(State.connected):
            d.addCallback(defer.drop_param,
                          self.wait_for_state, State.connected)
        d.addCallback(defer.drop_param, self._flush_body)
        d.addErrback(self._flush_error)
        return d

    def _flush_body(self):
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
        error.handle_failure(self, fail,
                           'Flushing entries to the writer failed')
        if self._writer:
            time.call_next(self._writer.close, flush=False)
        self._writer = None
        self._set_state(State.disconnected)
        self._flush_task = None
        time.call_next(self.use_next_writer)

    def _close_writer(self, flush_writer=True):
        d = defer.succeed(None)
        if self._writer:
            self.debug("Closing journal writer %r, flush=%r", self._writer,
                       flush_writer)
            d.addCallback(defer.drop_param, self._writer.close,
                          flush=flush_writer)
        return d


class BrokerProxyWriter(log.Logger, common.StateMachineMixin):
    implements(IJournalWriter)

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
        self._set_journaler(None)
        self._cache = EntriesCache()
        self._semaphore = defer.DeferredSemaphore(1)

    def initiate(self):
        d = self._broker.get_journaler()
        d.addCallback(self._set_journaler)
        d.addCallback(defer.drop_param, self._set_state, State.connected)
        return d

    def close(self, flush=True):
        self.debug("In BrokerProxyWriter close(), self.state=%r", self.state)
        d = defer.succeed(None)
        if flush:
            self.debug('Flushing to master agency before closing.')
            d.addCallback(defer.drop_param, self._flush_next)
        d.addCallback(defer.drop_param, self._set_state, State.disconnected)
        d.addCallback(defer.drop_param, self._set_journaler, None)
        return d

    def configure_with(self, journaler):
        pass

    def insert_entries(self, entries):
        for data in entries:
            self._cache.append(data)
        self._flush_next()
        return self._notifier.wait('flushed')

    def is_idle(self):
        if len(self._cache) > 0:
            return False
        return True

    ### private ###

    @in_state(State.connected)
    def _flush_next(self):
        if len(self._cache) == 0:
            self._notifier.callback('flushed', None)
            return defer.succeed(None)
        else:
            d = self._semaphore.run(self._push_entries)
            d.addCallback(defer.drop_param, time.call_next, self._flush_next)
            return d

    def _push_entries(self):
        entries = self._cache.fetch()
        if entries:
            try:
                d = self._journaler.callRemote('insert_entries', entries)
                d = defer.Timeout(2, d, message=("Timeout expired "
                                                 "pushing entries to master."))
                d.addCallbacks(defer.drop_param, defer.drop_param,
                               callbackArgs=(self._cache.commit, ),
                               errbackArgs=(self._cache.rollback, ))
                return d
            except pb.DeadReferenceError:
                # for some reason callRemote raises this error
                # instead of giving failed Deferred
                self._cache.rollback()

    def _set_journaler(self, journaler):
        self._journaler = journaler
        if isinstance(self._journaler, pb.RemoteReference):
            self._journaler.notifyOnDisconnect(self._on_disconnect)

    def _on_disconnect(self, writer):
        self._set_state(State.disconnected)
        self._set_journaler(None)


class SqliteWriter(log.Logger, log.LogProxy, common.StateMachineMixin):


    implements(IJournalWriter, IJournalReader)

    def __init__(self, logger, filename=":memory:", encoding=None,
                 hostname=None):
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
        self._hostname = hostname
        self._reset_history_id_cache()
        self._cache = EntriesCache()
        # the semaphore is used to always have at most running
        # .perform_instert() method
        self._semaphore = defer.DeferredSemaphore(1)

        self._sighup_installed = False

        self._journaler = None

    def initiate(self):
        self.debug("Initiating sqlite journal writer.")
        self._db = adbapi.ConnectionPool('sqlite3', self._filename,
                                         cp_min=1, cp_max=1, cp_noisy=True,
                                         check_same_thread=False,
                                         timeout=10)
        self._install_sighup()
        return self._check_schema()

    def close(self, flush=True):
        d = defer.succeed(None)
        if self._cmp_state(State.disconnected):
            self.debug("Writer is already disconnected.")
            return d
        if flush:
            self.debug("Flusing SQL writer before closign")
            d.addCallback(defer.drop_param, self._flush_next)
        d.addCallback(defer.drop_param, self._db.close)
        d.addCallback(defer.drop_param, self._uninstall_sighup)
        d.addCallback(defer.drop_param, self._set_state,
                      State.disconnected)
        d.addCallback(defer.drop_param,
                      self._notifier.cancel, State.connected)
        return d

    ### IJournalReader ###

    @in_state(State.connected)
    def get_histories(self):

        def parse(rows):
            return [History(history_id=x[0], agent_id=x[1], instance_id=x[2],
                            hostname=self._hostname)
                    for x in rows]

        d = self._db.runQuery(
            "SELECT id, agent_id, instance_id FROM histories")
        d.addCallback(parse)
        return d

    @in_state(State.connected)
    def get_bare_journal_entries(self, limit=1000):
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
          ORDER BY entries.timestamp ASC
          LIMIT ?""")
        d = self._db.runQuery(command, (limit, ))
        d.addCallback(self._decode, entry_type='journal')
        return d

    @in_state(State.connected)
    def delete_top_journal_entries(self, num):
        command = text_helper.format_block("""
        DELETE FROM entries
        WHERE id IN (
           SELECT id FROM entries
           ORDER BY timestamp, rowid
           LIMIT ?)
        """)
        return self._db.runQuery(command, (num, ))

    @in_state(State.connected)
    def get_entries(self, history, start_date=0, limit=None):
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
        d.addCallback(self._decode, entry_type='journal')
        return d

    @in_state(State.connected)
    def get_log_entries(self, start_date=None, end_date=None, filters=list(),
                        limit=None):
        '''
        See feat.agencies.interface.IJournalReader.get_log_entres
        '''
        query = text_helper.format_block('''
        SELECT "localhost",
               logs.message,
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
        query += " ORDER BY logs.timestamp, rowid"
        if limit:
            query += " LIMIT %s" % (limit, )

        d = self._db.runQuery(query)
        d.addCallback(self._decode, entry_type='log')
        return d

    @in_state(State.connected)
    def delete_top_log_entries(self, num):
        command = text_helper.format_block("""
        DELETE FROM logs
        WHERE id IN (
           SELECT id FROM logs
           ORDER BY timestamp, rowid
           LIMIT ?)
        """)
        return self._db.runQuery(command, (num, ))

    @in_state(State.connected)
    def get_log_hostnames(self, start_date=None, end_date=None):
        return [self._hostname]

    @in_state(State.connected)
    def get_log_categories(self, start_date=None, end_date=None,
                           hostname=None):
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

    def get_log_names(self, category, hostname=None,
                      start_date=None, end_date=None):
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

    ### IJournalWriter ###

    def configure_with(self, journaler):
        self.log("configure_with() called. journaler=%r", journaler)
        if self._journaler:
            self.warning("We already have a journaler reference, substituing")
        self._journaler = journaler

    def insert_entries(self, entries):
        for data in entries:
            self._cache.append(data)
        return self._flush_next()

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
        self.debug("Received SIGHUP, reopening the journal.")
        if self._journaler:
            time.call_next(self._journaler.on_rotate)
        self.close()
        self.initiate()

    def _install_sighup(self):
        if self._sighup_installed:
            return
        if self._filename == ':memory:':
            return
        self.debug('Installing SIGHUP handler.')
        signal.signal(signal.SIGHUP, self._sighup_handler)
        self._sighup_installed = True

    def _uninstall_sighup(self):
        if not self._sighup_installed:
            return

        try:
            signal.unregister(signal.SIGHUP, self._sighup_handler)
            self.debug("Uninstalled SIGHUP handler.")
        except ValueError:
            self.warning("Unregistering of sighup failed. Straaange!")
        self._sighup_installed = False

    def _decode(self, entries, entry_type):
        '''
        Takes the list of rows returned by sqlite.
        Returns rows in readable format. Transforms tuples into dictionaries,
        and appends information about entry type to the rows.
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

        decoded = map(decode_blobs, entries)
        if entry_type == 'log':
            mapping = ['hostname', 'message', 'level', 'category',
                       'log_name', 'file_path', 'line_num', 'timestamp']
        elif entry_type == 'journal':
            mapping = ['agent_id', 'instance_id', 'journal_id', 'function_id',
                       'fiber_id', 'fiber_depth', 'args', 'kwargs',
                       'side_effects', 'result', 'timestamp']
        else:
            raise ValueError('Unknown entry_type %r' % (entry_type, ))

        def parse(row, mapping, entry_type):
            resp = dict(zip(mapping, row))
            resp['entry_type'] = entry_type
            return resp

        parsed = [parse(row, mapping, entry_type) for row in decoded]
        return parsed

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
                try:
                    safe = safe.encode(self._encoding)
                except UnicodeEncodeError:
                    try:
                        safe = safe.encode('ascii', 'replace')
                        safe = safe.encode(self._encoding)
                    except UnicodeEncodeError:
                        self.error("Encoding to ascii with replace didn't "
                                   "help either. Skipping this piece of data "
                                   "in the journal")
                        safe = "".encode(self._encoding)

            result[key] = sqlite3.Binary(safe)

        return result

    def _check_schema(self):
        d = self._db.runQuery(
            'SELECT value FROM metadata WHERE name = "encoding"')
        d.addCallbacks(self._got_encoding, self._create_schema)
        d.addCallback(defer.drop_param, self._load_hostname)
        d.addCallback(defer.drop_param, self._initiated_ok)
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

    def _load_hostname(self):

        def callback(res):
            try:
                hostname = res[0][0]
            except IndexError:
                hostname = 'unknown'
            self._hostname = hostname

        d = self._db.runQuery(
            'SELECT value FROM metadata WHERE name = "hostname"')
        d.addCallback(callback)
        return d

    def _create_schema(self, fail):
        fail.trap(sqlite3.OperationalError)
        commands = [
            text_helper.format_block("""
            CREATE TABLE entries (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
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
              id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                self.debug('Executing command:\n %s', command)
                connection.execute(command)

        insert_meta = "INSERT INTO metadata VALUES('%s', '%s')"
        commands += [insert_meta % (u'encoding', self._encoding, )]

        hostname = self._hostname
        if hostname is None:
            self.warning("SqliteWriter initialized without hostname, "
                         "falling back to value from socket.gethostname()")
            hostname = socket.gethostname()
        commands += [insert_meta % (u'hostname', hostname, )]

        self._reset_history_id_cache()

        d = self._db.runWithConnection(run_all, commands)
        d.addErrback(lambda fail: error.handle_failure(
            self, fail, 'Failed running commands'))
        return d

    def _initiated_ok(self, *_):
        self.debug('Sqlite journal writer initiated correctly for the '
                   'filename %r', self._filename)
        self._set_state(State.connected)
        return self._flush_next()

    def _perform_inserts(self, cache):

        def do_insert_entry(connection, history_id, data):
            command = text_helper.format_block("""
            INSERT INTO entries VALUES (null, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """)
            connection.execute(
                command, (history_id,
                          data['journal_id'], data['function_id'],
                          data['fiber_id'], data['fiber_depth'],
                          data['args'], data['kwargs'],
                          data['side_effects'], data['result'],
                          int(data['timestamp'])))

        def do_insert_log(connection, data):
            command = text_helper.format_block("""
            INSERT INTO logs VALUES (null, ?, ?, ?, ?, ?, ?, ?)
            """)
            connection.execute(
                command, (data['message'], int(data['level']),
                          data['category'], data['log_name'],
                          data['file_path'], data['line_num'],
                          int(data['timestamp'])))

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
    formatable.field('hostname', None)


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
            'timestamp': time.time()}

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


class PostgresWriter(log.Logger, log.LogProxy, common.StateMachineMixin,
                     manhole.Manhole):

    implements(IJournalWriter)

    max_retries = 2
    max_delay = 120
    initial_delay = 1

    def __init__(self, logger, host, database, user, password,
                 max_retries=None, initial_delay=None, max_delay=None,
                 hostname=None):
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, logger)
        common.StateMachineMixin.__init__(self, State.disconnected)

        # lazy import not to require psycopg2 and txpostgres
        # packages if the writer is not used
        from txpostgres import txpostgres
        import psycopg2
        self._txpostgres = txpostgres
        self._psycopg2 = psycopg2

        self._credentials = dict(host=host, user=user,
                                 password=password, database=database)

        self._cache = EntriesCache()
        self._db = None

        self._retry = None

        self._max_delay = max_delay or type(self).max_delay
        self._max_retries = max_retries or type(self).max_retries
        self._initial_delay = initial_delay or type(self).initial_delay

        self._journaler = None
        self._initiate_defer = None
        self._should_giveup = False

        if hostname is None:
            hostname = socket.gethostname()
            self.warning("Postgres writer was initialized without passing "
                         "the hostname. Falling back to: %s", hostname)
        self._hostname = hostname

    def initiate(self):
        self._should_giveup = False
        self._db = self._txpostgres.ConnectionPool(
            "postgres", min=1, **self._credentials)

        if self._retry is not None:
            self._retry += 1
        else:
            self._retry = 1
            self._delay = self._initial_delay

        d = self._db.start()
        # run simple query to make sure schema is loaded
        d.addCallback(defer.drop_param, self._db.runQuery,
                      'SELECT message FROM feat.logs LIMIT 1')
        d.addCallback(self._connection_established)
        d.addErrback(self._connection_failed)
        self._initiate_defer = d
        return d

    def close(self, flush=True):
        self._should_giveup = True
        if self._initiate_defer:
            self._initiate_defer.cancel()
        d = defer.succeed(None)
        if flush and not self._cmp_state(State.disconnected):
            d.addCallback(defer.drop_param, self._flush_next)
        if self._db:
            db = self._db
            self._db = None
            d.addCallback(defer.drop_param, db.close)
        d.addCallback(defer.drop_param, self._set_state,
                      State.disconnected)
        d.addCallback(defer.drop_param,
                      self._notifier.cancel, State.connected)
        return d

    ### Used by model ###

    @property
    def host(self):
        return self._credentials['host']

    @property
    def dbname(self):
        return self._credentials['database']

    @property
    def user(self):
        return self._credentials['user']

    @property
    def password(self):
        return self._credentials['password']

    ### IJournalWriter ###

    def configure_with(self, journaler):
        self.log("configure_with() called. journaler=%r", journaler)
        if self._journaler:
            self.warning("We already have a journaler reference, substituing")
        self._journaler = journaler

    @manhole.expose()
    def insert_entries(self, entries):
        for data in entries:
            self._cache.append(data)
        return self._flush_next()

    def is_idle(self):
        if len(self._cache) > 0:
            return False
        return True

    ### private ###

    def _connection_established(self, _ignored):
        self._retry = None
        del(self._delay)
        self._initiate_defer = None

        self.log("Connection established to postgres database.")
        self._set_state(State.connected)
        return self._flush_next()

    def _connection_failed(self, fail):
        self._delay = min([self._max_delay, self._delay * 2])

        self.warning("Connection to postgres failed with credentials: %r. "
                     "Failure: %r. ", self._credentials, fail)
        if self._db:
            self._db.close()
            self._db = None
        if self._should_giveup or self._retry + 1 > self._max_retries:
            error.handle_failure(self, fail,
                                 "Giving up connecting to postgres. ")
            self._notifier.cancel(State.connected)
            return

        self.info("Will retry for %d time in %d seconds.",
                  self._retry, self._delay)
        time.call_later(self._delay, self.initiate)

    @in_state(State.connected)
    def _flush_next(self):
        if len(self._cache) == 0:
            return defer.succeed(None)
        else:
            d = self._db.runInteraction(self._perform_inserts)
            d.addCallback(defer.drop_param, self._flush_next)
            return d

    def _perform_inserts(self, cursor):
        entries = self._cache.fetch()
        if not entries:
            return

        d = defer.succeed(None)
        for data in entries:
            if data['entry_type'] == 'journal':
                d.addCallback(defer.drop_param,
                              self._do_insert_entry, cursor, data)
            elif data['entry_type'] == 'log':
                d.addCallback(defer.drop_param, self._do_insert_log,
                              cursor, data)
        d.addCallback(defer.bridge_param, self._cache.commit)
        d.addErrback(defer.bridge_param, self._cache.rollback)
        return d

    def _do_insert_entry(self, cursor, data):

        def escape(binary):
            if isinstance(binary, unicode):
                binary = binary.encode('utf8')
            return self._psycopg2.Binary(binary)

        return cursor.execute(
            'INSERT INTO feat.entries '
            '(agent_id, instance_id, journal_id, function_id, fiber_id,'
            ' fiber_depth, args, kwargs, side_effects, result, timestamp,'
            ' host_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,'
                     'feat.host_id_for(%s))',
            (data['agent_id'],
             data['instance_id'],
             escape(data['journal_id']),
             data['function_id'],
             escape(data['fiber_id']),
             data['fiber_depth'],
             escape(data['args']),
             escape(data['kwargs']),
             escape(data['side_effects']),
             escape(data['result']),
             self._format_timestamp(data['timestamp']),
             self._hostname))

    def _do_insert_log(self, cursor, data):
        return cursor.execute(
            'INSERT INTO feat.logs '
            '(message, level, category, log_name, file_path, line_num,'
            ' timestamp, host_id) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, feat.host_id_for(%s))',
            (data['message'], int(data['level']),
             data['category'], data['log_name'],
             data['file_path'], data['line_num'],
             self._format_timestamp(data['timestamp']),
             self._hostname))

    def _format_timestamp(self, epoch):
        t = time.strftime("%Y/%m/%d %H:%M:%S", time.localtime(epoch))
        t += str(epoch % 1)[1:]
        return t


class PostgresReader(log.Logger, log.LogProxy, common.StateMachineMixin,
                     manhole.Manhole):

    implements(IJournalReader)

    max_retries = 2
    max_delay = 120
    initial_delay = 1

    def __init__(self, logger, host, database, user, password):
        log.LogProxy.__init__(self, logger)
        log.Logger.__init__(self, logger)
        common.StateMachineMixin.__init__(self, State.disconnected)

        from txpostgres import txpostgres
        import psycopg2
        self._txpostgres = txpostgres
        self._psycopg2 = psycopg2

        self._credentials = dict(host=host, user=user,
                                 password=password, database=database)

        self._db = None
        self._error = None
        self._initiate_defer = None

    def initiate(self):
        self._db = self._txpostgres.ConnectionPool(
            "postgres", min=1, **self._credentials)
        d = self._db.start()
        # run simple query to make sure schema is loaded
        d.addCallback(defer.drop_param, self._db.runQuery,
                      'SELECT message FROM feat.logs LIMIT 1')
        d.addCallback(defer.drop_param, self._connection_established)
        d.addErrback(self._connection_failed)
        self._initiate_defer = d
        return d

    def close(self):
        if self._initiate_defer:
            self._initiate_defer.cancel()
            self._initiate_defer = None
        if self._db:
            self._db.close()
            self._db.close()
        self._set_state(State.disconnected)

    ### IJournalReader ###

    def get_histories(self):
        if not self._ensure_state(State.connected):
            return

        def parse(rows):
            return [History(agent_id=x[0],
                            instance_id=x[1],
                            hostname=x[2]) for x in rows]

        d = self._db.runQuery(
            "SELECT entries.agent_id, entries.instance_id, "
                    "hosts.hostname, min(entries.id) min_id FROM feat.entries"
            "  LEFT JOIN feat.hosts ON entries.host_id = hosts.id"
            "  GROUP BY entries.agent_id, entries.instance_id, hosts.hostname"
            "  ORDER BY min_id")
        d.addCallback(parse)
        return d

    def get_bare_journal_entries(self, limit=1000):
        if not self._ensure_state(State.connected):
            return

        command = text_helper.format_block("""
        SELECT agent_id, instance_id, journal_id, function_id, fiber_id,
               fiber_depth, args, kwargs, side_effects, result,
               date_part('epoch', timestamp)
          FROM feat.entries
          ORDER BY timestamp, id
          LIMIT %s""")
        d = self._db.runQuery(command, (limit, ))
        d.addCallback(self._decode, entry_type='journal')
        return d

    def delete_top_journal_entries(self, num):
        if not self._ensure_state(State.connected):
            return

        command = text_helper.format_block("""
        DELETE FROM feat.entries
        WHERE id IN (
           SELECT id FROM feat.entries
           ORDER BY timestamp, id
           LIMIT %s)
        """)
        return self._db.runOperation(command, (num, ))

    def get_entries(self, history, start_date=0, limit=None):
        if not self._ensure_state(State.connected):
            return

        if not isinstance(history, History):
            raise AttributeError(
                'First paremeter is expected to be History instance, got %r'
                % history)

        command = text_helper.format_block("""
        SELECT agent_id, instance_id, journal_id, function_id, fiber_id,
               fiber_depth, args, kwargs, side_effects, result,
               date_part('epoch', timestamp)
          FROM feat.entries
          WHERE agent_id = %s AND instance_id = %s""")
        params = (history.agent_id, history.instance_id)
        if start_date:
            command += " AND date_part('epoch', timestamp) >= %s"
            params += (start_date, )

        command += " ORDER BY timestamp, entries.id"
        if limit:
            command += " LIMIT %s"
            params += (limit, )
        d = self._db.runQuery(command, params)
        d.addCallback(self._decode, entry_type='journal')
        return d

    def get_log_hostnames(self, start_date=None, end_date=None):
        query = "SELECT hostname FROM feat.hosts WHERE true"
        query, params = self._add_timestamp_condition_sql(
            query, tuple(), start_date, end_date)
        d = self._db.runQuery(query, params)

        def unpack(res):
            return map(operator.itemgetter(0), res)

        d.addCallback(unpack)
        return d

    def get_log_entries(self, start_date=None, end_date=None, filters=list(),
                        limit=None):
        if not self._ensure_state(State.connected):
            return


        query = text_helper.format_block("""
        SELECT hosts.hostname, message, level, category, log_name,
               file_path, line_num, date_part('epoch', timestamp)
          FROM feat.logs
          LEFT JOIN feat.hosts ON logs.host_id = hosts.id
          WHERE true
        """)
        query, params = self._add_timestamp_condition_sql(
            query, tuple(), start_date, end_date)

        def transform_filter(filter):
            params = tuple()

            level = filter.get('level', None)
            category = filter.get('category', None)
            name = filter.get('name', None)
            hostname = filter.get('hostname', None)
            if level is None:
                raise AttributeError("level is mandatory parameter.")
            resp = "(level <= %s"
            params += (level, )
            if hostname is not None:
                resp += " AND hosts.hostname = %s"
                params += (hostname, )
            if category is not None:
                resp += " AND category = %s"
                params += (category, )
            if name is not None:
                resp += " AND log_name = %s"
                params += (name, )
            resp += ')'
            return resp, params

        parsed_filters = map(transform_filter, filters)
        if parsed_filters:
            filter_strings = [x[0] for x in parsed_filters]
            query += " AND (" + ' OR '.join(filter_strings) + ')'
            filter_params = [x[1] for x in parsed_filters]
            params += reduce(lambda x, y: x + y, filter_params)
        if limit:
            query += " LIMIT %s"
            params += (limit, )
        query += " ORDER BY timestamp, logs.id"
        d = self._db.runQuery(query, params)
        d.addCallback(self._decode, entry_type='log')
        return d

    def delete_top_log_entries(self, num):
        if not self._ensure_state(State.connected):
            return

        command = text_helper.format_block("""
        DELETE FROM feat.logs
        WHERE id IN (
           SELECT id FROM feat.logs
           ORDER BY timestamp, logs.id
           LIMIT %s)
        """)
        return self._db.runOperation(command, (num, ))

    def get_log_categories(self, start_date=None, end_date=None,
                           hostname=None):
        if not self._ensure_state(State.connected):
            return

        query = text_helper.format_block("""
        SELECT DISTINCT category FROM feat.logs
          LEFT JOIN feat.hosts ON logs.host_id = hosts.id
          WHERE true""")
        params = tuple()
        if hostname:
            query += " AND hosts.hostname = %s"
            params += (hostname, )
        query, params = self._add_timestamp_condition_sql(
            query, params, start_date, end_date)
        d = self._db.runQuery(query, params)

        def unpack(res):
            return map(operator.itemgetter(0), res)

        d.addCallback(unpack)
        return d

    def get_log_names(self, category, hostname=None,
                      start_date=None, end_date=None):
        query = text_helper.format_block("""
        SELECT DISTINCT log_name FROM feat.logs
          LEFT JOIN feat.hosts ON logs.host_id = hosts.id
          WHERE category = %s""")
        params = (category, )
        if hostname:
            query += " AND hosts.hostname = %s"
            params += (hostname, )
        query, params = self._add_timestamp_condition_sql(
            query, params, start_date, end_date)
        d = self._db.runQuery(query, params)

        def unpack(res):
            return map(operator.itemgetter(0), res)

        d.addCallback(unpack)
        return d

    def get_log_time_boundaries(self):
        '''
        @returns: a tuple of log entry timestaps (first, last) or None
        '''
        query = text_helper.format_block("""
        SELECT min(date_part('epoch', timestamp)),
               max(date_part('epoch', timestamp))
        FROM feat.logs""")
        d = self._db.runQuery(query)
        d.addCallback(operator.itemgetter(0))
        return d

    ### private helper used by querying functions ###

    def _decode(self, entries, entry_type):
        '''
        Takes the list of rows returned by postgres.
        Returns rows in readable format. Transforms tuples into dictionaries,
        and appends information about entry type to the rows.
        '''

        def decode_blobs(row):
            row = list(row)
            for index, value in zip(range(len(row)), row):
                if isinstance(value, types.BufferType):
                    value = str(value)
                    row[index] = value
            return row

        decoded = map(decode_blobs, entries)
        if entry_type == 'log':
            mapping = ['hostname', 'message', 'level', 'category',
                       'log_name', 'file_path', 'line_num', 'timestamp']
        elif entry_type == 'journal':
            mapping = ['agent_id', 'instance_id', 'journal_id', 'function_id',
                       'fiber_id', 'fiber_depth', 'args', 'kwargs',
                       'side_effects', 'result', 'timestamp']
        else:
            raise ValueError('Unknown entry_type %r' % (entry_type, ))

        def parse(row, mapping, entry_type):
            resp = dict(zip(mapping, row))
            resp['entry_type'] = entry_type
            return resp

        parsed = [parse(row, mapping, entry_type) for row in decoded]
        return parsed

    def _add_timestamp_condition_sql(self, query, params,
                                     start_date, end_date):
        if start_date is not None:
            query += "  AND date_part('epoch', timestamp) >= %s\n"
            params += (start_date, )
        if end_date is not None:
            query += "  AND date_part('epoch', timestamp) <= %s"
            params += (end_date, )
        return query, params

    ### callbacks for initiate() ###

    def _connection_failed(self, fail):
        error.handle_failure(self, fail, "Connecting to postgres %r failed",
                             self._credentials)
        self._error = fail

    def _connection_established(self):
        self._initiate_defer = None
        self._set_state(State.connected)


def parse_connstr(conn):
    try:
        resp = connstr.parse(conn)
        if resp['protocol'] == 'sqlite':
            klass = SqliteWriter
            params = dict(filename=resp['host'], encoding='zip')
        elif resp['protocol'] == 'postgres':
            klass = PostgresWriter
            host, dbname = resp['host'].split('/')
            params = dict(host=host, database=dbname,
                          password=resp['password'], user=resp['user'],
                          max_retries=3)
        else:
            raise ValueError("Unknown protocol")
        return klass, params
    except ValueError as e:
        raise error.FeatError("%s is not a valid connection string" % (conn, ),
                              cause=e), None, sys.exc_info()[2]
