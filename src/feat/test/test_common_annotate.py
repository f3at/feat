# -*- coding: utf-8 -*-
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

from feat.common import annotate

from . import common

# Method decorator
def accompany(accompaniment):
    def decorator(method):

        # Create a method for the accompaniment
        def get_accompaniment(self, *args, **kwargs):
            return self.name + " wants " + accompaniment

        # Inject the new method in the class
        annotate.injectAttribute("accompany", 3,
                                 accompaniment, get_accompaniment)

        # Inject the original method with a new name
        annotate.injectAttribute("accompany", 3,
                                 "original_" + method.__name__, method)

        # Wrapp a method call and add an accompaniment to its result
        def wrapper(self, *args, **kwargs):
            result = method(self, *args, **kwargs)
            return result + " and " + accompaniment

        # Call the class to register the decorator
        annotate.injectClassCallback("accompany", 3, "_decorator",
                                     accompaniment, method, wrapper)

        return wrapper
    return decorator


# Class annotation
def shop(animal, status):
    # Create a getter method
    def getter(self):
        return self.name + " " + animal + " is " + status
    annotate.injectAttribute("shop", 3, "get_" + animal, getter)
    return status


class Annotated(annotate.Annotable):

    class_init = False
    obj_init = False

    accompaniments = {}

    # Annotations

    shop("parrot", "dead")
    shop("slug", "mute")

    @classmethod
    def __class__init__(cls, name, bases, dct):
        cls.class_init = True

    @classmethod
    def _decorator(cls, accompaniment, old, new):
        cls.accompaniments[accompaniment] = (old, new)

    def __init__(self, name):
        self.obj_init = True
        self.name = name

    @accompany("beans")
    def spam(self, kind):
        return self.name + " like " + kind + " spam"

    @accompany("eggs")
    def bacon(self, kind):
        return self.name + " like " + kind + " bacon"


class TestAnnotation(common.TestCase):

    def testInitialization(self):
        self.assertTrue(Annotated.class_init)
        self.assertFalse(Annotated.obj_init)
        obj = Annotated("Monthy")
        self.assertTrue(obj.class_init)
        self.assertTrue(obj.obj_init)

    def testAnnotations(self):
        self.assertTrue(hasattr(Annotated, "get_parrot"))
        self.assertTrue(hasattr(Annotated, "get_slug"))
        obj = Annotated("Monthy")
        self.assertTrue(hasattr(obj, "get_parrot"))
        self.assertTrue(hasattr(obj, "get_slug"))
        self.assertEqual("Monthy parrot is dead", obj.get_parrot())
        self.assertEqual("Monthy slug is mute", obj.get_slug())

    def testDecorator(self):
        self.assertTrue(hasattr(Annotated, "spam"))
        self.assertTrue(hasattr(Annotated, "bacon"))
        self.assertTrue(hasattr(Annotated, "original_spam"))
        self.assertTrue(hasattr(Annotated, "original_bacon"))
        self.assertTrue(hasattr(Annotated, "beans"))
        self.assertTrue(hasattr(Annotated, "eggs"))

        self.assertTrue("beans" in Annotated.accompaniments)
        self.assertTrue("eggs" in Annotated.accompaniments)

        obj = Annotated("Monthy")

        self.assertEqual("Monthy like a lot of spam and beans",
                         obj.spam("a lot of"))
        self.assertEqual("Monthy like so much bacon and eggs",
                         obj.bacon("so much"))

        self.assertEqual("Monthy like a lot of spam",
                         obj.original_spam("a lot of"))
        self.assertEqual("Monthy like so much bacon",
                         obj.original_bacon("so much"))

        self.assertEqual("Monthy wants beans", obj.beans())
        self.assertEqual("Monthy wants eggs", obj.eggs())
