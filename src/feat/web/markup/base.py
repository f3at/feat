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

from xml.sax import saxutils

from twisted.python import failure
from zope.interface import implements

from feat.common import defer
from feat.web import document

from feat.web.markup.interface import *


### classes ###


class BasePolicy(object):

    implements(IPolicy)

    name = "base"

    content_separator = None

    def adapt_tag(self, tag):
        return tag.lower()

    def is_leaf(self, tag):
        return False

    def needs_no_closing(self, tag):
        return False

    def is_self_closing(self, tag):
        return True

    def adapt_attr(self, attr):
        return attr.lower()

    def convert_attr(self, obj):
        return unicode(obj)

    def write_attr(self, doc, value):
        doc.write(saxutils.quoteattr(value))
        return defer.succeed(doc)

    def convert_content(self, obj):
        return unicode(obj)

    def write_separator(self, doc):
        if self.content_separator:
            doc.write(self.content_separator)
        return defer.succeed(doc)

    def write_content(self, doc, value):
        doc.write(saxutils.escape(value))
        return defer.succeed(doc)

    def resolve_attr_error(self, failure):
        return failure

    def resolve_content_error(self, failure):
        return failure


class ElementContent(object):

    __slots__ = ("element", "_policy", "_children")

    implements(IElementContent)

    def __init__(self, element, policy):
        self.element = element
        self._policy = policy
        self._children = []

    ### IElementContent ###

    def __call__(self, *elements):
        for element in elements:
            self.append(element)
        return self.element

    def __len__(self):
        return len(self._children)

    def __getitem__(self, index):
        return self._unwrap_child(self._children[index])

    def __iter__(self):
        return (self._unwrap_child(v) for v in self._children)

    def append(self, value):
        self._children.append(self._wrap_child(value))

    def render(self, doc):
        d = defer.succeed(document.IWritableDocument(doc))
        separate = False
        for child in self._children:
            if separate:
                d.addCallback(self._policy.write_separator)
            d.addCallback(self._render_child, child)
            separate = True
        return d

    def close(self):
        return self.element.close()

    ### private ###

    def _render_child(self, doc, child):
        if isinstance(child, defer.Deferred):
            d = defer.Deferred()
            args = (doc, d)
            child.addCallbacks(self._got_value, self._value_error,
                               callbackArgs=args, errbackArgs=args)
            return d

        if IElement.providedBy(child):
            return child.render(doc)

        return self._policy.write_content(doc, child)

    def _got_value(self, value, doc, trigger=None):
        d = defer.succeed(doc)
        d.addCallback(self._render_child, value)
        if trigger is not None:
            d.addCallback(trigger.callback)
        d.addCallback(defer.override_result, value)
        return d

    def _value_error(self, failure, _doc, trigger=None):
        if trigger is not None:
            trigger.errback(failure)
        return failure

    def _wrap_child(self, value):
        if isinstance(value, failure.Failure):
            return value
        if isinstance(value, defer.Deferred):
            value.addCallbacks(self._wrap_callback, self._wrap_errback)
            return value
        return self._process_child(value)

    def _wrap_callback(self, element):
        return self._process_child(element)

    def _wrap_errback(self, failure):
        return self._wrap_child(self._policy.resolve_content_error(failure))

    def _process_child(self, element):
        if IElementContent.providedBy(element):
            element = element.element
        if IElement.providedBy(element):
            return element
        return self._policy.convert_content(element)

    def _unwrap_child(self, value):
        if isinstance(value, defer.Deferred):
            d = defer.Deferred()
            value.addCallbacks(self._unwrap_callback, self._unwrap_errback,
                               callbackArgs=(d, ), errbackArgs=(d, ))
            return d
        return value

    def _unwrap_callback(self, param, d):
        d.callback(param)
        return param

    def _unwrap_errback(self, failure, d):
        d.errback(failure)
        return failure


