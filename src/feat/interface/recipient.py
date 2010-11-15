from zope.interface import Interface, Attribute

from feat.common import enum

'''
Provides interfaces for specifing the recipients of messages.
Types that can be passed as destination includes:

- Agent (defined in this module)
- Broadcast (defined in this module)
- agent.IAgencyAgent this helps in tests - one can say that is sending message
                     to the agent
- message.BaseMessage (and subclasses) - one can say he is responding
                                         to message
- list - the list of any combination of above
'''


class RecipientType(enum.Enum):
    agent, broadcast = range(1, 3)


class IRecipients(Interface):
    '''Iterable with all elements implementing IRecipient'''

    def __iter__(self):
        pass


class IRecipient(Interface):

    shard = Attribute('Shard of reciepient')
    key = Attribute('Routing key of reciepient')
    type = Attribute('Broadcast or agent?')
