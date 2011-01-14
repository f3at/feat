# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import re
import traceback
import shlex
from functools import partial

from twisted.internet import defer
from feat.common import decorator, annotate, enum, log, error_handler


class SecurityLevel(enum.Enum):
    """
    safe - should be used to expose querying commands which
           will not mess up with the state
    unsafe - should be for the operations which require a bit of thinking
    superhuman - should not be used, but does it mean we shouldn't have it?
    """

    (safe, unsafe, superhuman, ) = range(3)


@decorator.parametrized_function
def expose(function, security_level=SecurityLevel.safe):
    annotate.injectClassCallback("recorded", 4,
                                 "_register_exposed", function,
                                 security_level)

    return function


class Manhole(annotate.Annotable):

    _exposed = None

    @classmethod
    def _register_exposed(cls, function, security_level):
        if cls._exposed is None:
            cls._exposed = dict()
        for lvl in SecurityLevel:
            if lvl > security_level:
                continue
            fun_id = function.__name__
            if lvl not in cls._exposed:
                cls._exposed[lvl] = dict()
            cls._exposed[lvl][fun_id] = function

    def get_exposed_cmds(self, lvl=SecurityLevel.safe):
        if self._exposed is None or lvl not in self._exposed:
            return list()
        else:
            return self._exposed[lvl].values()

    def lookup_cmd(self, name, lvl=SecurityLevel.safe):
        if self._exposed is None or lvl not in self._exposed or\
                                            name not in self._exposed[lvl]:
            raise UnknownCommand('Unknown command: %s.%s' %\
                                 (self.__class__.__name__, name, ))
        return partial(self._exposed[lvl][name], self)


class Parser(log.Logger):

    log_category = 'command-parser'

    def __init__(self, driver, output, commands, cb_on_finish=None):
        log.Logger.__init__(self, driver)

        self.cb_on_finish = cb_on_finish
        self.commands = commands
        self.buffer = ""
        self.output = output
        self._locals = dict()
        self._last_line = None
        self.re = dict(
            assignment=re.compile('\A(\w+)\s*=\s*(\S.*)'),
            number=re.compile('\A\d+(\.\d+)?\Z'),
            none=re.compile('\ANone\Z'),
            string=re.compile('\A\'([^(?<!\)\']*)\'\Z'),
            call=re.compile('\A(\w+)\((.*)\)\Z'),
            variable=re.compile('\A([^\(\)\'\"\s\+]+)\Z'),
            method_call=re.compile('\A(\w+)\.(\w+)\((.*)\)\Z'))

    def split(self, text):
        s = shlex.shlex(text, posix=False)
        s.whitespace += ','
        s.wordchars += '.'
        s.whitespace_split = False
        splitted = list(s)
        try:
            while True:
                index = splitted.index(')')
                while True:
                    item = splitted[index]
                    previous = splitted.pop(index - 1)
                    if previous == '(':
                        item = previous + item
                        command = splitted.pop(index - 2)
                        splitted[index - 2] = command + item
                        break
                    elif item == ')':
                        item = previous + item
                    else:
                        item = previous + ', ' + item
                    splitted[index - 1] = item
                    index -= 1
                    if index < 0:
                        raise BadSyntax('Syntax error processing line: %s' %\
                            self._last_line)

        except ValueError:
            return splitted

    def dataReceived(self, data):
        self.buffer += data
        self.process_line()

    def send_output(self, data):
        if data is not None:
            self.output.write(str(data) + "\n")

    def get_line(self):
        try:
            index = self.buffer.index("\n")
            line = self.buffer[0:index]
            self.buffer = self.buffer[(index + 1):]
            return line
        except ValueError:
            return None

    def process_line(self):
        line = self.get_line()
        if line is not None:
            self._last_line = line
            self.debug('Processing line: %s', line)
            if not re.search('\w', line):
                self.log('Empty line')
                return self.process_line()

            assignment = self.re['assignment'].search(line)
            if assignment:
                variable_name = assignment.group(1)
                line = assignment.group(2)

            d = defer.maybeDeferred(self.split, line)
            d.addCallback(self.process_array)
            d.addCallback(self.validate_result)
            if assignment:
                d.addCallback(self.set_local, variable_name)
            d.addCallback(self.send_output)
            d.addCallbacks(lambda _: self.process_line(), self._error_handler)
        else:
            self.on_finish()

    @defer.inlineCallbacks
    def process_array(self, array):
        """
        Main part of the protocol handling. Whan comes in as the parameter is
        a array of expresions, for example:

        ["1", "'some string'", "variable",
         "some_call(param1, some_other_call())"]

        Each element of the is evaluated in synchronous way. In case of method
        calls, the call is performed by iterating the method.

        The result of the function is list with elements subsituted by the
        values they stand for (for variables: values, for method calls: the
        result of deferred returned).
        """
        result = list()
        for element in array:
            m = self.re['number'].search(element)
            self.log('matching: %s', element)
            if m:
                result.append(eval(m.group(0)))
                continue

            m = self.re['string'].search(element)
            if m:
                result.append(m.group(1))
                continue

            m = self.re['none'].search(element)
            if m:
                result.append(None)
                continue

            m = self.re['variable'].search(element)
            if m:
                result.append(self.get_local(m.group(1)))
                continue

            m = self.re['call'].search(element)
            n = self.re['method_call'].search(element)
            if m or n:
                if m:
                    command = m.group(1)
                    method = self.commands.lookup_cmd(command)
                    rest = m.group(2)
                else:
                    obj = n.group(1)
                    local = self.get_local(obj)
                    if not isinstance(local, Manhole):
                        raise IllegalCall('Variable %r should be a Manhole '
                                          'instance to make this work!' % obj)
                    command = n.group(2)
                    method = local.lookup_cmd(command)
                    rest = n.group(3)
                arguments = yield self.process_array(self.split(rest))
                d = defer.maybeDeferred(method, *arguments)
                value = yield d
                self.debug("Finished processing command: %s", element)
                result.append(value)

                continue

            raise BadSyntax('Syntax error processing line: %s. '
                            'Could not detect type of element: %s' %\
                            (self._last_line, element, ))

        defer.returnValue(result)

    def validate_result(self, result_array):
        '''
        Check that the result is a list with a single element, and return it.
        If we had more than one element it would mean that the line processed
        looked somewhat like this:
        call1(), "blah blah blah"
        '''
        if len(result_array) != 1:
            raise BadSyntax('Syntax error processing line: %s' %\
                            self._last_line)
        return result_array[0]

    def on_finish(self):
        '''
        Called when there is no more messages to be processed in the buffer.
        '''
        if callable(self.cb_on_finish):
            self.cb_on_finish()

    def set_local(self, value, variable_name):
        '''
        Assign local variable. The line processed looked somewhat like this:
        variable = some_call()
        '''
        self.log('assigning %s = %r', variable_name, value)
        self._locals[variable_name] = value
        return value

    def get_local(self, variable_name):
        '''
        Return the value of the local variable. Raises UnknownVariable is
        the name is not known.
        '''
        if variable_name not in self._locals:
            raise UnknownVariable('Unknown variable %s' % variable_name)
        return self._locals[variable_name]

    def _error_handler(self, f):
        error_handler(self, f)
        self.send_output(f.getErrorMessage())


class BadSyntax(Exception):
    pass


class IllegalCall(Exception):
    pass


class UnknownVariable(Exception):
    pass


class UnknownCommand(Exception):
    pass
