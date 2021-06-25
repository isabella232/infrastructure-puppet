#!/usr/bin/env python3
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
""" Staging/live web site pubsubber for ASF git repos """
import asfpy.messaging
import asfpy.pubsub
import uuid
import git
import os
import time
import yaml
import threading
import ezt
import io
import re
import copy
import sys
import requests

# Defaults and settings
PUBSUB_URL = 'http://pubsub.apache.org:2069/github'  # Subscribe to github events only
PUBSUB_QUEUE = {}
ROOT_DIRS = ['/x1/repos/asf', '/x1/repos/private', '/x1/repos/svn']
SCHEME_FILE = 'notifications.yaml'
FALLBACK_ADDRESS = 'team@infra.apache.org'
DEFAULT_TEMPLATE = 'email_template.ezt'
EMAIL_SUBJECTS = {
    'open':         "opened a new %(type)s",
    'close':        "closed %(type)s",
    'merge':        "merged %(type)s",
    'comment':      "commented on %(type)s",
    'created':      "commented on %(type)s",
    'edited':       "edited a comment on %(type)s",
    'deleted':      "removed a comment on %(type)s",
    'diffcomment':  "commented on a change in %(type)s"
}
JIRA_DEFAULT_OPTIONS = 'link label'
JIRA_CREDENTIALS = '/x1/jirauser.txt'
LAST_CALL = int(time.time())

# Globals we figure out as we go along..
DEBUG = bool(sys.argv[1:]) # thus 'python3 gitbox-mailer.py debug' to set debug mode
JIRA_AUTH = tuple(open(JIRA_CREDENTIALS).read().strip().split(':', 1))
JIRA_HEADERS = {
    "Content-type": "application/json",
    "Accept": "*/*",
}
RE_PROJECT = re.compile(r"(?:incubator-)?([^-]+)")
RE_JIRA_TICKET = re.compile(r"\b([A-Z0-9]+-\d+)\b")

TLOCK = threading.Lock()

####################################################
def jira_update_ticket(ticket, txt, worklog=False):
    """ Post JIRA comment or worklog entry """
    where = 'comment'
    data = {
        'body': txt
    }
    if worklog:
        where = 'worklog'
        data = {
            'timeSpent': "10m",
            'comment': txt
        }

    rv = requests.post(
        "https://issues.apache.org/jira/rest/api/latest/issue/%s/%s" % (ticket, where),
        headers=JIRA_HEADERS,
        auth=JIRA_AUTH,
        json=data
    )
    if rv.status_code == 200 or rv.status_code == 201:
        return "Updated JIRA Ticket %s" % ticket
    else:
        raise Exception(rv.text)


def jira_remote_link(ticket, url, prno):
    """ Post JIRA remote link to GitHub PR/Issue """
    urlid = url.split('#')[0] # Crop out anchor
    data = {
        'globalId': "github=%s" % urlid,
        'object':
            {
                'url': urlid,
                'title': "GitHub Pull Request #%s" % prno,
                'icon': {
                    'url16x16': "https://github.com/favicon.ico"
                }
            }
        }
    rv = requests.post(
        "https://issues.apache.org/jira/rest/api/latest/issue/%s/remotelink" % ticket,
        headers=JIRA_HEADERS,
        auth=JIRA_AUTH,
        json=data
        )
    if rv.status_code == 200 or rv.status_code == 201:
        return "Updated JIRA Ticket %s" % ticket
    else:
        raise Exception(rv.text)

def jira_add_label(ticket):
    """ Add a "PR available" label to JIRA """
    data = {
        "update": {
            "labels": [
                {"add": "pull-request-available"}
            ]
        }
    }
    rv = requests.put(
        "https://issues.apache.org/jira/rest/api/latest/issue/%s" % ticket,
        headers=JIRA_HEADERS,
        auth=JIRA_AUTH,
        json=data
    )
    if rv.status_code == 200 or rv.status_code == 201:
        return "Added PR label to Ticket %s\n" % ticket
    else:
        raise Exception(rv.text)


