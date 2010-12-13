# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

import StringIO
import re
import shlex

from twisted.internet import defer
from zope.interface import implements

from feat.common import log
from feat.agencies import agency
from feat.agencies.emu import messaging, database
from feat.agents.base import descriptor, agent
from feat.interface.agent import IAgencyAgent
from feat.test import factories


class Commands(object):
    '''
    Implementation of all the commands understood by the protocol.
    This is a mixin mixed to Driver class.
    '''

    def cmd_spawn_agency(self):
        '''
        Spawn new agency, returns the reference. Usage:
        > spawn_agency()
        '''
        ag = agency.Agency(self._messaging, self._database)
        self._agencies.append(ag)
        return ag

    def cmd_start_agent(self, ag, agent_name, desc):
        """
        Start the agent inside the agency. Usage:
        > start_agent(agency, 'HostAgent', descriptor)
        """
        if not isinstance(ag, agency.Agency):
            raise AttributeError('First argument needs to be an agency')
        factory = agent.registry_lookup(agent_name)
        if factory is None:
            raise AttributeError('Second argument needs to be an agent type. '
                            'Name: %s not found in the registry.', agent_name)
        if not isinstance(desc, descriptor.Descriptor):
            raise AttributeError('Third argument needs to be an Descriptor, '
                                 'got %r instead', desc)
        ag.start_agent(factory, desc)

    def cmd_descriptor_factory(self, shard='lobby'):
        """
        Creates and returns a descriptor to pass it later
        for starting the agent.
        Parameter is optional (default lobby). Usage:
        > descriptor_factory('some shard')
        """
        desc = factories.build(descriptor.Descriptor, shard=shard)
        return self._database_connection.save_document(desc)

    def cmd_breakpoint(self, name):
        """
        Register the breakpoint of the name. Usage:
        > breakpoint('setup-done')

        The name should be used in a call of Driver.register_breakpoint(name)
        method, which returns the Deferred, which will be fired by this
        command.
        """
        if name not in self._breakpoints:
            self.warning("Reached breakpoint %s but found no "
                         "callback registered")
            return
        cb = self._breakpoints[name]
        cb.callback(None)
        return cb


class Driver(log.Logger, log.FluLogKeeper, Commands):
    implements(IAgencyAgent)

    log_category = 'simulation-driver'

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self._messaging = messaging.Messaging()
        self._database = database.Database()

        self._output = Output()
        self._parser = Parser(self, self._output, self)

        self._agencies = list()
        self._breakpoints = dict()

        self._init_connections()

    def _init_connections(self):

        def store(desc):
            self._descriptor = desc

        self._database_connection = self._database.get_connection(self)
        d = self._database_connection.save_document(
            factories.build(descriptor.Descriptor))
        d.addCallback(store)

        self._messaging_connection = self._messaging.get_connection(self)

    def register_breakpoint(self, name):
        if name in self._breakpoints:
            raise RuntimeError("Breakpoint with name: %s already registered",
                               name)
        d = defer.Deferred()
        self._breakpoints[name] = d
        return d

    def process(self, script):
        self._parser.dataReceived(script)

    def finished_processing(self):
        '''Called when the protocol runs out of data to process'''

    # IAgencyAgent

    def on_message(self, msg):
        pass

    def get_descriptor(self):
        return self._descriptor


class Parser(log.Logger):

    log_category = 'command-parser'

    def __init__(self, driver, output, commands):
        log.Logger.__init__(self, driver)

        self.driver = driver
        self.commands = commands
        self.buffer = ""
        self.output = output
        self._locals = dict()
        self._last_line = None
        self.re = dict(
            assignment=re.compile('\A(\w+)\s*=\s*(\S.*)'),
            number=re.compile('\A\d+(\.\d+)?\Z'),
            string=re.compile('\A\'([^(?<!\)\']*)\'\Z'),
            call=re.compile('\A(\w+)\((.*)\)\Z'),
            variable=re.compile('\A([^\(\)\'\"\s\+]+)\Z'))

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
            self.log('Processing line: %s', line)
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
            self.log('matching: #%s#', element)
            if m:
                result.append(eval(m.group(0)))
                continue

            m = self.re['string'].search(element)
            if m:
                result.append(m.group(1))
                continue

            m = self.re['variable'].search(element)
            if m:
                result.append(self.get_local(m.group(1)))
                continue

            m = self.re['call'].search(element)
            if m:
                command = m.group(1)
                method = self.lookup_cmd(command)
                arguments = yield self.process_array(self.split(m.group(2)))
                d = defer.maybeDeferred(method, *arguments)
                value = yield d
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
        self.driver.finished_processing()

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
        self.error("Error processing: %s", f.getErrorMessage())
        self.send_output(f.getErrorMessage())

    def lookup_cmd(self, name):
        '''
        Check if the protocol includes the message and return it.
        Raises UnknownCommand otherwise.
        '''
        cmd_name = "cmd_%s" % name
        try:
            method = getattr(self.commands, cmd_name)
            if not callable(method):
                raise UnknownCommand('Unknown command: %s' % name)
        except AttributeError:
            raise UnknownCommand('Unknown command: %s' % name)
        return method


class UnknownCommand(Exception):
    pass


class BadSyntax(Exception):
    pass


class UnknownVariable(Exception):
    pass


class Output(StringIO.StringIO, object):
    """
    This class is given to parser as an output in unit tests,
    when there is no transport to write to.
    """
