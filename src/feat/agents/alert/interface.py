from zope.interface import Interface

__all__ = ["IEmailSenderLabourFactory", "INagiosSenderLabourFactory",
           "IAlertSenderLabour"]


class IEmailSenderLabourFactory(Interface):

    def __call__(config):
        '''
        @returns: L{IAlertSenderLabour}
        '''


class INagiosSenderLabourFactory(Interface):

    def __call__(config):
        '''
        @returns: L{IAlertSenderLabour}
        '''


class IAlertSenderLabour(Interface):

    def send(config, msg, severity):
        '''
        Sends an alert
        '''
