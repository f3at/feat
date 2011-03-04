import os
from ConfigParser import (
        RawConfigParser,
        NoSectionError,
        NoOptionError)

import glib

manager = None


class SettingsManager(RawConfigParser):

    def __init__(self):
        RawConfigParser.__init__(self)

        config_home = glib.get_user_config_dir()
        config_home = os.path.join(config_home, 'fltsim')
        if not os.path.exists(config_home):
            os.makedirs(config_home)

        self.location = os.path.join(config_home, 'settings.ini')

        self._dirty = False
        self._saving = False

        try:
            self.read(self.location)
        except:
            pass

       #Save settings every 30 secs
        glib.timeout_add_seconds(30, self._timeout_save)

    def _timeout_save(self):
        self.save()
        return True

    def set_option(self, option, value):
        splitvals = option.split('/')
        section, key = "/".join(splitvals[:-1]), splitvals[-1]

        try:
            self.set(section, key, value)
        except NoSectionError:
            self.add_section(section)
            self.set(section, key, value)

        self._dirty = True

    def get_option(self, option, default=None):
        splitvals = option.split('/')
        section, key = "/".join(splitvals[:-1]), splitvals[-1]

        try:
            value = self.get(section, key)
        except NoSectionError:
            value = default
        except NoOptionError:
            value = default
        return value

    def get_int_option(self, option, default=None):
        return int(self.get_option(option, default))

    def save(self):
        if self._saving or not self._dirty:
            return

        self._saving = True
        with open(self.location + '.new', 'w') as f:
            self.write(f)
            f.flush()

        os.rename(self.location + '.new', self.location)
        self._saving = False
        self._dirty = False


manager = SettingsManager()
get_option = manager.get_option
get_int_option = manager.get_int_option
set_option = manager.set_option
