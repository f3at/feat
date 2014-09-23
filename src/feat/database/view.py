# F3AT - Flumotion Asynchronous Autonomous Agent Toolkit
# Copyright (C) 2010,2011 Flumotion Services, S.A.
# All rights reserved.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# See "LICENSE.GPL" in the source distribution for more information.

# Headers in this file shall remain intact.
import re
import inspect
import types

from zope.interface import directlyProvides, implements

from feat.common import formatable, annotate
from feat.common.text_helper import format_block
from feat.database import document
from feat import applications

from feat.interface.serialization import IRestorator
from feat.database.interface import IViewFactory
from feat.agents.application import feat

field = formatable.field


QUERY_METHODS = ['map', 'reduce', 'filter']


class JavascriptView(annotate.Annotable):

    name = None
    use_reduce = False
    design_doc_id = None
    language = u'javascript'
    disable_reduce_limit = False

    map_wrapper = format_block("""
    function exec(doc) {
        result = new Array();

        function emit(key, value) {result.push([key, value]); }

        (%s)(doc);
        return result;
    }
    """)

    js_wrapper = format_block("""
    function exec() {
        return (%s).apply(null, arguments);
    }
    """)

    # (wrapper, method) -> execjs.Context()
    compiled = dict()

    @classmethod
    def __class__init__(cls, name, bases, dct):
        directlyProvides(cls, IViewFactory)

    @classmethod
    def parse_view_result(cls, rows, reduced, include_docs, unserialize_list):
        if not include_docs:
            # return list of ids
            return list(rows)
        else:
            return unserialize_list((x[3] for x in rows
                                     if len(x) == 4 and x[3]))

    @classmethod
    def perform_map(cls, doc):
        context = cls.get_execjs(cls.map_wrapper, cls.map)
        for key, value in context.call('exec', doc):
            if isinstance(key, list):
                key = tuple(key)
            yield key, value

    @classmethod
    def perform_reduce(cls, keys, values):
        context = cls.get_execjs(cls.js_wrapper, cls.reduce)
        return context.call('exec', keys, values)

    @classmethod
    def perform_filter(cls, doc, request):
        context = cls.get_execjs(cls.js_wrapper, cls.filter)
        return context.call('exec', doc, request)

    @classmethod
    def get_code(cls, name):
        return unicode(getattr(cls, name))

    ### protected ###

    @classmethod
    def get_execjs(cls, wrapper, method):
        key = (wrapper, method)
        if key not in cls.compiled:
            try:
                import execjs
            except ImportError:
                raise NotImplementedError(
                    "Using js views in with emu database requires "
                    "installing the execjs python module. ")

            cls.compiled[key] = execjs.compile(wrapper % (method, ))

        return cls.compiled[key]


class AdhocQuery(object):
    """
    Use this class to query view defined outside of application context
    in the design documents which are not under control of feat.
    """

    implements(IViewFactory)

    def __init__(self, design_doc_id, name):
        if design_doc_id.startswith('_design/'):
            design_doc_id = design_doc_id.split('/', 1)[1]
        self.design_doc_id = design_doc_id
        self.name = name
        self.use_reduce = True

    def parse_view_result(self, rows, reduced, include_docs):
        return rows


