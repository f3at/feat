# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
import re


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


def format_block(block):
    '''
    Format the given block of text, trimming leading/trailing
    empty lines and any leading whitespace that is common to all lines.
    The purpose is to let us list a code block as a multiline,
    triple-quoted Python string, taking care of indentation concerns.
    '''
    # separate block into lines
    lines = str(block).split('\n')
    # remove leading/trailing empty lines
    while lines and not lines[0]:
        del lines[0]
    while lines and not lines[-1]:
        del lines[-1]
    # look at first line to see how much indentation to trim
    ws = re.match(r'\s*', lines[0]).group(0)
    if ws:
        lines = map(lambda x: x.replace(ws, '', 1), lines)
    # remove leading/trailing blank lines (after leading ws removal)
    # we do this again in case there were pure-whitespace lines
    while lines and not lines[0]:
        del lines[0]
    while lines and not lines[-1]:
        del lines[-1]
    return '\n'.join(lines) + '\n'
