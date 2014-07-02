#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2007-2008 Christopher Lenz
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

"""Implementation of a view server for functions written in Python."""

from codecs import BOM_UTF8

import logging
import os
import sys
import traceback
from types import FunctionType

from . import json

__all__ = ['main', 'run']
__docformat__ = 'restructuredtext en'

log = logging.getLogger('couchdb.view')


class CompileError(Exception):
    pass


def run(input=sys.stdin, output=sys.stdout):
    r"""CouchDB view function handler implementation for Python.

    :param input: the readable file-like object to read input from
    :param output: the writable file-like object to write output to
    """
    functions = []
    environments = dict()

    def _writejson(obj):
        obj = json.encode(obj)
        if isinstance(obj, unicode):
            obj = obj.encode('utf-8')
        output.write(obj)
        output.write('\n')
        output.flush()

    def _log(message):
        if not isinstance(message, basestring):
            message = json.encode(message)
        _writejson({'log': message})

    def reset(config=None):
        del functions[:]
        return True

    def add_fun(string):
        string = BOM_UTF8 + string.encode('utf-8')
        try:
            function = _compile(string, "map_compilation_error", "map")
        except CompileError as e:
            return e.args[0]
        functions.append(function)
        return True

    def map_doc(doc):
        results = []
        for function in functions:
            try:
                results.append([[key, value] for key, value in function(doc)])
            except Exception, e:
                log.error('runtime error in map function: %s', e,
                          exc_info=True)
                results.append([])
                _log(traceback.format_exc())
        return results

    def reduce(*cmd, **kwargs):
        code = BOM_UTF8 + cmd[0][0].encode('utf-8')
        args = cmd[1]

        try:
            function = _compile(code, "reduce_compilation_error", "reduce")
        except CompileError as e:
            return e.args[0]

        rereduce = kwargs.get('rereduce', False)
        results = []
        if rereduce:
            keys = None
            vals = args
        else:
            if args:
                keys, vals = zip(*args)
            else:
                keys = []
                vals = []
        if function.func_code.co_argcount == 3:
            results = function(keys, vals, rereduce)
        else:
            results = function(keys, vals)
        return [True, [results]]

    def rereduce(*cmd):
        # Note: weird kwargs is for Python 2.5 compat
        return reduce(*cmd, **{'rereduce': True})

    def ddoc_new(name, doc):
        env = dict()
        # key in design doc -> expected function name
        method_mapping = dict(filters='filter', views='map')
        for key, section in doc.iteritems():
            if key not in method_mapping:
                continue
            env[key] = dict()
            id_error = "%s_compilation_error" % (key)
            for f_name, func_str in section.iteritems():
                if isinstance(func_str, dict):
                    env[key][f_name] = dict()
                    for expected_name, code in func_str.iteritems():
                        try:
                            env[key][f_name][expected_name] = _compile(
                                code, id_error, expected_name)
                        except CompileError as e:
                            return e.args[0]
                else:
                    try:
                        expected_name = method_mapping[key]
                        env[key][f_name] = _compile(func_str, id_error,
                                                    expected_name)
                    except CompileError as e:
                        return e.args[0]
        environments[name] = env
        return True

    def ddoc_exec(ddoc_name, ref, args):
        e = environments[ddoc_name]
        for r in ref:
            e = e[r]
        function = e
        h = handlers[ref[0]]

        return h(*args, **{"function": function})

    def ddoc(*args):
        args = list(args)
        n = args.pop(0)
        if n == 'new':
            return ddoc_new(*args)
        return ddoc_exec(n, args.pop(0), args[0])

    def filter(rows, request, dbinfo=None, function=None):
        request['db'] = dbinfo
        results = []

        for row in rows:
            r = function(row, request)
            if r is True:
                results.append(True)
            else:
                results.append(False)

        return [True, results]

    def filter_view(rows, function=None):
        results = []

        for row in rows:
            r = function(row)
            try:
                r.next()
                results.append(True)
            except StopIteration:
                results.append(False)

        return [True, results]

    def _compile(func_str, error_id, f_name):
        globals_ = {}

        if func_str in ('_count', '_sum', '_stats'):
            # These are builtins which are not ment to be complited
            # by the python server
            return func_str

        try:
            exec func_str in {'log': _log}, globals_
        except Exception, e:
            log.error('runtime error in filter function: %s', e,
                      exc_info=True)
            raise CompileError({'error': {
                'id': error_id,
                'reason': e.args[0]}})
        err = {'error': {
            'id': error_id,
            'reason': ('string must eval to a function named %(f_name)s '
                       '(ex: "def %(f_name)s(doc, request): return True")' %
                       dict(f_name=f_name))}}
        if f_name not in globals_:
            raise CompileError(err)
        function = globals_.pop(f_name)
        if type(function) is not FunctionType:
            raise CompileError(err)
        # merge in remaining globals so that they are available in the function
        function.func_globals.update(globals_)
        return function


    handlers = {'reset': reset, 'add_fun': add_fun, 'map_doc': map_doc,
                'reduce': reduce, 'rereduce': rereduce, 'ddoc': ddoc,
                'filters': filter, 'views': filter_view}

    try:
        while True:
            line = input.readline()
            if not line:
                break
            try:
                cmd = json.decode(line)
                log.debug('Processing %r', cmd)
            except ValueError, e:
                log.error('Error: %s', e, exc_info=True)
                return 1
            else:
                retval = handlers[cmd[0]](*cmd[1:])
                log.debug('Returning  %r', retval)
                _writejson(retval)
    except KeyboardInterrupt:
        return 0
    except Exception, e:
        log.error('Error: %s', e, exc_info=True)
        return 1


