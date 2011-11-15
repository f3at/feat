from zope.interface import implements

from feat.common import log, defer
from feat.web import document
from feat.web.markup import html

from feat.models.interface import IModel, IMetadata


MIME_TYPE = "text/html"


class Layout(html.Document):

    def __init__(self, title, *args, **kwargs):
        html.Document.__init__(self, html.StrictPolicy(), title)
        self.h1()(title).close()
        self.div(_class='content')


class HTMLWriter(log.Logger):
    implements(document.IWriter)

    def __init__(self, logger=None):
        log.Logger.__init__(self, logger)

    @defer.inlineCallbacks
    def write(self, doc, model, *args, **kwargs):
        self.log("Rendering html doc for a model: %r", model.identity)
        title = "Displaying model %r." % (model.identity, )
        markup = Layout(title, *args, **kwargs)

        items = yield model.fetch_items()
        markup.h3()('List of model items.').close()
        ul = markup.ul(_class="items")
        for item in items:
            li = markup.li()
            if item.name:
                markup.span(_class='name')(item.name).close()
            if item.label:
                markup.span(_class='label')(item.label).close()
            if item.desc:
                markup.span(_class='desc')(item.desc).close()

            if IMetadata.providedBy(item):
                if item.get_meta('inline'):
                    markup.append(self._format_attribute(item))

            if IMetadata.providedBy(item):
                if item.get_meta('render_array'):
                    limit = int(item.get_meta('render_array')[0].value)
                    markup.div(_class='array')(
                        self._render_array(item, limit)).close()
            li.close()

        ul.close()
        yield markup.render(doc)

    @defer.inlineCallbacks
    def _format_attribute(self, item):
        if not item.get_meta('inline'):
            raise ValueError("_format_attribute() called for something which"
                             "doesn't render inline: %r", item)
        model = yield item.fetch()
        defer.returnValue(
            html.tags.span(_class='value')(model.perform_action('get')))

    @defer.inlineCallbacks
    def _render_array(self, item, limit):
        tree = list()
        flattened = list()
        columns = list()

        yield self._build_tree(tree, item, limit)
        self._flatten_tree(flattened, columns, dict(), tree[0], limit)

        headers = [html.tags.th()(x) for x in columns]
        table = html.tags.table()(
            html.tags.thead()(*headers))
        tbody = html.tags.tbody()
        table.content.append(tbody)

        for row in flattened:
            tr = html.tags.tr()
            for column in columns:
                td = html.tags.td()
                item = row.get(column)
                if item:
                    td.append(self._format_attribute(item))
                tr.append(td)

            tbody.append(tr)

        defer.returnValue(table)

    @defer.inlineCallbacks
    def _build_tree(self, tree, item, limit):
        model = yield item.fetch()
        items = yield model.fetch_items()
        # [dict of attributes added by this level, list of child rows]
        tree.append([dict(), list()])
        for item in items:
            is_array = IMetadata.providedBy(item) and \
                       not item.get_meta('inline')
            if is_array:
                if limit > 0:
                    yield self._build_tree(tree[-1][1], item, limit - 1)
            else:
                column_name = "%s.%s" % (model.identity, item.name, )
                tree[-1][0][column_name] = item

    def _flatten_tree(self, result, columns, current, tree, limit):
        current = dict(current)

        if tree[0]:
            current.update(tree[0])
            for column in tree[0].keys():
                if column not in columns:
                    columns.append(column)

        if not tree[1] and current:
            result.append(current)

        for subtree in tree[1]:
            if limit > 0:
                self._flatten_tree(result, columns, current, subtree,
                                   limit - 1)
            else:
                result.append(current)


writer = HTMLWriter()
document.register_writer(writer, MIME_TYPE, IModel)
