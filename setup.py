#!/usr/bin/env python
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

import os
import subprocess

from setuptools import setup, find_packages
from setuptools.command.sdist import sdist as _sdist


def call(root, path, *args):
    p = subprocess.Popen([path] + list(args), stdout=subprocess.PIPE, cwd=root)
    p.wait()
    if p.returncode:
        raise Exception("Sub process %s failed" % (path, ))
    return p.stdout.read()


root_dir = os.path.dirname(os.path.abspath(__file__))
#tools_dir = os.path.join(root_dir, "tools")
#git_ver_gen = os.path.join(tools_dir, "git-version-gen")
tarball_ver_filename = ".tarball-version"
tarball_ver_filepath = os.path.join(root_dir, tarball_ver_filename)
paisley_reldir = os.path.join("src", "feat", "extern", "paisley")
paisley_dir = os.path.join(root_dir, paisley_reldir)
paisley_pkg = os.path.join(paisley_dir, "paisley")


NAME = 'feat'
#VERSION = call(root_dir, git_ver_gen, tarball_ver_filepath)
VERSION = '0.15'
DESCRIPTION = 'Flumotion Asynchronous Autonomous Agent Toolkit'
LONG_DESC = DESCRIPTION
AUTHOR = 'Flumotion Developers',
AUTHOR_EMAIL = 'coreteam@flumotion.com',
URL = 'https://github.com/f3at/feat',
DOWNLOAD_URL = ('https://github.com/downloads/f3at/feat/%s-%s.tar.gz'
                % (NAME, VERSION)),
LICENSE = "GPL"
PLATFORMS = ['any']
REQUIRES = ['twisted', 'twisted.web']
SETUP_REQUIRES = ['setuptools>=0.6c9']
INSTALL_REQUIRES = ['Twisted>=10.1']
KEYWORDS = ['twisted', 'agent', 'framework']
CLASSIFIERS = [
    'Development Status :: 4 - Beta',
    'Environment :: No Input/Output (Daemon)',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: GNU General Public License (GPL)',
    'Natural Language :: English',
    'Operating System :: POSIX :: Linux',
    'Programming Language :: Python :: 2.6',
    'Topic :: Software Development :: Libraries :: Application Frameworks']


if not os.path.exists(paisley_pkg):
    call(root_dir, "git", "submodule", "init")
    call(root_dir, "git", "submodule", "update")


class sdist(_sdist):

    def run(self):
        have_tarball_ver = os.path.exists(tarball_ver_filepath)
        try:
            if not have_tarball_ver:
                with open(tarball_ver_filepath, "w") as f:
                    f.write(VERSION)

            return _sdist.run(self)
        finally:
            if not have_tarball_ver:
                os.unlink(tarball_ver_filepath)

    def make_distribution(self):
        # Starting from scratch... Huugg... stinky
        self.filelist.exclude_pattern(".*", is_regex=1)
        # Adding tarball version
        self.filelist.append(tarball_ver_filename)
        # Adding paisley
        root_files = call(root_dir, "git", "ls-files").split("\n")
        self.filelist.extend(root_files)
        # Adding paisley
        git_files = call(paisley_dir, "git", "ls-files")
        paisley_files = [os.path.join(paisley_reldir, f)
                         for f in git_files.split("\n")]
        self.filelist.extend(paisley_files)
        # Fix wrong inclusion from setuptools_git
        #self.filelist.exclude_pattern("tools/PKI/.*_ca", is_regex=1)
        self.filelist.exclude_pattern("tools/PKI/openssl.log")
        # Remove git files
        self.filelist.exclude_pattern(".gitignore")
        self.filelist.exclude_pattern(".gitmodules")
        self.filelist.exclude_pattern(".*\.gitignore", is_regex=1)

        _sdist.make_distribution(self)


setup(name = NAME,
      version = VERSION,
      description = DESCRIPTION,
      long_description = LONG_DESC,
      author = 'Flumotion Developers',
      author_email = 'coreteam@flumotion.com',
      url = 'https://github.com/f3at/feat',
      download_url = ('https://github.com/downloads/f3at/feat/%s-%s.tar.gz'
                      % (NAME, VERSION)),
      license = "GPL",
      platforms = ['any'],
      setup_requires = SETUP_REQUIRES,
      install_requires = INSTALL_REQUIRES,
      requires = REQUIRES,
      package_dir = {'': 'src'},
      packages = (['feat']),
      scripts = ['bin/feat',
                 'bin/feat-couchpy',
                 'bin/feat-dbload',
                 'bin/feat-locate',
                 'bin/feat-service'],
      package_data = {'feat': ['agencies/messaging/amqp0-8.xml',
                               'gateway/static/default.css',
                               'gateway/static/feat.css',
                               'gateway/static/default.css'
                               'gateway/static/script/feat.js',
                               'gateway/static/script/form.js',
                               'gateway/static/script/jquery.cseditable.js',
                               'gateway/static/script/json2.js']},
      include_package_data = True,
      keywords = KEYWORDS,
      classifiers = CLASSIFIERS,
      cmdclass = {'sdist': sdist}
)
