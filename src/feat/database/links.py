import operator

from feat.agents.application import feat
from feat.common.text_helper import format_block
from feat.database import view
from feat.database.interface import IDocument


@feat.register_view
class Join(view.JavascriptView):

    design_doc_id = 'featjs'
    name = 'join'

    map = format_block('''
    function(doc) {
        if (doc.linked) {
            for (var x = 0; x < doc.linked.length; x++) {
                var row = doc.linked[x];

                // emit link from document to linkee
                if (row[3] && row[3].length && row[3][0][0] != '.') {
                    for (var xx=0; xx < row[3].length; xx ++) {
                        emit([doc["_id"], row[3][xx]], {"_id": row[1]});
                    }
                };
                emit([doc["_id"], row[0]], {"_id": row[1]});

                // emit reverse link, from linkee to linker
                if (row[2] && row[2].length && row[2][0][0] != '.') {
                    for (var xx=0; xx < row[2].length; xx ++) {
                        emit([row[1], row[2][xx]], null);
                    }
                };
                emit([row[1], doc[".type"]], null);
            }
        }
    }''')

    @staticmethod
    def keys(doc_id, type_name=None):
        if IDocument.providedBy(doc_id):
            doc_id = doc_id.doc_id
        if type_name is not None:
            return dict(key=(doc_id, type_name))
        else:
            return dict(startkey=(doc_id, ), endkey=(doc_id, {}))


def fetch(connection, doc_id, type_name=None):
    keys = Join.keys(doc_id, type_name)
    return connection.query_view(Join, include_docs=True, **keys)


def fetch_one(connection, doc_id, type_name=None):
    keys = Join.keys(doc_id, type_name)
    d = connection.query_view(Join, include_docs=True, limit=1, **keys)
    d.addCallback(lambda x: x[0] if x else None)
    return d


def get_ids(connection, doc_id, type_name=None):
    keys = Join.keys(doc_id, type_name)
    d = connection.query_view(Join, parse_results=False, **keys)
    d.addCallback(lambda x: map(operator.itemgetter(2), x))
    return d
