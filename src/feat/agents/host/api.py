import copy

from feat.agents.host import host_agent
from feat.common import first
from feat.gateway.application import featmodels
from feat.gateway import models
from feat.web import http

from feat.models import model, value, call, getter, reference, attribute
from feat.models import effect, action, response

from feat.models.interface import IModel, InvalidParameters


@featmodels.register_model
@featmodels.register_adapter(host_agent.HostAgent, IModel)
class HostAgent(models.Agent):
    model.identity('feat.host_agent')

    model.child('static_agents', model='feat.host_agent.static_agents',
                label="Static agents",
                view=call.source_call('get_static_agents'))
    model.item_meta('static_agents', 'html-render', 'array, 1')


@featmodels.register_model
class StaticAgents(model.Collection):
    model.identity('feat.host_agent.static_agents')
    model.child_names(call.model_call('get_names'))
    model.child_view(getter.model_get('get_definition'))
    model.child_model('feat.host_agent.static_agents.INDEX')
    model.meta('html-render', 'array, 1')
    model.meta("html-render", "array-columns, name, running, agent_id")

    def get_names(self):
        return [x.name for x in self.view]

    def get_definition(self, name):
        return first(x for x in self.view if name == x.name)


class StartStaticAgent(action.Action):

    action.label('Start agent')
    action.result(value.Response())
    action.param('force', value.Boolean(False), is_required=False,
                 label="Start the agent even it is already running")
    action.effect(call.action_perform('do_spawn'))
    action.effect(call.action_filter('render_response'))

    def do_spawn(self, force=False):
        if self.model.running and not force:
            raise InvalidParameters(
                params=dict(force="Agent is already running, you have to use"
                            " force."))
        desc = copy.copy(self.model.view.initial_descriptor)
        return self.model.source.spawn_agent(
            desc, static_name=self.model.view.name, **self.model.view.kwargs)

    def render_response(self, value):
        if value is None:
            raise http.HTTPError(name="Spawning agent failed",
                                 status=http.Status[409])
        else:
            return response.Done(value, "Done")


@featmodels.register_model
class StaticAgent(model.Model):
    model.identity('feat.host_agent.static_agents.INDEX')
    model.attribute('name', value.String(), getter.view_attr('name'))
    model.item_meta("name", "html-link", "owner")
    model.attribute('running', value.Boolean(), getter.model_attr('running'))
    model.child('initial_descriptor',
                view=getter.view_attr('initial_descriptor'),
                model='feat.host_agent.static_agents.INDEX.initial_descriptor')
    model.child('intial_params', view=getter.view_attr('kwargs'),
                model='feat.host_agent.static_agents.INDEX.initial_params')
    model.attribute('agent_id', value.String(''),
                    getter.model_attr('agent_id'))
    model.child('agent', source=call.model_call('get_agent_reference'))
    model.action('start', StartStaticAgent)

    def init(self):
        partner = self.source.find_static_partner(self.view.name)
        self.running = partner is not None
        self.agent_id = partner and partner.recipient.key

    def get_agent_reference(self):
        if self.running:
            return reference.Local('agents', self.agent_id)


@featmodels.register_model
class InitialDescriptor(model.Collection):
    model.identity('feat.host_agent.static_agents.INDEX.initial_descriptor')
    model.child_names(call.model_call('get_names'))
    model.child_source(getter.model_get('get_value'))
    model.child_meta('json', 'attribute')

    def init(self):
        values = dict()
        for field in self.view._fields:
            v = getattr(self.view, field.name)
            values[field.name] = v
        self._children = model_from_dict(values, self.source,
                                         self.view.type_name)

    def get_names(self):
        return self._children.keys()

    def get_value(self, name):
        return self._children.get(name)


@featmodels.register_model
class InitialParams(model.Collection):
    model.identity('feat.host_agent.static_agents.INDEX.initial_params')
    model.child_names(call.model_call('get_names'))
    model.child_source(getter.model_get('get_value'))
    model.child_meta('json', 'attribute')

    def init(self):
        self._children = model_from_dict(self.view, self.source,
                                         'initial_params')

    def get_names(self):
        return self._children.keys()

    def get_value(self, name):
        return self._children.get(name)


def model_from_dict(values, source, type_name):
    result = dict()
    if not values:
        return result
    for name, v in values.iteritems():

        v_info = None
        if isinstance(v, int):
            v_info = value.Integer()
        elif isinstance(v, (str, unicode)):
            v_info = value.String()
        if v_info:
            iden = type_name + '.' + name
            Attribute = attribute.MetaAttribute.new(
                iden, v_info, getter=effect.static_value(v))
            result[name] = Attribute(source)
    return result
