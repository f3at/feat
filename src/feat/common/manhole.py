# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
from functools import partial
from feat.common import decorator, annotate, enum


class SecurityLevel(enum.Enum):
    """
    safe - should be used to expose querying commands which
           will not mess up with the state
    unsafe - should be for the operations which require a bit of thinking
    superhuman - should not be used, but does it mean we shouldn't have it?
    """

    (safe, unsafe, superhuman, ) = range(3)


@decorator.parametrized_function
def expose(function, security_level=SecurityLevel.safe):
    annotate.injectClassCallback("recorded", 4,
                                 "_register_exposed", function,
                                 security_level)

    return function


class Manhole(annotate.Annotable):

    _exposed = None

    @classmethod
    def _register_exposed(cls, function, security_level):
        if cls._exposed is None:
            cls._exposed = dict()
        for lvl in SecurityLevel:
            if lvl > security_level:
                continue
            fun_id = function.__name__
            if lvl not in cls._exposed:
                cls._exposed[lvl] = dict()
            cls._exposed[lvl][fun_id] = function

    def get_exposed_cmds(self, lvl=SecurityLevel.safe):
        if self._exposed is None or lvl not in self._exposed:
            return list()
        else:
            return self._exposed[lvl].values()

    def lookup_cmd(self, name, lvl=SecurityLevel.safe):
        if self._exposed is None or lvl not in self._exposed or\
                                            name not in self._exposed[lvl]:
            raise UnknownCommand('Unknown command: %s.%s' %\
                                 (self.__class__.__name__, name, ))
        return partial(self._exposed[lvl][name], self)


class UnknownCommand(Exception):
    pass
