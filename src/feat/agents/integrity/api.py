import operator

from feat.agents.integrity import integrity_agent
from feat.common import defer
from feat.database import conflicts
from feat.gateway.application import featmodels
from feat.gateway import models
from feat.models import model, value, call, getter

from feat.models.interface import IModel


@featmodels.register_model
@featmodels.register_adapter(integrity_agent.IntegrityAgent, IModel)
class IntegrityAgent(models.Agent):
    model.identity('feat.integrity_agent')

    model.child('replications', model='feat.integrity_agent.replications',
                label="Replications")


@featmodels.register_model
class Replications(model.Collection):
    model.identity('feat.integrity_agent.replications')
    model.child_names(call.model_call('get_names'))
    model.child_view(getter.model_get('get_status'))
    model.child_model('feat.integrity_agent.replications.NAME')
    model.child_meta('json', 'render-inline')

    def init(self):
        state = self.source._get_state()
        self.connection = state.replicator
        self.config = state.db_config
        d = conflicts.get_replication_status(self.connection,
                                             self.config.name)
        d.addCallback(defer.inject_param, 2, setattr, self, 'statuses')
        return d

    def get_names(self):
        return self.statuses.keys()

    def get_status(self, name):
        rows = self.statuses.get(name)
        if not rows:
            return
        rows.sort(key=operator.itemgetter(0), reverse=True)
        return rows[0]


@featmodels.register_model
class Replication(model.Model):
    model.identity('feat.integrity_agent.replications.NAME')
    model.attribute('last_seq', value.Integer(),
                    getter=getter.model_attr('seq'))
    model.attribute('continuous', value.Integer(),
                    getter=getter.model_attr('continuous'))
    model.attribute('status', value.String(),
                    getter=getter.model_attr('status'))

    def init(self):
        self.seq, self.continuous, self.status = self.view
