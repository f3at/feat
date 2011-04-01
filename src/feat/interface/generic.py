from zope.interface import Interface

__all__ = ["ITimeProvider"]


class ITimeProvider(Interface):

    def get_time():
        '''
        Use this to get current time.
        It is assumed time is synchronized throughout the cluster using NTP.
        @return: Number of seconds since epoch in UTC.
        @rtype: float
        '''
