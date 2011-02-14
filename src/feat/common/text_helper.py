# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4


class Table(object):

    def __init__(self, fields, lengths):
        self.fields = fields
        self.lengths = lengths

    def render(self, iterator):
        result = "".join(
            [x.ljust(length) for x, length in zip(self.fields, self.lengths)])
        result = [result, "^" * len(result)]
        for record in iterator:
            formated = [str(val).ljust(length) \
                        for val, length in zip(record, self.lengths)]
            result += ["".join(formated)]
        return '\n'.join(result)
