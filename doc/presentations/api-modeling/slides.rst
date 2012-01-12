API Modeling Presentation
=========================

Sebastien Merle
---------------

13/01/2012
..........


Requirements
============

    * REST Friendly.
    * Non Intrusive.
    * Self Documented.
    * Asynchronous.
    * Flexible.


Solution
========

    * Model/View Separation.
    * Fully Asynchronous.
    * Declarativish Programing.
    * Static Introspection.
    * Code Reusability.


Just Show Me |(TM)|
===================

**A Categorized Web Page Store**:

    * Service
    * Application
    * Model Iterations

Try It Yourself |(TM)|::

  cd doc/presentation/api-modeling
  ../../../env python demo_app.py [VERSION]

.. |(TM)| unicode:: U+2122


Service: Document Class
=======================

.. code-block:: python

  class Document(object):

      def __init__(self, category, name, url, content):
          self.category = category
          self.name = name
          self.url = url
          self.content = content


Service: Main Class
===================

.. code-block:: python

  from twisted.web import client

  class Service(object):

      def __init__(self):
          self._docs = {} # {CATEGORY: {NAME: Document}}

      def count_documents(self):
          return sum(len(c) for c in self._docs.itervalues())


Service: Getting Information
============================

.. code-block:: python

      def iter_categories(self):
          return self._docs.iterkeys()

      def iter_names(self, category):
          return self._docs[category].iterkeys()

      def get_document(self, category, name):
          return self._docs[category][name]


Service: Adding Documents
=========================

.. code-block:: python

      def add_document(self, category, name, url):

          def got_page(content):
              doc = Document(category, name, url, content)
              self._docs.setdefault(category, {})[name] = doc
              return doc

          return client.getPage(str(url)).addCallback(got_page)


Service: Removing Documents
===========================

.. code-block:: python

      def remove_document(self, category, name):
          del self._docs[category][name]
          if not self._docs[category]:
              del self._docs[category]


Application
===========

.. code-block:: python

  from twisted.internet import reactor
  import demo_service

  def initialize():
      global service
      service.add_document("search", "altavista", "http://www.altavista.com")
      service.add_document("search", "yahoo", "http://www.yahoo.com")
      service.add_document("news", "slashdot", "http://slashdot.org")

  service = demo_service.Service()
  reactor.callWhenRunning(initialize)

  reactor.run()


Application: Publish API
========================

.. code-block:: python

  from feat.common import log
  from feat.gateway import gateway

  import demo_models

  ...

  log.FluLogKeeper.init()
  api = gateway.Gateway(service, 7878, "localhost", label="Demo")
  reactor.callWhenRunning(api.initiate)


Minimal Model
=============

.. code-block:: python

  @adapter.register(demo_service.Service, model.IModel)
  class Service(model.Model):
      model.identity("service")
      model.attribute("size", value.Integer(),
                      call.source_call("count_documents"))


Done ! (1)
==========

HTTP API::

  http://localhost:7878/

JSON API::

  alias json-get='curl -H "Accept: application/json"'
  alias json-put='curl -H "Accept: application/json" -H "Content-Type: application/json" -X PUT -d'
  alias json-post='curl -H "Accept: application/json" -H "Content-Type: application/json" -X POST -d'
  alias json-delete='curl -H "Accept: application/json" -X DELETE'

  json-get http://localhost:7878/
  json-get http://localhost:7878/size


Publishing Documents
====================

Defining REST interface::

  http://localhost:7878/size
  http://localhost:7878/documents/$CATEGORY/$NAME
  http://localhost:7878/documents/$CATEGORY/$NAME/url
  http://localhost:7878/documents/$CATEGORY/$NAME/content


Documents Model
===============

    * Dynamic Items.

.. code-block:: python

  class Documents(model.Collection):
      model.identity("service.documents")
      model.child_model("service.documents.CATEGORY")
      model.child_names(call.source_call("iter_categories"))
      model.child_source(effect.context_value("key"))


Category Model
==============

.. code-block:: python

  class Category(model.Model):
      model.identity("service.documents.CATEGORY")
      model.attribute("category", value.String(),
                      effect.context_value("source"))

TEST ! (2)


Using Views
===========

In class ``Documents``:

.. code-block:: python

  model.child_view(effect.context_value("key"))

In class ``Category``:

.. code-block:: python

  model.attribute("category", value.String(),
                  effect.context_value("view"))

TEST ! (3)


