from zope.interface import implements

from feat.common import log, defer
from feat.models import reference
from feat.web import document
from feat.web.markup import html

from feat.models.interface import IModel, IMetadata, ActionCategory


MIME_TYPE = "text/html"


class Layout(html.Document):

    def __init__(self, title, context):
        html.Document.__init__(self, html.StrictPolicy(), title)
        self._link_static_files(context)
        self.div(_class='header')(*self._render_header(context)).close()
        self.h1()(title).close()

        self.div(_class='content')

    def _link_static_files(self, context):
        url = reference.Local('static', 'feat.css').resolve(context)
        self.head.content.append(
            html.tags.link(_type='text/css', rel='stylesheet', href=url))

    def _render_header(self, context):
        res = list("History: ")
        for index in range(len(context.names[:-1])):
            name = context.names[index]
            path = context.names[1:index + 1]
            url = reference.Local(*path).resolve(context)
            res.append("|")
            res.append(html.tags.a(href=url)(name))
        return res


class HTMLWriter(log.Logger):
    implements(document.IWriter)

    def __init__(self, logger=None):
        log.Logger.__init__(self, logger)

    @defer.inlineCallbacks
    def write(self, doc, model, *args, **kwargs):
        self.log("Rendering html doc for a model: %r", model.identity)
        context = kwargs['context']

        title = "Displaying model %r." % (model.identity, )
        markup = Layout(title, context)

        yield self._render_items(model, markup, context)
        yield self._render_actions(model, markup, context)
        yield markup.render(doc)

    @defer.inlineCallbacks
    def _render_items(self, model, markup, context):
        items = yield model.fetch_items()
        if not items:
            return
        markup.h3()('List of model items.').close()
        ul = markup.ul(_class="items")
        for item in items:
            li = markup.li()
            # submodel = yield item.fetch()
            url = item.reference.resolve(context)
            markup.span(_class='name')(
                html.tags.a(href=url)(item.name)).close()

            if IMetadata.providedBy(item):
                if item.get_meta('inline'):
                    li.append(self._format_attribute(item))

            if item.label:
                markup.span(_class='label')(item.label).close()
            if item.desc:
                markup.span(_class='desc')(item.desc).close()

            if IMetadata.providedBy(item):
                if item.get_meta('render_array'):
                    limit = int(item.get_meta('render_array')[0].value)
                    markup.div(_class='array')(
                        self._render_array(item, limit)).close()
            li.close()

        ul.close()
        markup.hr()

    @defer.inlineCallbacks
    def _render_actions(self, model, markup, context):
        actions = yield model.fetch_actions()
        if not actions:
            return
        markup.h3()('List of model actions.').close()
        ul = markup.ul(_class="items")
        for action in actions:
            li = markup.li()
            markup.span(_class='name')(action.name).close()
            self._render_action_form(action, markup, context)
            li.close()
        ul.close()
        markup.hr()

    def _render_action_form(self, action, markup, context):
        if action.category == ActionCategory.delete:
            method = "DELETE"
        elif action.is_idempotent:
            method = "PUT"
        else:
            method = "POST"
        url = reference.Relative().resolve(context)
        form = markup.form(method=method, action=url, _class='action_form')
        div = markup.div()
        for param in action.parameters:
            self._render_param_field(markup, context, param)
        markup.input(type='submit', value='Perform')
        div.close()
        form.close()

    def _render_param_field(self, markup, context, action_param):
        default = action_param.value_info.use_default and \
                  action_param.value_info.default

        markup.label()(action_param.name).close()
        markup.input(type='text', default=default, name=action_param.name)
        if action_param.desc:
            markup.span(_class='desc')(action_param.desc).close()
        if not action_param.is_required:
            markup.span(_class='optional')("Optional").close()
        markup.br()

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
