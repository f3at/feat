from feat.common import enum
from feat.agents.base import replay


class Mode(enum.Enum):

    production, test, simulation = range(3)


class AgencyDependencyMixin(object):

    def __init__(self, default):
        self._dependencies_modes = dict()
        self._set_default_mode(default)

    def _set_default_mode(self, default):
        self._dependencies_modes['_default'] = default

    def set_mode(self, component, mode):
        assert isinstance(mode, Mode)
        self._dependencies_modes[component] = mode

    def get_mode(self, component):
        return self._dependencies_modes.get(component,
                                        self._dependencies_modes['_default'])


class AgencyAgentDependencyMixin(object):

    @replay.named_side_effect('AgencyAgent.get_mode')
    def get_mode(self, component):
        return self.agency.get_mode(component)