def get_recipient(repo, itype, action):
    """ Finds the right email recipient for a repo and an action. """
    scheme = {}
    m = RE_PROJECT.match(repo)
    if m:
        project = m.group(1)
    else:
        project = 'infra'
    for root_dir in ROOT_DIRS:
        repo_path = os.path.join(root_dir, "%s.git" % repo)
        if os.path.exists(repo_path):
            # Check for notifications.yaml first
            scheme_path = os.path.join(repo_path, SCHEME_FILE)
            if os.path.exists(scheme_path):
                try:
                    scheme = yaml.safe_load(open(scheme_path))
                except:
                    pass

            # Check standard git config
            cfg_path = os.path.join(repo_path, 'config')
            cfg = git.GitConfigParser(cfg_path)
            if not 'commits' in scheme:
                scheme['commits'] = cfg.get("hooks.asfgit", "recips") or FALLBACK_ADDRESS
            if cfg.has_option('apache', 'dev'):
                default_issue = cfg.get("apache", "dev")
                if not 'issues' in scheme:
                    scheme['issues'] = default_issue
                if not 'pullrequests' in scheme:
                    scheme['pullrequests'] = default_issue
            if cfg.has_option('apache', 'jira'):
                default_jira = cfg.get("apache", "jira")
                if not 'jira_options' in scheme:
                    scheme['jira_options'] = default_jira
            break

    if scheme:
        if itype not in ['commit', 'jira']:
            it = 'issues' if itype == 'issue' else 'pullrequests'
            if action in ['comment', 'diffcomment', 'edited', 'deleted', 'created']:
                if ("%s_comment" % it) in scheme:
                    return scheme["%s_comment" % it]
                elif it in scheme:
                    return scheme.get(it, FALLBACK_ADDRESS)
            elif action in ['open', 'close', 'merge']:
                if ("%s_status" % it) in scheme:
                    return scheme["%s_status" % it]
                elif it in scheme:
                    return scheme.get(it, FALLBACK_ADDRESS)
        elif itype == 'commit' and 'commits' in scheme:
            return scheme['commits']
        elif itype == 'jira':
            return scheme.get('jira_options', JIRA_DEFAULT_OPTIONS)
    if itype == 'jira':
        return JIRA_DEFAULT_OPTIONS
    return "dev@%s.apache.org" % project