class BaseView(annotate.Annotable):

    name = None
    use_reduce = False
    design_doc_id = u'feat'
    language = u'python'
    disable_reduce_limit = False

    @classmethod
    def __class__init__(cls, name, bases, dct):
        for method_name in QUERY_METHODS:
            method = dct.get(method_name, None)
            if not method:
                method = getattr(cls, method_name, None)
            if callable(method):
                setattr(cls, method_name, cls._querymethod(method))
        directlyProvides(cls, IViewFactory)

    @classmethod
    def parse_view_result(cls, rows, reduced, include_docs, unserialize_list):
        if not include_docs:
            # return list of ids
            return [cls.parse(x[0], x[1], reduced) for x in rows]
        else:
            return unserialize_list((x[3] for x in rows
                                     if len(x) == 4 and x[3]))

    @classmethod
    def parse(cls, key, value, reduced):
        return value

    @classmethod
    def perform_map(cls, doc):
        return cls.map(doc)

    @classmethod
    def perform_reduce(cls, keys, values):
        if cls.reduce.func_code.co_argcount == 3:
            return cls.reduce(keys, values, rereduce=False)
        else:
            return cls.reduce(keys, values)

    @classmethod
    def perform_filter(cls, doc, request):
        return cls.filter(doc, request)

    ### annotations ###

    @classmethod
    def attach_constant(cls, method, constant, value):
        if method.__name__ not in QUERY_METHODS:
            raise AttributeError("%s not in %r" % (method.__name__,
                                                   QUERY_METHODS))
        method.source += "\n%s = %r" % (constant, value)
        method.func_globals.update({constant: value})

    @classmethod
    def attach_method(cls, query_method, method):
        if query_method.__name__ not in QUERY_METHODS:
            raise AttributeError("%s not in %r" % (query_method.__name__,
                                                   QUERY_METHODS))
        source = cls._get_normalized_source(method)
        if source not in query_method.source:
            query_method.source += "\n%s" % (source, )
            query_method.func_globals.update({method.__name__: method})

    @classmethod
    def attach_code(cls, query_method, code):
        if query_method.__name__ not in QUERY_METHODS:
            raise AttributeError("%s not in %r" % (query_method.__name__,
                                                   QUERY_METHODS))
        query_method.source += "\n%s" % (code, )
        exec code in {}, query_method.func_globals

    @classmethod
    def attach_dict_of_objects(cls, query_method, name):
        # we cannot use normal mechanism for attaching code to query methods,
        # because we want to build a complex object out of it, so we need to
        # inject it after all the annotations have been processed
        names = {}
        obj = getattr(cls, name)
        if not isinstance(obj, dict):
            raise ValueError("%s.%s expected dict, %r found" %
                             (cls, name, obj))
        for field, handler in obj.items():
            if isinstance(handler, types.FunctionType):
                cls.attach_method(query_method, handler)
            elif isinstance(handler, types.TypeType):
                cls.attach_class_definition(query_method, handler)
            else:
                raise ValueError(handler)
            names[field] = handler.__name__
        code = ", ".join(["'%s': %s" % (k, v)
                          for k, v in sorted(names.iteritems())])
        cls.attach_code(query_method, "%s = {%s}" % (name, code))

    @classmethod
    def attach_class_definition(cls, query_method, definition):
        mro = definition.mro()
        if mro[1] is not object and mro[1] not in query_method.func_globals:
            cls.attach_class_definition(query_method, mro[1])
        cls.attach_method(query_method, definition)

    @classmethod
    def get_code(cls, name):
        if name not in QUERY_METHODS:
            raise AttributeError("%s not in %r" % (name, QUERY_METHODS))
        method = getattr(cls, name)
        if isinstance(method, (str, unicode, )):
            return unicode(method)
        else:
            return unicode(method.source)

    ### private ###

    @classmethod
    def _get_normalized_source(cls, func):
        source_lines, _ = inspect.getsourcelines(func)
        leading_whitespace = re.compile('\A\s*')
        found = leading_whitespace.search(source_lines[0])
        if found:
            count = len(found.group(0))
            source_lines = [x[count:-1] for x in source_lines
                            if x and len(x) >= count]
        decorator_line = re.compile('\A@')
        source_lines = [x for x in source_lines
                        if not decorator_line.search(x)]

        return '\n'.join(source_lines)

    @classmethod
    def _querymethod(cls, func):
        source = cls._get_normalized_source(func)
        setattr(func, 'source', source)
        res = staticmethod(func)
        return res


def attach_constant(method, constant, value):
    annotate.injectClassCallback('attach_constant', 3, 'attach_constant',
                                 method, constant, value)


