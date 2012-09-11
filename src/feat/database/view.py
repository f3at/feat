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

from zope.interface import directlyProvides

from feat.common import formatable, annotate
from feat.database import document
from feat import applications

from feat.database.interface import IViewFactory
from feat.agents.application import feat

field = formatable.field


QUERY_METHODS = ['map', 'reduce', 'filter']


class BaseView(annotate.Annotable):

    name = None
    use_reduce = False
    design_doc_id = u'feat'

    @classmethod
    def __class__init__(cls, name, bases, dct):
        for method_name in QUERY_METHODS:
            method = dct.get(method_name, None)
            if callable(method):
                setattr(cls, method_name, cls._querymethod(method))
        directlyProvides(cls, IViewFactory)

    @classmethod
    def parse(cls, key, value, reduced):
        return value

    ### annotations ###

    @classmethod
    def attach_constant(cls, method, constant, value):
        if method.__name__ not in QUERY_METHODS:
            raise AttributeError("%s not in %r" % (method.__name__,
                                                   QUERY_METHODS))
        method.source += "\n%s = %r" % (constant, value)

    @classmethod
    def attach_method(cls, query_method, method):
        if query_method.__name__ not in QUERY_METHODS:
            raise AttributeError("%s not in %r" % (query_method.__name__,
                                                   QUERY_METHODS))
        source_lines, _ = inspect.getsourcelines(method)
        source = "\n".join([x[:-1] for x in source_lines])
        query_method.source += "\n%s" % (source, )

    @classmethod
    def attach_code(cls, query_method, code):
        if query_method.__name__ not in QUERY_METHODS:
            raise AttributeError("%s not in %r" % (query_method.__name__,
                                                   QUERY_METHODS))
        query_method.source += "\n%s" % (code, )

    ### private ###

    @classmethod
    def _querymethod(cls, func):
        source_lines, _ = inspect.getsourcelines(func)
        decorator_line = re.compile('\A\s*@')
        leading_whitespace = re.compile('\A\s*')
        source_lines = [x for x in source_lines
                        if not decorator_line.search(x)]
        found = leading_whitespace.search(source_lines[0])
        if found:
            count = len(found.group(0))
            source_lines = [x[count:-1] for x in source_lines
                            if x and len(x) >= count]

        source = '\n'.join(source_lines)
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


@feat.register_restorator
class DesignDocument(document.Document):

    type_name = "design"

    document.field('language', u'python')
    document.field('views', dict())
    document.field('filters', dict())

    @classmethod
    def generate_from_views(cls, views):

        # id -> instance
        instances = dict()

        def get_instance(name):
            existing = instances.get(name, None)
            if not existing:
                doc_id = u"_design/%s" % (name, )
                existing = cls(doc_id=doc_id)
                instances[name] = existing
            return existing

        for view in views:
            view = IViewFactory(view)
            instance = get_instance(view.design_doc_id)
            entry = dict()
            if hasattr(view, 'map'):
                entry['map'] = unicode(view.map.source)
                if view.use_reduce:
                    if isinstance(view.reduce, (str, unicode, )):
                        red = unicode(view.reduce)
                    else:
                        red = unicode(view.reduce.source)
                    entry['reduce'] = red
                instance.views[view.name] = entry

            if hasattr(view, 'filter'):
                instance.filters[view.name] = unicode(view.filter.source)
        return instances.values()


def generate_design_docs():
    generator = applications.get_view_registry().itervalues()
    return DesignDocument.generate_from_views(generator)