_VERSION = """%(name)s - CouchDB Python %(version)s

Copyright (C) 2007 Christopher Lenz <cmlenz@gmx.de>.
"""

_HELP = """Usage: %(name)s [OPTION]

The %(name)s command runs the CouchDB Python view server.

The exit status is 0 for success or 1 for failure.

Options:

  --version             display version information and exit
  -h, --help            display a short help message and exit
  --json-module=<name>  set the JSON module to use ('simplejson', 'cjson',
                        or 'json' are supported)
  --log-file=<file>     name of the file to write log messages to, or '-' to
                        enable logging to the standard error stream
  --debug               enable debug logging; requires --log-file to be
                        specified

Report bugs via the web at <http://code.google.com/p/couchdb-python>.
"""


def main():
    """Command-line entry point for running the view server."""
    import getopt
    from . import __version__ as VERSION

    try:
        option_list, argument_list = getopt.gnu_getopt(
            sys.argv[1:], 'h',
            ['version', 'help', 'json-module=', 'debug', 'log-file='])

        message = None
        for option, value in option_list:
            if option in ('--version'):
                message = _VERSION % dict(name=os.path.basename(sys.argv[0]),
                                      version=VERSION)
            elif option in ('-h', '--help'):
                message = _HELP % dict(name=os.path.basename(sys.argv[0]))
            elif option in ('--json-module'):
                json.use(module=value)
            elif option in ('--debug'):
                log.setLevel(logging.DEBUG)
            elif option in ('--log-file'):
                if value == '-':
                    handler = logging.StreamHandler(sys.stderr)
                    handler.setFormatter(logging.Formatter(
                        ' -> [%(levelname)s] %(message)s'))
                else:
                    handler = logging.FileHandler(value)
                    handler.setFormatter(logging.Formatter(
                        '[%(asctime)s] [%(levelname)s] %(message)s'))
                log.addHandler(handler)
        if message:
            sys.stdout.write(message)
            sys.stdout.flush()
            sys.exit(0)

    except getopt.GetoptError, error:
        message = '%s\n\nTry `%s --help` for more information.\n' % (
            str(error), os.path.basename(sys.argv[0]))
        sys.stderr.write(message)
        sys.stderr.flush()
        sys.exit(1)

    sys.exit(run())


if __name__ == '__main__':
    main()
