#!/usr/local/bin/python

import fnmatch
import io
import os
import re
import subprocess
import sys

import asfpy.messaging
import yaml
import yaml.constructor

# LDAP to CNAME mappings for some projects
WSMAP = {
    "whimsy": "whimsical",
    "empire": "empire-db",
    "webservices": "ws",
    "infrastructure": "infra",
    "comdev": "community",
}

# Hack to get around 'on: foo' being translated to 'True: foo' in pyYaml:
yaml.constructor.SafeConstructor.bool_values["on"] = "on"

# YAML String locator debug dict
ALL_STRINGS = {}

# Allowed GH Actions
ALLOWED_ACTIONS = [
    re.compile(r"^\./.+$"),       # Repo-local action
    re.compile(r"^actions/.*$"),  # GitHub Common Actions
    re.compile(r"^github/.*$"),   # GitHub's own Action collection
    re.compile(r"^apache/.*$"),   # Apache's action collection
    re.compile(r"^[-a-z0-9]+/[-A-Za-z0-9]+@([a-f0-9]{7}|[a-f0-9]{40})$"),  # Any commit-pinned action
]


def capture_string_location(self, node):
    """ Constructor that captures where in the yaml all strings are located, for debug/response purposes """
    if self.name not in ALL_STRINGS:
        ALL_STRINGS[self.name] = []
    ALL_STRINGS[self.name].append((node.value, str(node.start_mark)))
    return self.construct_scalar(node)


# Re-route all strings through our capture function
yaml.constructor.SafeConstructor.add_constructor(u"tag:yaml.org,2002:str", capture_string_location)


def contains(filename, value=None, fnvalue=None):
    """ If a string is contained within a yaml (and is not a comment or key), return where we found it """
    if filename in ALL_STRINGS:
        for el in ALL_STRINGS[filename]:
            if (value and value in el[0]) or (fnvalue and fnmatch.fnmatch(el[0], fnvalue)):
                return el[1].strip()


def get_yaml(filename, refname):
    """ Fetch a yaml file from a specific branch, return its contents to caller as parsed object"""
    try:
        devnull = open(os.devnull, "w")
        fdata = subprocess.check_output(("/usr/bin/git", "show", "%s:%s" % (refname, filename)), stderr=devnull)
    except subprocess.CalledProcessError as e:  # Git show failure, no such file/branch
        fdata = None
    if fdata:
        try:
            stream = io.BytesIO(fdata)
            stream.name = filename
            return yaml.safe_load(stream)
        except yaml.YAMLError as e:
            pass  # If yaml doesn't work, we do not need to scan it :)
    return None


def get_values(yml, tagname):
    """ Returns all matching tag values from the yaml """
    for key, value in yml.iteritems():
        if key == tagname:
            yield value
        elif isinstance(value, dict):
            for subvalue in get_values(value, tagname):
                yield subvalue
        elif isinstance(value, list):
            for subitem in value:
                if isinstance(subitem, dict):
                    for subvalue in get_values(subitem, tagname):
                        yield subvalue


def notify_private(cfg, subject, text):
    """ Notify a project's private list about issues... """
    # infer project name
    m = re.match(r"(?:incubator-)?([^-.]+)", cfg.repo_name)
    pname = m.group(1)
    pname = WSMAP.get(pname, pname)
    #  recps = ["private@%s.apache.org" % pname, "private@infra.apache.org"]
    recps = ["notifications@infra.apache.org"]  # For now, send to projects later.

    # Tell project what happened, on private@
    asfpy.messaging.mail(
        sender="GitBox Security Scan <gitbox@apache.org>",
        recipients=recps,
        subject=subject,
        message=text,
    )


def scan_for_problems(yml, filename):
    """ Scan for all potential security policy issues in the yaml """
    problems = ""

    #  Rule 1: No pull_request_target triggers if secrets are used in the workflow
    if "on" in yml:
        triggers = yml.get("on", [])
        if (isinstance(triggers, list) or isinstance(triggers, dict)) and "pull_request_target" in triggers:
            # No ${{ secrets.GITHUB_TOKEN }} etc in pull_request_target workflows.
            secrets_where = contains(filename, fnvalue="${{ secrets.* }}")
            if secrets_where:
                problems += (
                    "- Workflow can be triggered by forks (pull_request_target) but contains references to secrets %s!\n"
                    % secrets_where
                )
            # No imports via from_secret!
            from_secret = get_values(yml, "from_secret")
            if from_secret:
                secrets_where = contains(filename, value="from_secret")
                problems += (
                    "- Workflow can be triggered by forks (pull_request_target) but contains references to secrets %s!\n"
                    % secrets_where
                )

    # Rule 2: All external refs must be pinned or within whitelisted groups
    for use_ref in get_values(yml, "uses"):
        good = False
        for am in ALLOWED_ACTIONS:
            if am.match(use_ref):
                good = True
        if not good:
            problems += '- "%s" (%s) is not an allowed GitHub Actions reference.\n' % (
                use_ref,
                contains(filename, use_ref),
            )
    return problems


def main():
    import asfgit.cfg as cfg
    import asfgit.git as git

    # For each push
    for ref in git.stream_refs(sys.stdin):
        # For each commit in push
        for commit in ref.commits():
            cfiles = commit.files()
            # For each file in commit
            for filename in cfiles:
                # Is this a GHA file?
                if filename.startswith(".github/workflows/") and (
                    filename.endswith(".yml") or filename.endswith(".yaml")
                ):
                    yml = get_yaml(filename, ref.name)
                    problems = scan_for_problems(yml, filename)
                    if problems:
                        notify_private(
                            cfg,
                            "Security policy warning for GitHub Actions defined in %s.git: %s"
                            % (cfg.repo_name, filename),
                            "The following issues were detected while scanning %s in the %s repository:\n\n"
                            "%s\n\n"
                            "Please see https://s.apache.org/ghactions for our general policies on GitHub Actions.\n"
                            "With regards,\nASF Infrastructure <users@infra.apache.org>."
                            % (filename, cfg.repo_name, problems),
                        )


# Test when being called directly
if __name__ == "__main__":
    my_yaml = yaml.safe_load(open("test.yml"))
    probs = scan_for_problems(my_yaml, "test.yml")
    print(probs)
