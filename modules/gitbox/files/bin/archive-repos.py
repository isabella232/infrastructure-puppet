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
import configparser
import pwd
import argparse

REPO_ROOT = "/x1/repos/asf"  # Root dir for all repos
CONFIG_FILE = "/x1/gitbox/matt/tools/grouper.cfg"  # config file with GH token in it

CONFIG = configparser.ConfigParser()
CONFIG.read(CONFIG_FILE) # Shhhh
TOKEN = CONFIG.get('github', 'token')


def fetch_args():
    parser = argparse.ArgumentParser(
        description="Apache repository archival tool",
        epilog="Specify either a project or a file, but not both",
    )
    parser.add_argument(
        "-p", "--project", help="Project for which all repositories are to be archived"
    )
    parser.add_argument(
        "-f", "--file", help="File containing a list of repositories to be archived"
    )
    parser.add_argument("-d", "--debug", action="store_true", help="debug switch")
    args = parser.parse_args()
    return args


def archive_github_repo(token, old):
    """
    Renames a repository on GitHub by sending a PATCH request.
    """
    # Cut away the .git ending if it's there
    old = old.replace(".git", "")

    # API URL for patching the name
    url = "https://api.github.com/repos/apache/%s" % old

    # Headers - json payload + creds
    headers = {"content-type": "application/json"}

    # Construct payload
    payload = json.dumps({"archived": True})

    # Run the request
    print("  - Archiving %s on GitHub..." % old)
    r = requests.patch(
        url, headers=headers, data=payload, auth=(token, "x-oauth-basic")
    )
    if r.status_code == requests.codes.ok:
        print("  - Repository archived!")
    else:
        print("  - Something went wrong :(")
        print(r.text)
        print("Something did not work here, aborting process!!")
        print("Fix the issue and run the tool again.")
        sys.exit(-1)


def archive_local_repo(old, new, project):
    """
    Renames local repositories:
        - Rename the git dir
        - Change remote origin (svn or git)
        - Change commit notification ML
        - Change PR notification ML
    """
    with open("%s/%s/nocommit" % (REPO_ROOT, old), "w") as f:
        f.write("nocommit")
        f.close()


def archive_project(args):
    print("Retiring %s..." % args.project)
    pr = 0
    for repo in os.listdir(REPO_ROOT):
        m = re.match(r"^(%s(-.+)?)(\.git)?$" % args.project, repo)
        if m:
            pr += 1
            print("Archiving %s..." % repo)
            if not args.debug:
                archive_local_repo(repo, args.project)
                archive_github_repo(TOKEN, repo)
            else:
                print("Debug enabled: skipping local archival")
                print("Debug enabled: skipping remote archival")
    print("All done, processed %u repositories!" % pr)


def archive_list(args):
    try:
        repos_to_retire = open(args.file, "r")
    except FileNotFoundError as e:
        print("%s doesn't exist" % args.file)
        sys.exit(2)

    ar = 0
    for repo in repos_to_retire:
        print("Archiving %s..." % repo.strip("\n"))
        if not args.debug:
            archive_local_repo(repo, args.project)
            archive_github_repo(TOKEN, repo)
        else:
            print("Debug enabled: skipping local archival")
            print("Debug enabled: skipping remote archival")
        ar += 1


def main():
    args = fetch_args()
    # Demand being run by www-data or git
    me = pwd.getpwuid(os.getuid()).pw_name
    if me != "www-data" and me != "git":
        print(
            "You must run this as either www-data (on gitbox/git-wip) or git (on git.a.o)!"
        )
        print("You are running as: %s" % me)
        sys.exit(-1)

    # Ensure we don't have a listfile and a project
    if args.project and args.file:
        print("Specify either a file or a project, but not both")
        sys.exit(1)

    if os.path.isdir(REPO_ROOT):
        if args.project:
            archive_project(args)
        elif args.file:
            archive_list(args)
        else:
            print("No action provided, run with '-h' to see usage")
    else:
        print("%s does not seem to be a directory, aborting!" % REPO_ROOT)


if __name__ == "__main__":
    main()
