# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import inspect
import StringIO
import re

from twisted.internet import defer, protocol

from feat.common import log
from feat.agencies import agency
from feat.agencies.emu import messaging, database
from feat.agents import descriptor, agent
from feat.interface.agent import IAgentFactory
from feat.test import factories


class Commands(object):
    '''
    Implementation of all the commands understood by protocol.
    This is a mixin mixed to Driver class.
    '''

    def cmd_spawn_agency(self):
        '''
        Spawn new agency, returns the reference. Usage:
          spawn_agency
        '''
        ag = agency.Agency(self._messaging, self._database)
        self._agencies.append(ag)
        return ag

    def cmd_start_agent(self, ag, agent_name):
        """
        Start the agent inside the agency. Usage:
          start_agent agency 'HostAgent'
        """
        if not isinstance(ag, agency.Agency):
            raise AttributeError('First argument needs to be an agency')
        factory = agent.registry_lookup(agent_name)
        if factory is None:
            raise AttributeError('Second argument needs to be an agent type. '
                            'Name: %s not found in the registry.', agent_name)
        desc = factories.build(descriptor.Descriptor)
        ag.start_agent(factory, desc)

    def cmd_breakpoint(self, name):
        if name not in self._breakpoints:
            self.warning("Reached breakpoint %s but found no "
                         "callback registered")
            return
        cb = self._breakpoints[name]
        cb.callback(None)
        return cb
                             

class Driver(log.Logger, log.FluLogKeeper, Commands):

    log_category = 'simulation-driver'

    def __init__(self):
        log.FluLogKeeper.__init__(self)
        log.Logger.__init__(self, self)

        self._messaging = messaging.Messaging()
        self._database = database.Database()
        self._output = Output()
        self._parser = Parser(self, self.output, self)
        
        self._agencies = dict()
        self._breakpoints = dict()

    def register_breakpoint(self, name):
        if name in self._breakpoints:
            raise RuntimeError("Breakpoint with name: %s already registered",
                               name)
        d = defer.Deferred()
        self._breakpoints[name] = d
        return d

    def process(script):
        self._parser.dataReceived(script)


class Parser(log.Logger):

    log_category = 'command-parser'

    def __init__(self, driver, output, commands):
        log.Logger.__init__(self, driver)

        self.commands = commands
        self.buffer = ""
        self.output = output
        self._locals = dict()

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
            self.log('Processing line: %s', line)
            if not re.search('\w', line):
                self.log('Empty line')
                return self.process_line()

            assignment = re.search('\A(\w+)\s*=\s*(\w+)\s*(.*)', line)
            if assignment:
                variable_name = assignment.group(1)
                command = assignment.group(2)
                rest = assignment.group(3)
                args = rest and rest.split() or list()
            else:
                args = line.split()
                command = args.pop(0)

            d = defer.maybeDeferred(self.lookup_cmd, command)
            d.addCallback(self.call_method, args)
            if assignment:
                d.addCallback(self.set_local, variable_name)
            d.addCallback(self.send_output)
            d.addCallbacks(lambda _: self.process_line(), self._error_handler)
        else:
            self.on_finish()

    def on_finish(self):
        pass

    def set_local(self, value, variable_name):
        self.log('assigning %s = %r', variable_name, value)
        self._locals[variable_name] = value
        return value

    def get_local(self, variable_name):
        if variable_name not in self._locals:
            raise UnknownVariable('Variable %s not known', variable_name)
        return self._locals[variable_name]

    def call_method(self, method, args):
        parsed_args = list()
        for arg in args:
            m = re.search('\A[\'\"](.+)[\'\"]\Z', arg) #string
            if m:
                parsed_args.append(m.group(1))
                continue
            m = re.search('\A[0-9\.]\Z', arg) # number
            if m:
                parsed_args.append(arg)
                continue

            parsed_args.append(self.get_local(arg)) # variable name

        return method(*parsed_args)

    def _error_handler(self, f):
        self.error("Error processing: %s", f.getErrorMessage())
        self.send_output(f.getErrorMessage())
            
    def lookup_cmd(self, name):
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


class UnknownVariable(Exception):
    pass


class Output(StringIO.StringIO, object):
    """
    This class is given to parser as an output in unit tests,
    when we don't there is no transport to write to.
    """
