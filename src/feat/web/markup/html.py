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

from zope.interface import Attribute, implements

from feat.web.markup import base

from feat.web.markup.interface import *


### exceptions ###


class InvalidElement(base.MarkupError):
    pass


class DeprecatedElement(InvalidElement):
    pass


### interfaces ###


class IHtmlPolicy(IPolicy):

    doctype = Attribute("Document doctype header")


### classes ###


class BasePolicy(base.BasePolicy):

    doctype = None

    name = "html"

    attr_lookup = {"_class": "class",
                   "class_": "class",
                   "Class": "class",
                   "http_equiv": "http-equiv",
                   "accept_charset": "accept-charset"}

    leaf_tags = set(["area", "base", "br", "col", "frame", "hr", "img",
                     "input", "meta", "param"])

    node_tags = set(["a", "abbr", "acronym", "address", "b", "bdo", "big",
                     "blockquote", "body", "button", "caption", "cite",
                     "code", "colgroup", "dd", "del", "dfn", "div", "dl",
                     "dt", "em", "fieldset", "form", "frameset", "h1", "h2",
                     "h3", "h4", "h5", "h6", "head", "html", "i", "iframe",
                     "ins", "kbd", "label", "legend", "li", "link", "map",
                     "noframes",
                     "noscript", "object", "ol", "optgroup", "option", "p",
                     "pre", "q", "samp", "script", "select", "small", "span",
                     "strong", "style", "sub", "sup", "table", "tbody", "td",
                     "textarea", "tfoot", "th", "thead", "title", "tr", "tt",
                     "ul", "var"])

    valid_tags = leaf_tags | node_tags

    deprecated_tags = set([])

    def adapt_tag(self, tag):
        tag = tag.lower()
        if tag in self.deprecated_tags:
            raise DeprecatedElement("Following %s markup policy, "
                                    "'%s' is a deprecated tag"
                                    % (self.name, tag))
        if tag not in self.valid_tags:
            raise InvalidElement("Following %s markup policy, "
                                 "'%s' is not a valid tag"
                                 % (self.name, tag))
        return tag

    def is_leaf(self, tag):
        return tag.lower() in self.leaf_tags

    def is_self_closing(self, tag):
        return False

    def needs_no_closing(self, tag):
        return tag.lower() in self.leaf_tags

    def adapt_attr(self, attr):
        return self.attr_lookup.get(attr, attr)


class StrictPolicy(BasePolicy):

    implements(IHtmlPolicy)

    doctype = "<!DOCTYPE HTML PUBLIC " \
              "'-//W3C//DTD HTML 4.01//EN' " \
              "'http://www.w3.org/TR/html4/strict.dtd'>"

    deprecated_tags = set(["basefont", "isindex", "applet", "center",
                           "dir", "font", "menu", "s", "strike", "u"])


class LoosePolicy(BasePolicy):

    implements(IHtmlPolicy)

    doctype = "<!DOCTYPE HTML PUBLIC " \
              "'-//W3C//DTD HTML 4.01 Transitional//EN' " \
              "'http://www.w3.org/TR/html4/loose.dtd'>"

    leaf_tags = BasePolicy.leaf_tags | set(["basefont", "isindex"])

    node_tags = BasePolicy.node_tags | set(["applet", "center", "dir", "font",
                                            "menu", "s", "strike", "u"])

    valid_tags = leaf_tags | node_tags

    def adapt_tag(self, tag):
        # Allows capital tags
        BasePolicy.adapt_tag(self, tag)
        return tag


class Document(base.Document):

    def __init__(self, policy, title=None):
        base.Document.__init__(self, IHtmlPolicy(policy))
        self.html = self.html()()
        self.head = self.head()()
        if title is not None:
            self.title()(title).close()
        self.head.close()
        self.body = self.body()()

    def render(self, doc):
        doc.write(self._policy.doctype)
        doc.write("\n")
        return base.Document.render(self, doc)


loose_tags = base.ElementBuilder(LoosePolicy())
strict_tags = base.ElementBuilder(StrictPolicy())
tags = strict_tags
