from zope.interface import implements

from feat.common import log, defer
from feat.models import reference
from feat.web import document
from feat.web.markup import html

from feat.models.interface import IModel, IMetadata, ActionCategory, ValueTypes


MIME_TYPE = "text/html"


class Layout(html.Document):

    def __init__(self, title, context):
        html.Document.__init__(self, html.StrictPolicy(), title)
        self._link_static_files(context)
        self.div(_class='header')(*self._render_header(context)).close()
        self.h1()(title).close()

        self.div(_class='content')

    def _link_static_files(self, context):
        url = self._local_url(context, 'static', 'feat.css')
        self.head.content.append(
            html.tags.link(type='text/css', rel='stylesheet', href=url)())

        scripts = [('http://ajax.googleapis.com/ajax/libs/'
                   'jquery/1.6/jquery.min.js'),
                   self._local_url(context, 'static', 'script', 'json2.js'),
                   self._local_url(context, 'static', 'script', 'feat.js'),
                   self._local_url(context, 'static', 'script', 'form.js'),
                   self._local_url(context, 'static', 'script',
                                   'jquery.cseditable.js')]
        for url in scripts:
            self.head.content.append(
                html.tags.script(src=url, type='text/javascript')(" "))

    def _local_url(self, context, *parts):
        return reference.Local(*parts).resolve(context)

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

            url = item.reference.resolve(context)
            markup.span(_class='name')(
                html.tags.a(href=url)(item.name)).close()

            if IMetadata.providedBy(item):
                if item.get_meta('inline'):
                    li.append(self._format_attribute(item, context))

            if item.label:
                markup.span(_class='label')(item.label).close()
            if item.desc:
                markup.span(_class='desc')(item.desc).close()

            if IMetadata.providedBy(item):
                if item.get_meta('render_array'):
                    submodel = yield item.fetch()
                    limit = int(item.get_meta('render_array')[0].value)
                    markup.div(_class='array')(
                        self._render_array(item, limit, context)).close()
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

    def _action_url(self, context, name):
        url = "%s.%s" % (reference.Relative().resolve(context), name)
        return url

    def _render_action_form(self, action, markup, context):
        if action.category == ActionCategory.delete:
            method = "DELETE"
        elif action.is_idempotent:
            method = "PUT"
        else:
            method = "POST"
        url = self._action_url(context, action.name)
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
        text_types = [ValueTypes.integer, ValueTypes.number,
                      ValueTypes.string]
        v_t = action_param.value_info.value_type
        if v_t in text_types:
            markup.input(type='text', default=default, name=action_param.name)
        elif v_t == ValueTypes.boolean:
            extra = {}
            if default is True:
                extra['checked'] = '1'
            markup.input(type='checkbox', value='true',
                         name=action_param.name, **extra)
        else:
            msg = ("ValueType %s is not supported by HTML writer" %
                   (v_t.__name__))
            markup.span(_class='type_not_supported')(msg)
        if action_param.desc:
            markup.span(_class='desc')(action_param.desc).close()
        if not action_param.is_required:
            markup.span(_class='optional')("Optional").close()
        markup.br()

    @defer.inlineCallbacks
    def _format_attribute(self, item, context):
        if not item.get_meta('inline'):
            raise ValueError("_format_attribute() called for something which"
                             "doesn't render inline: %r", item)
        model = yield item.fetch()
        set_action = yield model.fetch_action('set')
        classes = ['value']
        extra = dict()
        if set_action:
            classes.append('inplace')
            subcontext = context.descend(model)
            extra['rel'] = self._action_url(subcontext, 'set')

        value = yield model.perform_action('get')
        if item.get_meta('link_owner'):
            url = reference.Relative().resolve(context)
            value = html.tags.a(href=url)(value)

        defer.returnValue(
            html.tags.span(_class=" ".join(classes), **extra)(value))

    @defer.inlineCallbacks
    def _render_array(self, item, limit, context):
        tree = list()
        flattened = list()
        columns = list()

        yield self._build_tree(tree, item, limit, context)
        self._flatten_tree(flattened, columns, dict(), tree[0], limit)

        headers = [html.tags.th()(x) for x, _ in columns]
        table = html.tags.table()(
            html.tags.thead()(*headers))
        tbody = html.tags.tbody()
        table.content.append(tbody)

        for row in flattened:
            tr = html.tags.tr()
            for column in columns:
                td = html.tags.td()
                value = row.get(column)
                if value:
                    item, cur_context = value
                    td.append(self._format_attribute(item, cur_context))
                tr.append(td)

            tbody.append(tr)

        defer.returnValue(table)

    @defer.inlineCallbacks
    def _build_tree(self, tree, item, limit, context):
        model = yield item.fetch()
        items = yield model.fetch_items()
        subcontext = context.descend(model)
        # [dict of attributes added by this level, list of child rows]
        tree.append([dict(), list()])
        for item in items:
            is_array = IMetadata.providedBy(item) and \
                       not item.get_meta('inline')
            if is_array:
                if limit > 0:
                    yield self._build_tree(tree[-1][1], item, limit - 1,
                                           subcontext)
            else:
                column_name = item.label
                if not column_name:
                    column_name = "%s.%s" % (model.identity, item.name, )
                tree[-1][0][(column_name, limit)] = (item, subcontext)

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
