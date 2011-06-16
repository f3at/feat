from zope.interface import Interface

__all__ = ["IDNSServerLabourFactory", "IDNSServerLabour"]


class IDNSServerLabourFactory(Interface):

    def __call__(patron, resolver, slaves, suffix):
        '''
        @returns: L{IManagerLabour}
        '''


class IDNSServerLabour(Interface):

    def initiate():
        '''Initialises the labour.'''

    def startup(port):
        '''Startups the labour, starting to listen
        on specified port for DNS queries.'''

    def cleanup():
        '''Cleanup the labour, stop listening for DNS queries.'''

    def notify_slaves(self):
        '''Notify slaves for zones updates'''
