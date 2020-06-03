#!/usr/bin/env python3
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""JIRA plugin for GnomeBot"""

"""
Sample YAML configuration in gnomebot.yaml:
jira:
  subscriptions:
    infra_openclose:
      project: INFRA
      events: create close
      channel: '#gnometest'
    infra_detailed:
      project: INFRA
      events: ~  # Handle all events
      channel: '#asfjira'
    jira_all:
      project: ALL  # All JIRA tickets
      events: ~ # All events
      channel: '#spam'
"""

import gnomebot
import asfpy.pubsub
import requests

JIRA_CACHE = {}
SLACK_WEB_CLIENT = None
CFG = None

def jira_details_callback(event, value):
    if value in JIRA_CACHE: # We only handle JIRAs we've seen..
        title, desc = JIRA_CACHE[value]
        return {
            "text": f"<https://issues.apache.org/jira/browse/{value}|{value}>: {title}\n{desc}",
            "replace_original": False,
            "response_type": "ephemeral",
        }
    return {"text": "Could not load details", "replace_original": False, "response_type": "ephemeral", }

def jira_description(event, match):
    key = match.group(1)
    title = None
    desc = None
    if key in JIRA_CACHE:
        title, desc = JIRA_CACHE[key]
    else:
        url = f"https://issues.apache.org/jira/rest/api/latest/issue/{key}"
        try:
            rv = requests.get(url).json()
            title = rv['fields']['summary']
            desc = rv['fields']['description']
            JIRA_CACHE[key] = [title, desc]
        except:
            print("Could not contact JIRA, nothing to do :/")
            return
    if title and desc:
        js = [
                    {
                        "type": "section",
                        "block_id": "title",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"<https://issues.apache.org/jira/browse/{key}|{key}>: {title}"
                        },
                        "accessory":
                            {
                              "type": "button",
                              "text": {
                                "type": "plain_text",
                                "text": "Details"
                              },
                              "value": key,
                              "action_id": "jira_details"
                            }
                    }
                ]
        try:
            chan = event['channel']
            response = SLACK_WEB_CLIENT.chat_postMessage(channel=chan, text=None, blocks=js)
        except Exception as e:
            print(f"Could not post JIRA event message to Slack channel {chan}: {e}")


def jira_parse_event(event):
    if 'stillalive' in event:  # Pingback?
        return
    author = event['author']
    key = event['key']
    title = event['summary']
    js = None
    # New JIRA
    if event['action'] == 'create':
        desc = event.get('description', '')
        if desc and len(desc) > 200:
            desc = desc[:200] + '...'
        js = [
            {
                "pretext": f"*{author}* created <https://issues.apache.org/jira/browse/{key}|{key}>: {title}",
                "title": f"{key}: {title}",
                "text": desc,
                "mrkdwn_in": ["pretext"]
            }
        ]

    if event['action'] == 'close':
        res = event.get('resolution', 'Fixed')
        js = [
            {
                "pretext": f"*{author}* closed <https://issues.apache.org/jira/browse/{key}|{key}> as {res}",
                "title": f"{key}: {title}",
                "text": '',
                "mrkdwn_in": ["pretext"]
            }
        ]

    # Status change
    if event['action'] == 'status':
        fr = event.get('from', 'Unknown')
        to = event.get('to', 'Unknown')
        if to == 'Closed':  # Ignore 'closed' status, that's what the above 'close' catch is for!
            return
        js = [
            {
                "pretext": f"*{author}* changed <https://issues.apache.org/jira/browse/{key}|{key}> from {fr} to {to}.",
                "title": f"{key}: {title}",
                "text": '',
                "mrkdwn_in": ["pretext"]
            }
        ]

    # Assign/unassign
    if event['action'] == 'assign':
        fr = event.get('from')
        to = event.get('to')
        if not to:
            prt = f"*{author}* unassigned <https://issues.apache.org/jira/browse/{key}|{key}>."
        elif not fr:
            prt = f"*{author}* assigned <https://issues.apache.org/jira/browse/{key}|{key}> to *{to}*."
        else:
            prt = f"*{author}* changed assignment of <https://issues.apache.org/jira/browse/{key}|{key}> from *{fr}* to *{to}*."

        js = [
            {
                "pretext": prt,
                "title": f"{key}: {title}",
                "text": '',
                "mrkdwn_in": ["pretext"]
            }
        ]

    # Commented on
    if event['action'] == 'comment':
        comment = event['body']
        js = [
            {
                "pretext": f"*{author}* commented on <https://issues.apache.org/jira/browse/{key}|{key}> - {title}:",
                "title": f"",
                "text": comment,
                "mrkdwn_in": ["pretext"]
            }
        ]
    if js:
        for xkey, sub in CFG['jira']['subscriptions'].items():
            project = key.split('-')[0]
            subproject = sub.get('project')
            chan = sub.get('channel')
            if not chan:
                return
            if not subproject or project == subproject:
                if not sub.get('events') or event['action'] in sub['events'].split(' '):
                    try:
                        response = SLACK_WEB_CLIENT.chat_postMessage(channel=chan, text=None, attachments=js)
                    except Exception as e:
                        print(f"Could not post JIRA event message to Slack channel {chan}: {e}")

def jira_listener(t):
    listener = asfpy.pubsub.Listener('http://pubsub.apache.org:2069/jira')  #TODO: make configurable?
    listener.attach(jira_parse_event, raw=True)


def load(cfg, hooks, swc):
    global SLACK_WEB_CLIENT, CFG
    SLACK_WEB_CLIENT = swc
    CFG = cfg
    # Add a hook to all messages with [A-Z]+-\d+, like INFRA-1234
    hooks.add_message_hook(r"\b([A-Z]+-\d+)\b", jira_description)

    # Interactive hook for when someone expands a jira notice
    hooks.add_action_hook("jira_details", jira_details_callback)

    # PluginThread for listening to pubsub jira events
    jthread = gnomebot.PluginThread(cfg, jira_listener)
    jthread.start()

