import os
import re
import datetime
from xml.dom import minidom
from xml.parsers.expat import ExpatError

import glib


class HistoryLogger(object):

    def __init__(self, history_dir="history"):
        config_home = glib.get_user_config_dir()
        self.history_dir = os.path.join(config_home, 'fltsim', history_dir)
        if not os.path.exists(self.history_dir):
            os.makedirs(self.history_dir)

        self.documents = {}
        self.current_date = datetime.datetime.now().date()
        self.dates = []

    def load_dates(self):
        now = datetime.datetime.now().date()
        if now != self.current_date or not self.dates:
            self.current_date = now
            self.dates = []
            for f in os.listdir(self.history_dir):
                try:
                    doc = minidom.parse(os.path.join(self.history_dir, f))
                    date = doc.getElementsByTagName('date')[0]
                    year = date.getAttribute('year')
                    month = date.getAttribute('month')
                    cmds = doc.getElementsByTagName('cmd')
                    for cmd in cmds:
                        strdate = '%s %s %s' % (
                                year,
                                month,
                                cmd.getAttribute('time'))
                        date = datetime.datetime.strptime(
                            strdate,
                            '%Y %m %d %H:%M:%S').date()
                        if date not in self.dates:
                            self.dates.append(date)
                    del doc
                except (IOError, IndexError, ExpatError):
                    continue
            self.dates.sort(reverse=True)
        return self.dates

    def read_commands(self, date):
        doc, _ = self._get_document(date)
        commands = []
        cmds = doc.getElementsByTagName('cmd')
        for cmd in cmds:
            d = doc.getElementsByTagName('date')[0]
            year = d.getAttribute('year')
            month = d.getAttribute('month')
            cmd_strtime = '%s %s %s' % (year, month, cmd.getAttribute('time'))
            cmd_time = datetime.datetime.strptime(
                            cmd_strtime,
                            '%Y %m %d %H:%M:%S')
            if date == cmd_time.date():
                text = cmd.firstChild.data.strip()
                commands.append([cmd_time, text])
            if date < cmd_time.date():
                break
        commands.sort(reverse=True)
        return commands

    def get_filename(self, date):
        filename = 'command-%d%d.xml' % (date.year, date.month)
        return os.path.join(self.history_dir, filename)

    def _get_id(self, date):
        return '%d%d' % (date.year, date.month)

    def _get_document(self, date):
        id = self._get_id(date)
        if not id in self.documents:
            try:
                f = self.get_filename(date)
                doc = minidom.parse(f)
                root = doc.getElementsByTagName('command-history')[0]
                self.documents[id] = (doc, root)
            except (IOError, IndexError, ExpatError):
                doc = minidom.Document()
                root = doc.createElement('command-history')
                root.setAttribute('version', '0.1')
                doc.appendChild(root)
                self.documents[id] = (doc, root)
        return self.documents[id]

    def append_command(self, cmd):
        date = datetime.datetime.now()
        doc, root = self._get_document(date)
        if not root.hasChildNodes():
            elem = doc.createElement('date')
            elem.setAttribute('year', str(date.year))
            elem.setAttribute('month', str(date.month))
            root.appendChild(elem)

        cmd_elem = doc.createElement('cmd')
        cmd_elem.setAttribute('time', date.strftime('%d %H:%M:%S'))
        txt_elem = doc.createTextNode(cmd)
        cmd_elem.appendChild(txt_elem)
        root.appendChild(cmd_elem)
        self._save_to_disk(date, doc)

    def _save_to_disk(self, date, doc):
        filename = self.get_filename(date)
        f = open(filename, 'wb')
        f.write(doc.toxml())
        f.close()