def attach_method(query_method, method):
    annotate.injectClassCallback('attach_method', 3, 'attach_method',
                                 query_method, method)


def attach_code(query_method, code):
    annotate.injectClassCallback('attach_code', 3, 'attach_code',
                                 query_method, code)


class FormatableView(BaseView, formatable.Formatable):

    __metaclass__ = type(BaseView)

    @classmethod
    def __class__init__(cls, name, bases, dct):
        # FIXME: This is necessary to set _fields here to integrate with
        # formatable. If we just call Formatable.__class__init__ here it
        # for some reason operates on Formatable class dictionary, not
        # on FormatableView. It results in view sharing the reference
        # to the _fields list with the Formatable class. Damn you annotations!
        method = getattr(formatable.Formatable, '__class__init__')
        method.__func__(cls, name, bases, dct)

        method = getattr(BaseView, '__class__init__')
        method.__func__(cls, name, bases, dct)

    @classmethod
    def parse(cls, key, value, reduced):
        '''
        The point integrating with this is that the
        map method should yield as second value the dictionary. The keys
        of that dictionary should be defined as the fields of this class.
        '''
        if reduced:
            return value
        else:
            return cls(**value)


@feat.register_view
class DocumentByType(JavascriptView):

    design_doc_id = 'featjs'
    name = 'by_type'
    use_reduce = True

    map = format_block('''
    function(doc) {
        if (doc[".type"]) {
            emit([doc[".type"], doc[".version"]], null);
        }
    }''')

    reduce = "_count"

    @staticmethod
    def keys(type_name):
        if IRestorator.providedBy(type_name):
            type_name = type_name.type_name
        if not isinstance(type_name, (str, unicode)):
            raise ValueError(type_name)
        return dict(startkey=(type_name, ), endkey=(type_name, {}))

    @classmethod
    def fetch(cls, type_name):
        keys = cls.keys(type_name)
        keys.update({'reduce': False, 'include_docs': True})
        return keys


@feat.register_restorator
class DesignDocument(document.Document):

    type_name = "design"

    document.field('language', u'python')
    document.field('views', dict())
    document.field('filters', dict())

    disable_reduce_limit = False

    @classmethod
    def generate_from_views(cls, views):

        # id -> instance
        instances = dict()

        def get_instance(view):
            name = view.design_doc_id
            if name is None:
                raise ValueError("%r.design_doc_id is None" % (view, ))
            existing = instances.get(name, None)
            if not existing:
                doc_id = u"_design/%s" % (name, )
                existing = cls(doc_id=doc_id,
                               language=view.language)
                instances[name] = existing
            elif existing.language != view.language:
                raise ValueError("Language mismatch! Design document %s "
                                 "has language: %s, the view %s has language: "
                                 " %s" % (doc_id, existing.language,
                                          name, view.language))
            return existing

        for view in views:
            view = IViewFactory(view)
            if view.name is None:
                raise ValueError("%r.name is None!" % (view, ))
            instance = get_instance(view)
            entry = dict()
            if hasattr(view, 'map'):
                entry['map'] = view.get_code('map')
                if view.use_reduce:
                    entry['reduce'] = view.get_code('reduce')
                instance.views[view.name] = entry

            if hasattr(view, 'filter'):
                instance.filters[view.name] = view.get_code('filter')

            if view.disable_reduce_limit:
                instance.disable_reduce_limit = True

        return instances.values()


def generate_design_docs():
    generator = applications.get_view_registry().itervalues()
    return DesignDocument.generate_from_views(generator)


### helper methods usefull in view definitions ###


def iter_linked_id(doc, type_name):
    for row in doc.get('linked', list()):
        if row[0] == type_name:
            yield row[1]


def parse_enum(value):
    if isinstance(value, list) and len(value) == 2 and value[0] == '.enum':
        return value[1].split('.')[-1]


def parse_decimal(value):
    if isinstance(value, dict) and value.get('.type') == 'decimal':
        try:
            return float(value.get('.state'))
        except ValueError:
            pass