Category Model
==============

.. code-block:: python

  class Category(model.Collection):
      model.identity("service.documents.CATEGORY")
      model.child_model("service.documents.CATEGORY.NAME")
      model.child_names(call.model_call("_iter_documents"))
      model.child_view(getter.model_get("_get_document"))

      def _iter_documents(self):
          return self.source.iter_names(self.view)

      def _get_document(self, name):
          return self.source.get_document(self.view, name)


Document Model
==============

.. code-block:: python

  class Document(model.Model):
      model.identity("service.documents.CATEGORY.NAME")
      model.attribute("category", value.String(),
                      getter.view_getattr())
      model.attribute("name", value.String(),
                      getter.view_getattr())
      model.attribute("url", value.String(),
                      getter.view_getattr())
      model.attribute("content", value.Binary("text/html"),
                      getter.view_getattr())


Done ! (4)
==========

HTTP API::

  http://localhost:7878/documents/news/slashdot
  http://localhost:7878/documents/news/slashdot/url
  http://localhost:7878/documents/news/slashdot/content

JSON API::

  json-get http://localhost:7878/documents/search/yahoo
  json-get http://localhost:7878/documents/search/yahoo/content
  curl http://localhost:7878/documents/search/yahoo/content


Mutable Attributes
==================

Making URL attribute mutable in class ``Document``:

.. code-block:: python

    model.attribute("url", value.String(),
                    getter.view_getattr(),
                    setter.view_setattr())


Done ! (5)
==========

HTTP API::

  http://localhost:7878/documents/news/slashdot

JSON API::

  json-put '"http://www.google.com"' http://localhost:7878/documents/search/yahoo/url


Adding Documents
================

.. code-block:: python

  class CreateDocument(action.Action):
      action.param("category", value.String())
      action.param("name", value.String())
      action.param("url", value.String())
      action.effect(call.source_perform("add_document"))


In ``Documents`` class:

.. code-block:: python

  model.action("post", CreateDocument, label="Create Document")

TEST ! (6)


Returning a Response
====================

In class ``CreateDocument``:

.. code-block:: python

  action.effect(call.action_filter("_respond"))
  action.result(value.Response())

  def _respond(self, doc):
      ref = reference.Local("documents", doc.category, doc.name)
      return response.Created(ref, "Document Created")


Done ! (7)
==========

JSON API::

  json-post '{}' http://localhost:7878/documents
  json-post '{"name": "bing", "category": "search", "url": "http://www.bing.com"}' http://localhost:7878/documents
  json-post '{"name": 1, "category": 2, "url": 3}' http://localhost:7878/documents


Custom Parameters
=================

.. code-block:: python

  class CategoryValue(value.String):
      value.option("search", label="Search Engines")
      value.option("news", label="News Sites", is_default=True)
      value.options_only()

In class ``CreateDocument``:

.. code-block:: python

  action.param("category", CategoryValue())


Done ! (8)
==========

HTML API::

 http://localhost:7878/documents

JSON API::

  json-post '{"name": "dummy", "category": "bad", "url": "http://www.dummy.com"}' http://localhost:7878/documents


Removing Documents
==================

In class ``Document``:

.. code-block:: python

  model.delete("del", call.model_call("_delete"))

  def _delete(self):
      self.source.remove_document(self.view.category, self.view.name)
      ref = reference.Local("documents")
      return response.Deleted(ref, "Document Deleted")


Done ! (9)
==========

HTML API::

 http://localhost:7878/documents/search/yahoo

JSON API::

  json-delete http://localhost:7878/documents/search/yahoo


Formating Hints
===============

In class ``Service``:

.. code-block:: python

  model.meta("html-order", "size, documents")

In class ``Documents``:

.. code-block:: python

  model.meta("html-render", "array, 2")
  model.meta("html-render", "array-columns, category, name, url")


Formating Hints
===============

In class ``Category``:

.. code-block:: python

  model.meta("html-render", "array, 1")
  model.meta("html-render", "array-columns, name, url")

In class ``Document``:

.. code-block:: python

  model.meta("html-order", "category, name, url, content")
  model.item_meta("name", "html-link", "owner")

TEST !


And For Free
============

    * SSL.
    * Client Certificate Validation.
    * External Access Officer.
    * Self-Described JSON API


Future
======

    * Support for more document types.
    * Documentation generation
    * Model proxy
    * Dynamic reloading


.. header::

  API Modeling Presentation








