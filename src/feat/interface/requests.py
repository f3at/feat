from feat.common import enum

from feat.interface import protocols

__all__ = ["RequestState", "IRequestPeer"]


class RequestState(enum.Enum):
    '''Request protocol state:

      - none: Not initiated.
      - requested: The requested has send a request message to to repliers.
      - closed: The request expire or a response has been received
        from all repliers.
      - wtf: What a Terrible Failure
    '''
    none, requested, closed, wtf = range(4)


class IRequestPeer(protocols.IAgencyProtocol):
    '''Define common interface between both peers of the request protocol.'''

    def ensure_state():
        '''
        Cancel the fiber if the machine is currectly in incorrect state.
        '''
