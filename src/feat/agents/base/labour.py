from feat.common import log, serialization


class BaseLabour(log.Logger, serialization.Serializable):

    def __init__(self, patron):
        log.Logger.__init__(self, patron)
        self.patron = patron

    def startup(self):
        """Overridden by sub-classes."""

    def cleanup(self):
        """Overridden by sub-classes."""

    def __eq__(self, other):
        if isinstance(other, type(self)):
            return True
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, type(self)):
            return False
        return NotImplemented

    ### ISerializable Methods ###

    def snapshot(self):
        """Nothing to serialize."""

    def recover(self, snapshot):
        """Nothing to recover."""
