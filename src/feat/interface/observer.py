from zope.interface import Interface

__all__ = ["IObserver"]


class IObserver(Interface):
    '''
    Wraps the asynchronous job remembering it status and result.
    '''

    def notify_finish(self):
        '''
        Gives a fiber which will fire when the observed job is done (or is
        fired instantly). The fibers trigger value and status should be the
        same as the result of the asynchronous job.
        '''

    def active(self):
        '''
        Returns True/False saying if the job is still being performed.
        '''

    def get_result(self):
        '''
        Get the result synchronously. It may only be called after the job
        has finished. Overwise it should raise runtime error.
        If the job failed this method returns the Failure instance.

        @raises: RuntimeError
        '''
