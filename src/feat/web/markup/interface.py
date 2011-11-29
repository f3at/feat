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

from zope.interface import Interface, Attribute

__all__ = ("MarkupError", "IPolicy", "IContext",
           "IElement", "IElementContent")


### exceptions ###


class MarkupError(Exception):
    pass


### interfaces ###


class IPolicy(Interface):
    """Defines a markup policy."""

    name = Attribute("name of the markup policy.")

    content_separator = Attribute("Separator between content items")

    def adapt_tag(tag):
        """Adapt tag name."""

    def is_leaf(tag):
        """Returns if the tag is a leaf."""

    def is_self_closing(tag):
        """returns if the specified tag require to have
        both opening and closing tags or can use '<XXX />'
        when there is not content."""

    def needs_no_closing(tag):
        """Returns if in addition to be a leaf the element is self closing,
        meaning instead of <TAG/> it is valide to have <TAG>."""

    def adapt_attr(attr):
        """Adapt attribute name."""

    def convert_attr(obj):
        """Convert tag attribute value to string."""

    def write_attr(doc, value):
        """Writes an attribute value into a document handling escaping.
        @param doc: the document to write into.
        @type doc: document.IWritableDocument
        @param value: the value to write.
        @type value: object()
        @return: a deferred fired with the specified document.
        @rtype: defer.Deferred
        """

    def convert_content(obj):
        """Convert an object to something write_content() knows about."""

    def write_separator(doc):
        """Writes a content separator into the document.
        @param doc: the document to write into.
        @type doc: document.IWritableDocument
        @return: a deferred fired with the specified document.
        @rtype: defer.Deferred
        """

    def write_content(doc, value):
        """
        Writes a content value into a document handling escaping.
        The value will be the result of a previous call to convert_content().
        @param doc: the document to write into.
        @type doc: document.IWritableDocument
        @param value: the value to write.
        @type value: object()
        @return: a deferred fired with the specified document.
        @rtype: defer.Deferred
        """

    def resolve_attr_error(self, failure):
        """Try resolving attribute asynchronous errors."""

    def resolve_content_error(self, failure):
        """Try resolving content asynchronous errors."""


class IElement(Interface):
    """A markup element."""

    context = Attribute("document context")
    parent = Attribute("Parent element")
    tag = Attribute("Element tag name")
    is_leaf = Attribute("If the element is a leaf")
    is_self_closing = Attribute("If the element is self closing")
    content = Attribute("Element content if not a leaf")

    def __call__(**attributes):
        """Adds the specified attributes to the element.
        @return: the content if not a leaf or self.
        @rtype: IElement or IElementContent
        """

    def __len__():
        """Returns the number of attributes."""

    def __contains__(attr):
        """Returns if the element contains the specified attribute."""

    def __getitem__(attr):
        """Retrieves the value of specified attribute."""

    def __setitem__(attr, value):
        """Sets the value of specified attribute."""

    def __iter__():
        """Iterate over attribute names."""

    def close():
        """If part of a document context, it close the element."""

    def render(doc):
        """Render the element using specified document.
        @param doc: the writable document to render to.
        @type doc: document.IWritableDocument
        @return: a deferred fired with the specified document
                 when the rendering is done.
        @rtype: defer.Deferred
        """


class IElementContent(Interface):

    element = Attribute("Element the content is for")

    def __call__(*values):
        """Adds the specified values or elements.
        Elements must not have a document context.
        @return: the element the content is for.
        @rtype: IElement
        """

    def __len__():
        """returns the number of elements."""

    def __getitem__(index):
        """Retrieves the element with specified index."""

    def __iter__():
        """Iterates of elements."""

    def append(self, value):
        """Adds the specified value or element.
        Elements must not have been created by a document context."""

    def context_append(self, value):
        """Only to be used by document context to add elements.
        Elements must have a document context."""

    def render(doc):
        """Renders the contained elements into the specified document.
        @param doc: the writable document to render to.
        @type doc: document.IWritableDocument
        @return: a deferred fired with the specified document
                 when the rendering is done.
        @rtype: defer.Deferred
        """

    def close():
        """If part of a document context, it close the element."""


class IContext(Interface):

    def close_element(element):
        """Close specified element that MUST be the current one."""
