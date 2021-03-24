import ConfigParser
import os
import subprocess as sp

import asfgit.run as run
import asfgit.util as util


NO_DEFAULT = object()
DEFAULT_SUBJECT = "%(repo)s git commit: %(subject)s"

DEFAULT_PUBSUB_HOST = "gitpubsub.apache.org"
DEFAULT_PUBSUB_PORT = "2069"
DEFAULT_PUBSUB_PATH = "/json"

# When debugging, we need a few values in the environment, in order to
# populate the exported symbols from this module.
DEBUG = False
if DEBUG:
  os.environ['PATH_INFO'] = 'debug'
  os.environ['GIT_PROJECT_ROOT'] = 'debug'
  os.environ['GIT_COMMITTER_NAME'] = 'debug'
  os.environ['GIT_COMMITTER_EMAIL'] = 'debug'
  os.environ['SCRIPT_NAME'] = 'debug'
  os.environ['WEB_HOST'] = 'debug'
  os.environ['WRITE_LOCK'] = 'debug'
  os.environ['AUTH_FILE'] = 'debug'


def _repo_name():
    path = filter(None, os.environ["PATH_INFO"].split("/"))
    path = filter(lambda p: p != "git-receive-pack", path)
    if len(path) != 1:
        raise ValueError("Invalid PATH_INFO: %s" % os.environ["PATH_INFO"])
    path = path[0]
    if path.endswith('.git'):
        return util.decode(path[:-4])
    return util.decode(path)


if os.environ.get('GIT_ORIGIN_REPO'):
  os.chdir(os.environ.get('GIT_ORIGIN_REPO'))
_all_config = dict(c.split('=', 1)
                   for c in run.git('config', '--list')[1].splitlines()
                   if c.strip())
if os.environ.get('GIT_WIKI_REPO'):
  os.chdir(os.environ.get('GIT_WIKI_REPO'))

def _git_config(key, default=NO_DEFAULT):
    if key not in _all_config:
        if default is NO_DEFAULT:
            # When debugging, this is a good default value to return.
            #return '0'
            raise KeyError(key)
        return default
    return _all_config[key]


repo_name = _repo_name()
repo_dir = os.path.join(util.environ("GIT_PROJECT_ROOT"), u"%s.git" % repo_name)
committer = util.environ("GIT_COMMITTER_NAME")
remote_user = util.environ("GIT_COMMITTER_EMAIL")
script_name = util.environ("SCRIPT_NAME")
web_host = util.environ("WEB_HOST")
write_locks = [util.environ("WRITE_LOCK"), os.path.join(repo_dir, "nocommit")]
auth_file = util.environ("AUTH_FILE")
ip = os.environ.get("REMOTE_ADDR", "127.0.0.1")

debug = _git_config("hooks.asfgit.debug") == "true"
protect = _git_config("hooks.asfgit.protect").split()
no_merges = _git_config("hooks.asfgit.no-merges") == "true"
sendmail = _git_config("hooks.asfgit.sendmail").strip()
recips = _git_config("hooks.asfgit.recips").split()
subject_fmt = _git_config("hooks.asfgit.subject-fmt", DEFAULT_SUBJECT)
max_size = int(_git_config("hooks.asfgit.max-size"))
max_emails = int(_git_config("hooks.asfgit.max-emails"))
extra_writers = _git_config("hooks.asfgit.extra-writers", default='')
extra_writers = extra_writers.split(',') if extra_writers != '' else []

# Check if repo is empty
is_empty = False
try:
  is_empty = len(run.git('rev-list', '-n1', '--all')[1].strip()) == 0
except sp.CalledProcessError as e:  # This will break if repo is empty.
  is_empty = True

# Whether master branch exists (used for checking if main is default branch)
has_master_branch = True
try:
  run.git('show-ref', 'refs/heads/master')
except sp.CalledProcessError as e:  # No master branch, exit code 1
  has_master_branch = False

# Fetch default branch, default to master is repo is bare or has no default yet.
default_branch = 'master'
try:
  default_branch = run.git('symbolic-ref', '--short', 'HEAD')[1].strip()
except sp.CalledProcessError as e:  # This can break when repo is empty, beware.
  pass

gitpubsub_host = _git_config("hooks.asfgit.pubsub-host", DEFAULT_PUBSUB_HOST)
gitpubsub_port = _git_config("hooks.asfgit.pubsub-port", DEFAULT_PUBSUB_PORT)
gitpubsub_path = _git_config("hooks.asfgit.pubsub-path", DEFAULT_PUBSUB_PATH)
