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
"""GnomeBot - a pluggable, relatively simple bot for Slack"""
import os
import flask
import slack
import slackeventsapi
import yaml
import importlib
import re
import threading
import json
import requests
import traceback
import sys

def backtrace():
    """Simple shorthand for printing trace-back for an exception"""
    traceback.print_exception(*sys.exc_info())

class PluginThread(threading.Thread):
    """Simple thread for plugins to make use of, with built-in exception wrapper"""

    def __init__(self, config, func):
        threading.Thread.__init__(self)
        self.config = config
        self.func = func

    def run(self):
        try:
            self.func(self)
        except Exception as e:
            print(f"Thread running {self.func.__name__} errored out, rebooting it: {e}")
            backtrace()
            self.run()


class HookManager:
    """Manager class for hooks of all kinds. Plugins tie into these."""

    def __init__(self):
        self.messageHooks = []
        self.actionHooks = []

    def add_message_hook(self, pattern, callback):
        cname = callback.__name__
        print(f"Registering message hook '{pattern}' for function {cname}...")
        self.messageHooks.append([re.compile(pattern), callback, cname])

    def add_action_hook(self, actionid, callback):
        cname = callback.__name__
        print(f"Registering action hook '{actionid}' for function {cname}...")
        self.actionHooks.append([actionid, callback, cname])


def handle_message(payload):
    """Handle messages from users (not bots) if they match a trigger"""
    if 'event' in payload:
        # Don't wanna respond to bots...
        if 'bot_id' in payload['event']:
            return

        if payload['event'].get('type') == 'message':
            msg = payload['event'].get('text')
            if msg:
                for mhook in hooks.messageHooks:
                    pattern, callback, cname = mhook
                    match = pattern.search(msg)
                    if match:
                        try:
                            callback(payload['event'], match)
                        except Exception as e:
                            print(f"Could not run callback function {cname}: {e}")
                            backtrace()


def handle_event():
    """Native handling of events payloads sent from interactive elements"""
    js = json.loads(flask.request.form["payload"])

    # For each action, see if a plugin can handle this through an action hook
    for action in js.get('actions', []):
        for hook in hooks.actionHooks:
            hook_id, hook_func, hook_name = hook
            if action.get('action_id') == hook_id:
                value = action.get('value')
                try:
                    retval = hook_func(js, value)
                    if retval:
                        assert json.dumps(retval)
                        requests.post(js['response_url'], json=retval)
                except AssertionError as e:
                    print(f"Response from {hook_name} was not serializable JSON!")
                except Exception as e:
                    print(f"Action parsing function {hook_name} errored out: {e}")
                    backtrace()
                break

    resp = flask.Response('{}', mimetype='application/json')
    return resp


if __name__ == "__main__":
    config = yaml.safe_load(open('gnomebot.yaml').read())

    # Initialize a Flask app to host the events adapter
    app = flask.Flask(__name__)
    event_adapter = slackeventsapi.SlackEventAdapter(config['server']['slack_secret'], "/slack/events", app)

    # Message events (slack module knows what to do)
    @event_adapter.on("message")  # HOST:PORT/slack/events
    def deliver(payload):
        return handle_message(payload)

    # Interactive events (slack module does not know how to handle this, so native flask..)
    @app.route("/slack/interactive", methods=["POST"])  # HOST:PORT/slack/interactive
    def deliver():
        return handle_event()


    # Initialize a Web API client
    slack_web_client = slack.WebClient(token=config['server']['slack_token'])

    # Initialize hooks
    hooks = HookManager()

    # Load all plugins in the plugin dir
    pdir = config['server']['plugindir']
    plugin_files = [fpath[:-3] for fpath in os.listdir(pdir) if fpath.endswith('.py')]
    for plugin_file in plugin_files:
        importlib.import_module(f'plugins.{plugin_file}').load(config, hooks, slack_web_client)

    # Spin up the Flask server
    app.run(host=config['server']['host'], port=config['server']['port'])