class Element(object):

    __slots__ = ("_tag", "_policy", "_attrs", "_content", "context", "parent")

    implements(IElement)

    content_factory = ElementContent

    def __init__(self, name, policy, parent=None, context=None):
        self.parent = IElement(parent) if parent is not None else None
        self.context = IContext(context) if context is not None else None
        self._policy = IPolicy(policy)
        self._tag = policy.adapt_tag(name)
        self._attrs = {}
        self._content = None
        if not self.is_leaf:
            self._content = self.content_factory(self, self._policy)

    ### IElement ###

    @property
    def tag(self):
        return self._tag

    @property
    def is_leaf(self):
        return self._policy.is_leaf(self._tag)

    @property
    def needs_no_closing(self):
        return self._policy.needs_no_closing(self._tag)

    @property
    def is_self_closing(self):
        return self._policy.is_self_closing(self._tag)

    @property
    def content(self):
        if self._content is None:
            raise MarkupError("With %s markup policy, '%s' tags do not have "
                              "content" % (self._policy.name, self._tag))
        return self._content

    def __call__(self, **kwargs):
        for k, v in kwargs.iteritems():
            self.__setitem__(k, v)
        return self if self._content is None else self._content

    def __len__(self):
        return len(self._attrs)

    def __contains__(self, attr):
        adapted_attr = self._policy.adapt_attr(attr)
        return  adapted_attr in self._attrs

    def __getitem__(self, attr):
        adapted_attr = self._policy.adapt_attr(attr)
        return self._unwrap_value(self._attrs[adapted_attr])

    def __setitem__(self, attr, value):
        adapted_attr = self._policy.adapt_attr(attr)
        self._attrs[adapted_attr] = self._wrap_value(value)

    def __iter__(self):
        return iter(self._attrs)

    def close(self):
        if self.context is None:
            raise MarkupError("cannot close element '%s', "
                              "it do not have context" % (self._tag, ))
        return self.context.close_element(self)

    def render(self, doc):

        def start_tag(doc, name):
            doc.writelines(["<", name])
            return doc

        def start_attr(doc, name, value):
            doc.writelines([" ", name])

            if isinstance(value, defer.Deferred):
                d = defer.Deferred()
                args = (doc, d)
                value.addCallbacks(self._got_value, self._value_error,
                                   callbackArgs=args, errbackArgs=args)
                return d

            if value is not None:
                doc.write("=")
                return self._policy.write_attr(doc, value)

            return doc

        def close_tag(doc, name):
            if self.is_leaf:
                if self.needs_no_closing:
                    doc.write(">")
                elif not self.is_self_closing:
                    doc.writelines(["></", name, ">"])
                else:
                    doc.write(" />")
            elif self.content:
                doc.write(">")
            elif not self.is_self_closing:
                doc.writelines(["></", name, ">"])
            else:
                doc.write(" />")
            return doc

        def close_element(doc, name):
            doc.writelines(["</", name, ">"])
            return doc

        doc = document.IWritableDocument(doc)
        d = defer.succeed(doc)
        d.addCallback(start_tag, self._tag)
        keys = self._attrs.keys()
        keys.sort()
        for name in keys:
            d.addCallback(start_attr, name, self._attrs[name])
        d.addCallback(close_tag, self._tag)
        if self._content:
            d.addCallback(self.content.render)
            d.addCallback(close_element, self._tag)
        return d

    def as_string(self, mime_type=None, encoding=None):
        doc = document.WritableDocument(mime_type, encoding)
        d = self.render(doc)
        d.addCallback(document.WritableDocument.get_data)
        return d

    ### private ###

    def _got_value(self, value, doc, trigger=None):

        if value is not None:
            doc.write("=")
            d = defer.succeed(doc)
            d.addCallback(self._policy.write_attr, value)
            if trigger is not None:
                d.addCallback(trigger.callback)
            d.addCallback(defer.override_result, value)
            return d

        trigger.callback(doc)
        return value

    def _value_error(self, failure, _doc, trigger=None):
        if trigger is not None:
            trigger.errback(failure)
        return failure

    def _wrap_value(self, value):
        if isinstance(value, failure.Failure):
            return value
        if isinstance(value, defer.Deferred):
            value.addCallbacks(self._wrap_callback, self._wrap_errback)
            return value
        return self._process_value(value)

    def _wrap_callback(self, value):
        return self._process_value(value)

    def _wrap_errback(self, failure):
        return self._wrap_value(self._policy.resolve_attr_error(failure))

    def _process_value(self, value):
        if (IElement.providedBy(value) or
            IElementContent.providedBy(value)):
            raise MarkupError("Attribute values cannot be markup elements")
        if value is None:
            return None
        return self._policy.convert_attr(value)

    def _unwrap_value(self, value):
        if isinstance(value, defer.Deferred):
            d = defer.Deferred()
            value.addCallbacks(self._unwrap_callback, self._unwrap_errback,
                               callbackArgs=(d, ), errbackArgs=(d, ))
            return d
        return value

    def _unwrap_callback(self, param, d):
        d.callback(param)
        return param

    def _unwrap_errback(self, failure, d):
        d.errback(failure)
        return failure


class ElementBuilder(object):

    __slots__ = ("_policy", )

    element_factory = Element

    def __init__(self, policy):
        self._policy = IPolicy(policy)

    def __getattr__(self, attr):
        if attr.startswith("__"):
            raise AttributeError(attr)
        return self.element_factory(attr, self._policy)


class Document(object):
    """Helper class to keep element hierarchy context."""

    __slots__ = ("_policy", "_elements", "_current")

    implements(IContext)

    element_factory = Element

    def __init__(self, policy):
        self._policy = IPolicy(policy)
        self._elements = []
        self._current = None

    def __getattr__(self, attr):
        if attr.startswith("__"):
            raise AttributeError(attr)

        element = self.element_factory(attr,
                                       policy=self._policy,
                                       parent=self._current,
                                       context=self)

        if self._current is None:
            self._elements.append(element)
        else:
            self._current.content.append(element)

        if not element.is_leaf:
            self._current = element

        return element

    def render(self, doc):
        """Render all elements using specified document.
        @param doc: the writable document to render to.
        @type doc: document.IWritableDocument
        @return: a deferred fired with the specified document
                 when the rendering is done.
        @rtype: defer.Deferred
        """
        d = defer.succeed(doc)
        for element in self._elements:
            d.addCallback(element.render)
        return d

    def as_string(self, mime_type=None, encoding=None):
        doc = document.WritableDocument(mime_type, encoding)
        d = self.render(doc)
        d.addCallback(document.WritableDocument.get_data)
        return d

    ### IContext ###

    def close_element(self, element):
        if self._current is None:
            raise MarkupError("Ask to close tag '%s' when there is no "
                              "current element" % (element.tag, ))
        if element is not self._current:
            raise MarkupError("Ask to close tag '%s' when the current one is "
                              "'%s'" % (element.tag, self._current.tag))
        self._current = element.parent
        return self._current
