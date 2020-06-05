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
"""Simple PagerDuty helper plugin for GomeBot"""
"""
To enable PagerDuty calls, add the following to gnomebot.yaml:

pagerduty:
  apikey:  api-key-goes-here

"""
import pdpyras
import re
import gnomebot

CFG = None
SLACK_WEB_CLIENT = None
PD_MATCH_ONCALL = re.compile(r"(oncall|on-call|on call)", flags=re.IGNORECASE)


def handle_pd_message(event, match):
    chan = event['channel']
    # Fetch PD session, grab on-call
    pdsession = pdpyras.APISession(CFG['pagerduty']['apikey'])
    oncall = pdsession.get('/oncalls').json()
    current_oncall = oncall['oncalls'][-1]['user']['summary']

    # Tell user!
    SLACK_WEB_CLIENT.chat_postMessage(channel=chan, text=f"Hi <@{event['user']}>! Currently, {current_oncall} is on-call.")
    return True  # We got this, don't pass to other plugins!


def load(cfg: dict,  hooks: gnomebot.HookManager, slack_client):
    global SLACK_WEB_CLIENT, CFG
    SLACK_WEB_CLIENT = slack_client
    CFG = cfg
    # Add a hook for when someone mentions gnomebot
    hooks.add_mention_hook(PD_MATCH_ONCALL, handle_pd_message, priority=0)
