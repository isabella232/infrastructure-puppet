#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
This is a retirement script for git repositories on gitbox, git-wip and git.a.o.
When run on git-wip or gitbox, it:
    - Renames the repositories locally
    - Updates git origins
    - Updates mailing list settings
    - Renames the reposiories on GitHub
    - Marks them as archived (read-only)

Usage: attic-repos.py $project, e.g.: attic-repos.py blur
MUST BE RUN AS www-data!
"""
import os
import sys
import re
import requests
import json
import git
import ConfigParser
import pwd

DEBUG = False
REPO_ROOT = "/x1/repos/asf" # Root dir for all repos
CONFIG_FILE = "/x1/gitbox/matt/tools/grouper.cfg" # config file with GH token in it
CONFIG = ConfigParser.ConfigParser()
CONFIG.read(CONFIG_FILE) # Shhhh
TOKEN = CONFIG.get('github', 'token')


def update_github_repo(token, old):
    """
    Renames a repository on GitHub by sending a PATCH request.
    """
    # API URL for archiving
    url = "https://api.github.com/repos/apache/%s" % old

    # Headers - json payload + creds
    headers = {
        'content-type': 'application/json',
    }

    # Construct payload
    payload = json.dumps({
        'archived': True
    })

    # Run the request
    print("  - Changing repository to archived on GitHub...")
    r = requests.patch(url, headers = headers, data = payload, auth = (token, 'x-oauth-basic'))
    if r.status_code == requests.codes.ok:
        print("  - Repository Archived!")
    else:
        print("  - Something went wrong :(")
        print(r.text)
        print("Something did not work here, aborting process!!")
        print("Fix the issue and run the tool again.")
        sys.exit(-1)

def update_local_repo(old, project):
    """
    Renames local repositories:
        - Change PR notification ML
    """
    # ML notification targets for commits and PRs
    print("  - Changing notification options..")
    if gconf.has_option('hooks.asfgit', 'recips'):
        ml = 'commits@attic.apache.org'
        print("    - Changing commit ML to %s" % ml)
        gconf.set('hooks.asfgit', 'recips', ml)
    if gconf.has_section('apache') and gconf.has_option('apache', 'dev'):
        ml = 'dev@attic.apache.org'
        print("    - Changing PR notification ML to %s" % ml)
        gconf.set('apache', 'dev', ml)

    print("  - Done!")

# Demand being run by www-data or git
me = pwd.getpwuid(os.getuid()).pw_name
if me != "www-data" and me != "git":
    print("You must run this as either www-data (on gitbox/git-wip) or git (on git.a.o)!")
    print("You are running as: %s" % me)
    sys.exit(-1)

# Expect one project name passed on, and only one!
if len(sys.argv) == 2:
    PROJECT = sys.argv[1]
    print("Attic'ing %s..." % PROJECT)
    if os.path.isdir(REPO_ROOT):
        pr = 0
        for repo in os.listdir(REPO_ROOT):
            m = re.match(r"^%s(-.+)?(\.git)?$"% PROJECT, repo)
            if m:
                pr += 1
                print("Archiving %s..." % (repo))
                if not DEBUG:
                    update_local_repo(repo, PROJECT)
                    update_github_repo(TOKEN, repo)
        print("All done, processed %u repositories!" % pr)
    else:
        print("%s does not seem to be a directory, aborting!" % REPO_ROOT)
else:
    print("Usage: attic-repos.py $project")
    print("Example: attic-repos.py blur")