class Event:
    def __init__(self, key, data):
        self.key = key
        self.payload = data
        self.user = data.get('user')
        self.repo = data.get('repo')
        self.tid = data.get('id')
        self.title = data.get('title')
        self.typeof = data.get('type')
        self.action = data.get('action', 'comment')
        self.link = data.get('link', '')
        self.recipient = get_recipient(self.repo, self.typeof, self.action)
        self.payload['unsubscribe'] = self.recipient.replace('@', '-unsubscribe@')
        self.subject = None
        self.message = None
        self.updated = time.time()
        self.payload['reviews'] = None

        if data.get('filename'):
            self.add(data)

    def add(self, data):
        """ Turn into a stream of comments """
        if not self.payload.get('reviews'):
            self.payload['reviews'] = []
        self.payload['reviews'].append(Helper(data))
        self.updated = time.time()

    def format_message(self, template = DEFAULT_TEMPLATE):
        self.payload['action_text'] = EMAIL_SUBJECTS.get(self.action, EMAIL_SUBJECTS['comment']) % self.payload
        self.subject = "[GitHub] [%(repo)s] %(user)s %(action_text)s #%(id)i: %(title)s" % self.payload
        template = ezt.Template(template, compress_whitespace=0)
        fp = io.StringIO()
        template.generate(fp, self.payload)
        self.message = fp.getvalue()
        if DEBUG:
            print(self.message)
    def notify_jira(self):
        try:
            m = RE_JIRA_TICKET.search(self.title)
            if m:
                jira_ticket = m.group(1)
                jopts = get_recipient(self.repo, 'jira', '')
                if 'worklog' in jopts or 'comment' in jopts:
                    print("[INFO] Adding comment to %s" % jira_ticket)
                    if not DEBUG:
                        jira_update_ticket(jira_ticket, self.message, True if 'worklog' in jopts else False)
                if 'link' in jopts:
                    print("[INFO] Setting JIRA link for %s to %s" % (jira_ticket, self.link))
                    if not DEBUG:
                        jira_remote_link(jira_ticket, self.link, self.tid)
                if 'label' in jopts:
                    print("[INFO] Setting JIRA label for %s" % jira_ticket)
                    if not DEBUG:
                        jira_add_label(jira_ticket)
        except Exception as e:
            print("[WARNING] Could not update JIRA: %s" % e)

    def send_email(self):
        recipient = self.recipient
        print("[INFO] Sending email to %s: %s" % (recipient, self.subject))
        if DEBUG:
            return
        if recipient == 'dev@null':
            return
        is_new_ticket = True if self.action == 'open' else False
        thread_id = "<%s.%s.%s.gitbox@gitbox.apache.org>" % (self.repo, self.tid, self.payload.get('node_id', '--'))
        message_id = thread_id if is_new_ticket else None
        reply_to_id = thread_id if not is_new_ticket else None

        sender = "GitBox <git@apache.org>"
        reply_headers = {
            'References': reply_to_id,
            'In-Reply-To': reply_to_id,
            } if reply_to_id else None
        try:
            asfpy.messaging.mail(
                sender=sender,
                recipient=recipient,
                subject=self.subject,
                message=self.message,
                messageid=message_id,
                headers=reply_headers,
            )
        except Exception as e:
            raise Exception("Could not send email: " + str(e))

    def process(self):
        global LAST_CALL
        no_children = len(self.payload.get('reviews', []) or [])
        print("Processing %s (%u sub-item(s))..." % (self.key, no_children))
        try:
            self.format_message()
            self.send_email()
            self.notify_jira()
        except Exception as e:
            print("Could not dispatch message: " + str(e))
        try:
            LAST_CALL = int(time.time())
            with open("epoch.dat", "w") as f:
                f.write(str(LAST_CALL))
                f.close()
        except:
            pass

class Helper(object):
  def __init__(self, xhash):
    self.__dict__.update(xhash)

class Actor(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)

    def run(self):
        """ Copy queue, clear it and run each item """
        while True:
            QUEUE_COPY = {}
            with TLOCK:
                QUEUE_COPY = PUBSUB_QUEUE.copy()
            for key, event_object in QUEUE_COPY.items():
                now = time.time()
                if now - event_object.updated > 5:
                    try:
                        with TLOCK:
                            del PUBSUB_QUEUE[key]
                    except:
                        print("[ERROR] Could not prune pubsub queue - double free?")
                    try:
                        event_object.process()
                    except Exception as e:
                        print("[WARNING] Could not process payload: %s" % e)
            time.sleep(10)


def process(js):
    """ Plop the item into the queue, or (if stream of comments) append to existing queue item. """
    action = js.get('action', 'null')
    user = js.get('user', 'null')
    type_of = js.get('type', 'null')
    issue_id = js.get('id', 'null')
    repository = js.get('repo', 'null')
    key = "%s-%s-%s-%s-%s" % (action, repository, type_of, issue_id, user)

    # If not a file review, we don't want to fold...
    if 'filename' not in js:
        key += str(uuid.uuid4())
    with TLOCK:
        if key not in PUBSUB_QUEUE:
            PUBSUB_QUEUE[key] = Event(key, js)
        else:
            PUBSUB_QUEUE[key].add(js)

if __name__ == '__main__':
    if DEBUG:
        print("[INFO] Debug mode enabled, no emails will be sent!")
    try:
        LAST_CALL = int(open("epoch.dat").read())
    except:
        pass
    mail_actor = Actor()
    mail_actor.start()
    pubsub = asfpy.pubsub.Listener(PUBSUB_URL)
    pubsub.attach(process, since = LAST_CALL)
