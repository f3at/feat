from twisted.web import client


class Document(object):

    def __init__(self, category, name, url, content):
        self.category = category
        self.name = name
        self.url = url
        self.content = content


class Service(object):

    def __init__(self):
        self._docs = {} # {CATEGORY: {NAME: Document}}

    def count_documents(self):
        return sum(len(c) for c in self._docs.itervalues())

    def iter_categories(self):
        return self._docs.iterkeys()

    def iter_names(self, category):
        return self._docs[category].iterkeys()

    def get_document(self, category, name):
        return self._docs[category][name]

    def add_document(self, category, name, url):

        def got_page(content):
            doc = Document(category, name, url, content)
            self._docs.setdefault(category, {})[name] = doc
            return doc

        return client.getPage(str(url)).addCallback(got_page)

    def remove_document(self, category, name):
        del self._docs[category][name]
        if not self._docs[category]:
            del self._docs[category]
