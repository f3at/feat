#!/usr/bin/env python

import os
from setuptools import setup, find_packages

setup(name='feat',
      version='0.1.1',
      description='Flumotion Asynchronous Autonomous Agent Toolkit',
      author='Flumotion Developers',
      author_email='coreteam@flumotion.com',
      platforms=['any'],
      package_dir={'': 'src'},
      packages=find_packages(where='src'),
      scripts=['src/feat/bin/host.py',
               'src/feat/bin/standalone.py'],
)
