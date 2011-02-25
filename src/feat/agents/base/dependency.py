from feat.common import annotate
from feat.agents.base import replay
from feat.agencies.dependency import Mode


def register(component, calable, mode):
    annotate.injectClassCallback("dependency", 3, "_register_dependency",
                                 component, calable, mode)


class UndefinedDependency(Exception):
    pass


class AgentDependencyMixin(object):
    '''
    Mixin for the BaseAgent to handle dependencies.
    '''

    _dependencies = None

    @classmethod
    def _register_dependency(cls, component, calable, mode):
        if cls._dependencies is None:
            cls._dependencies = dict()
        if component not in cls._dependencies:
            cls._dependencies[component] = dict()
        cls._dependencies[component][mode] = calable

    @replay.immutable
    def dependency(self, state, component, *args, **kwargs):
        mode = state.medium.get_mode(component)
        for_component = self._dependencies.get(component, None)
        if for_component is None:
            raise UndefinedDependency(
                'Component %s is not defined. Defined components are: %r' %\
                (component, self._dependencies.keys(), ))
        calable = for_component.get(mode, None)
        if calable is None:
            raise UndefinedDependency(
                'Component %s is not defined for the mode %r. '
                'Defined handlers are for the modes: %r' %\
                (component, mode, for_component.keys(), ))

        return calable(*args, **kwargs)
