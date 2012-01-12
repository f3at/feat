from feat.common import adapter
from feat.models import model, value
from feat.models import call

import demo_service


@adapter.register(demo_service.Service, model.IModel)
class Service(model.Model):
    model.identity("service")
    model.attribute("size", value.Integer(),
                    call.source_call("count_documents"))
