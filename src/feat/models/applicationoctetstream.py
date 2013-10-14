from zope.interface import implements

from feat.web import document

from feat.models.interface import IActionPayload


MIME_TYPE = 'application/octet-stream'


class ActionPayload(dict):
    implements(IActionPayload)


def read_action(doc, *args, **kwargs):
    data = doc.read(decode=False)
    if not data:
        return ActionPayload()

    return ActionPayload(value=data)


document.register_reader(read_action, MIME_TYPE, IActionPayload)
