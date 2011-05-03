from zope.interface import Interface

__all__ = ["IEmailSenderLabourFactory", "IEmailSenderLabour"]


class IEmailSenderLabourFactory(Interface):

    def __call__(config):
        '''
        @returns: L{IEmailSenderLabour}
        '''


class IEmailSenderLabour(Interface):

    def send(config, msg):
        '''
        Sends a an email
        '''
