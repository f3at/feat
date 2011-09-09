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

from feat.common import formatable, decorator, log, annotate
from feat.agents.base import document

from feat.interface.view import *


@decorator.simple_class
def register(view):
    global _registry

    view = IViewFactory(view)
    if view.name in _registry:
        log.warning('view-registry', 'View with the name %s is already '
                    'registered and points to %r. Overwriting!', view.name,
                    _registry[view.name])
    _registry[view.name] = view
    return view

field = formatable.field


class BaseView(annotate.Annotable):

    name = None
    use_reduce = False

    @classmethod
    def __class__init__(cls, name, bases, dct):
        for method_name in 'map', 'reduce':
            method = dct.get(method_name, None)
            if callable(method):
                setattr(cls, method_name, cls._querymethod(method))
        directlyProvides(cls, IViewFactory)

    def map(doc):
        if False:
            yield

    def reduce(keys, values):
        pass

    @classmethod
    def parse(cls, key, value, reduced):
        return value

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


### module private ###


# name -> IViewFactory
_registry = dict()


def _iterviews():
    global _registry
    return _registry.itervalues()


@document.register
class DesignDocument(document.Document):

    document_type = "design"

    document.field('doc_id', u"_design/%s" % (DESIGN_DOC_ID, ), "_id")
    document.field('language', u'python')
    document.field('views', dict())

    @classmethod
    def generate_from_views(cls, views):
        instance = cls()
        for view in views:
            view = IViewFactory(view)
            entry = dict()
            entry['map'] = unicode(view.map.source)
            if view.use_reduce:
                if isinstance(view.reduce, (str, unicode, )):
                    red = unicode(view.reduce)
                else:
                    red = unicode(view.reduce.source)
                entry['reduce'] = red
            instance.views[view.name] = entry
        return instance


def generate_design_doc():
    return DesignDocument.generate_from_views(_iterviews())
