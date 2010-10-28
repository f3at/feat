

class Obj(object):

    @classmethod
    def restore(cls, snapshot):
        o = cls.__new__(cls)
        o.recover(snapshot)
        return o

    def __init__(self, some, param):
        self._some = some
        self._param = param

    def __recover__(self, snapshot):
        self._some, self._param = snapshot

    def snapshot(self):
        return (self._some, self._param)


    def __repr__(self):
        return "<%s some=%r param=%r>" % (type(self), self._some, self._param)


a = Obj(42, 18)
print a

s = a.snapshot()
print s

b = Obj.restore(s)
print b