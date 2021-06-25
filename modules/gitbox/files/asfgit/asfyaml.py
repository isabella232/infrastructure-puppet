import requests
import json
import asfgit.log
import asfgit.git
import asfgit.cfg
import re
import github as pygithub
import os
import yaml
import asfpy.messaging
import io
import fnmatch

# LDAP to CNAME mappings for some projects
WSMAP = {
    'whimsy': 'whimsical',
    'empire': 'empire-db',
    'webservices': 'ws',
    'infrastructure': 'infra',
    'comdev': 'community',
}

# Repositories that override hostname for publishing
WS_HOSTNAME_OVERRIDES = {
    "comdev-events-site": "events.apache.org",
}

# Notification scheme setup
NOTIFICATION_SETTINGS_FILE = 'notifications.yaml'
VALID_LISTS_FILE = '/x1/gitbox/mailinglists.json'
VALID_NOTIFICATION_SCHEMES = [
        'commits',
        'issues',
        'pullrequests',
        'issues_status',
        'issues_comment',
        'pullrequests_status',
        'pullrequests_comment',
        'jira_options'
]
# regex for valid ASF mailing list
RE_VALID_MAILINGLIST = re.compile(r"[-a-z0-9]+@([-a-z0-9]+)?(\.incubator)?\.?apache\.org$")

# Collaborators file for GitHub triage role
COLLABORATOR_FILE = "github_collaborators.txt"
MAX_COLLABORATORS = 20  # We don't want more than 20 external collaborators

def jenkins(cfg, yml):
    
    # GitHub PR Builder Whitelist for known (safe) contributors
    ref = yml.get('refname', 'master').replace('refs/heads/', '')
    if ref == 'master' or ref == 'trunk':
        ghprb_whitelist = yml.get('github_whitelist')
        if ghprb_whitelist and type(ghprb_whitelist) is list:
            if len(ghprb_whitelist) > 10:
                raise Exception("GitHub whitelist cannot be more than 10 people!")
            ghwl = "\n".join(ghprb_whitelist)
            print("Updating GHPRB whitelist for GitHub...")
            with open("/x1/gitbox/conf/ghprb-whitelist/%s.txt" % cfg.repo_name, "w") as f:
                f.write(ghwl)
                f.close()
            print("Whitelist updated!")

def custombuild(cfg, yml):
    """ Custom Command Builder """

    # Don't build from asf-site, like...ever
    ref = yml.get('refname', 'master').replace('refs/heads/', '')
    if ref == 'asf-site':
        print("Not auto-building from asf-site, ever...")
        return

    # If whoami specified, ignore this payload if branch does not match
    whoami = yml.get('whoami')
    if whoami and whoami != ref:
        return

    # Get target branch, if any, default to same branch
    target = yml.get('target', ref)

    # get the directory the build script will output it's generated content to.
    outputdir = yml.get('outputdir', None)

    # Get commands
    buildscript = yml.get('buildscript', None)
    if buildscript is None:
        print("No buildscript specified")
        return

    # infer project name
    m = re.match(r"(?:incubator-)?([^-.]+)", cfg.repo_name)
    pname = m.group(1)
    pname = WSMAP.get(pname, pname)

    # Get notification list
    pnotify = yml.get('notify', cfg.recips[0])
    # Exclude default table of contents
    no_toc = yml.get('notoc', False)
    # Contact buildbot 2
    bbusr, bbpwd = open("/x1/gitbox/auth/bb2.txt").read().strip().split(':', 1)
    import requests
    s = requests.Session()
    s.get("https://ci2.apache.org/auth/login", auth= (bbusr, bbpwd))

    if type(buildscript) is not str:
        raise ValueError("Buildscript invocation is not a string")
    else:
            payload = {
                "method": "force",
                "jsonrpc": "2.0",
                "id":0,
                "params":{
                    "reason": "Triggered custom builder via .asf.yaml by %s" % cfg.committer,
                    "builderid": "8",
                    "source": "https://gitbox.apache.org/repos/asf/%s.git" % cfg.repo_name,
                    "sourcebranch": ref,
                    "outputbranch": target,
                    "project": pname,
                    "buildscript": buildscript,
                    "outputdir": outputdir,
                    "notify": pnotify,
                    "notoc": no_toc
                }
            }
    print("Triggering custom build...")
    s.post('https://ci2.apache.org/api/v2/forceschedulers/custombuild_websites', json = payload)
    print("Done!")

def jekyll(cfg, yml):
    """ Jekyll auto-build """
    
    # Don't build from asf-site, like...ever
    ref = yml.get('refname', 'master').replace('refs/heads/', '')
    if ref == 'asf-site':
        print("Not auto-building from asf-site, ever...")
        return
    
    # If whoami specified, ignore this payload if branch does not match
    whoami = yml.get('whoami')
    if whoami and whoami != ref:
        return
    
    # Get target branch, if any, default to same branch
    target = yml.get('target', ref)
    
    # Get optional theme
    theme = yml.get('theme', 'theme')

    # Get optional outputdirectory name, Default 'output'
    outputdir = yml.get('outputdir', 'output')
    
    # infer project name
    m = re.match(r"(?:incubator-)?([^-.]+)", cfg.repo_name)
    pname = m.group(1)
    pname = WSMAP.get(pname, pname)
    
    # Get notification list
    pnotify = yml.get('notify', cfg.recips[0])
    
    # Contact buildbot 2
    bbusr, bbpwd = open("/x1/gitbox/auth/bb2.txt").read().strip().split(':', 1)
    import requests
    s = requests.Session()
    s.get("https://ci2.apache.org/auth/login", auth= (bbusr, bbpwd))
    
    payload = {
        "method": "force",
        "jsonrpc": "2.0",
        "id":0,
        "params":{
            "reason": "Triggered jekyll auto-build via .asf.yaml by %s" % cfg.committer,
            "builderid": "7",
            "source": "https://gitbox.apache.org/repos/asf/%s.git" % cfg.repo_name,
            "sourcebranch": ref,
            "outputbranch": target,
            "outputdir": outputdir,
            "project": pname,
            "theme": theme,
            "notify": pnotify,
        }
    }
    print("Triggering jekyll build...")
    s.post('https://ci2.apache.org/api/v2/forceschedulers/jekyll_websites', json = payload)
    print("Done!")

def pelican(cfg, yml):
    """ Pelican auto-build """
    
    # Don't build from asf-site, like...ever
    ref = yml.get('refname', 'master').replace('refs/heads/', '')
    if ref == 'asf-site':
        print("Not auto-building from asf-site, ever...")
        return
    
    # If whoami specified, ignore this payload if branch does not match
    # Unless autobuilding matches...
    whoami = yml.get('whoami')
    autobuild = yml.get('autobuild')
    if autobuild:
        assert isinstance(autobuild, str), "autobuild parameter must be a string!"
        assert autobuild.endswith('/*'), "autobuild parameter must be $foo/*, e.g. site/* or feature/*"
    do_autobuild = autobuild and fnmatch.fnmatch(ref, autobuild) and not ref.endswith('-staging')  # don't autobuild the autobuilt
    if whoami and whoami != ref and not do_autobuild:
        return
    
    # Get target branch, if any, default to same branch or $branch-staging for autobuilds
    target = yml.get('target', ref)
    if do_autobuild:
        ref_bare = ref.replace(autobuild[:-1], '', 1) # site/foo -> foo
        target = "%s/%s-staging" % ( autobuild[:-2], ref_bare)  # site/foo -> site/foo-staging
    
    # Get optional theme
    theme = yml.get('theme', 'theme')
    
    # infer project name
    m = re.match(r"(?:incubator-)?([^-.]+)", cfg.repo_name)
    pname = m.group(1)
    pname = WSMAP.get(pname, pname)
    
    # Get notification list
    pnotify = yml.get('notify', cfg.recips[0])

    # Get TOC boolean
    toc = yml.get('toc', True)
    
    # Get minimum page count
    minpages = yml.get('minimum_page_count', 0)
    assert isinstance(minpages, int) and minpages >= 0, "minimum_page_count needs to be a positve integer!"

    # Contact buildbot 2
    bbusr, bbpwd = open("/x1/gitbox/auth/bb2.txt").read().strip().split(':', 1)
    import requests
    s = requests.Session()
    s.get("https://ci2.apache.org/auth/login", auth= (bbusr, bbpwd))
    
    payload = {
        "method": "force",
        "jsonrpc": "2.0",
        "id":0,
        "params":{
            "reason": "Triggered pelican auto-build via .asf.yaml by %s" % cfg.committer,
            "builderid": "3",
            "source": "https://gitbox.apache.org/repos/asf/%s.git" % cfg.repo_name,
            "sourcebranch": ref,
            "outputbranch": target,
            "project": pname,
            "theme": theme,
            "notify": pnotify,
            "toc": toc,
            "minimum_page_count": "%u" % minpages,
        }
    }
    print("Triggering pelican build...")
    s.post('https://ci2.apache.org/api/v2/forceschedulers/pelican_websites', json = payload)
    print("Done!")

GH_BRANCH_PROTECTION_URL_TPL = 'https://api.github.com/repos/apache/%s/branches/%s/protection'
GH_BRANCH_PROTECTION_URL_ACCEPT = 'application/vnd.github.luke-cage-preview+json'

def getEnabledProtectedBranchList (GH_TOKEN, repo_name, url, isLast):
    if url:
        REQ_URL = url
    else:
        REQ_URL = 'https://api.github.com/repos/apache/%s/branches?protected=true' % repo_name
    headers = { "Authorization": "token %s" % GH_TOKEN }
    response = requests.get(REQ_URL, headers=headers)

    branchCollection = []
    for branch in response.json():
        branchCollection.append(branch.get("name"))

    if response.links and response.links.get("next") and not isLast:
        isLast = response.links["next"]["url"] == response.links["last"]["url"]
        branchCollection = branchCollection + getEnabledProtectedBranchList(GH_TOKEN, repo_name, response.links["next"]["url"], isLast)

    return branchCollection

def setProtectedBranch (GH_TOKEN, cfg, branch, required_status_checks, required_pull_request_reviews, required_linear_history):
    REQ_URL = GH_BRANCH_PROTECTION_URL_TPL % (cfg.repo_name, branch)
    response = requests.put(REQ_URL, headers = {'Accept': GH_BRANCH_PROTECTION_URL_ACCEPT, "Authorization": "token %s" % GH_TOKEN}, json = {
        'enforce_admins': None,
        'restrictions': None,
        'required_status_checks': required_status_checks,
        'required_pull_request_reviews': required_pull_request_reviews,
        'required_linear_history': required_linear_history,
    })

    if not (200 <= response.status_code < 300):
        js = response.json()
        raise Exception(
            "[GitHub] Request error with message: \"%s\". (status code: %s)" % (
                js.get("message"),
                response.status_code
            )
        )

    title = "Protected Branches"
    message = "GitHub Protected Branches has been enabled on branch=%s" % (branch)
    print(message)
    notifiyPrivateMailingList(cfg, title, message)

    return response

def removeProtectedBranch (GH_TOKEN, cfg, branch):
    REQ_URL = GH_BRANCH_PROTECTION_URL_TPL % (cfg.repo_name, branch)
    headers = {"Authorization": "token %s" % GH_TOKEN}
    response = requests.delete(REQ_URL, headers=headers)

    if not (200 <= response.status_code < 300):
        js = response.json()
        raise Exception(
            "[GitHub] Request error with message: \"%s\". (status code: %s)" % (
                js.get("message"),
                response.status_code
            )
        )

    title = "Protected Branches"
    message = "GitHub Protected Branches has been be removed from branch=%s" % (branch)
    print(message)
    notifiyPrivateMailingList(cfg, title, message)

    return response

def setProtectedBranchRequiredSignature (GH_TOKEN, cfg, pb_branch, required_signatures):
    REQ_URL = 'https://api.github.com/repos/apache/%s/branches/%s/protection/required_signatures' % (cfg.repo_name, pb_branch)
    ACCEPT_HEADER = 'application/vnd.github.zzzax-preview+json'
    
    if type(required_signatures) is not bool:
        required_signatures = False
        print('The GitHub protected branch setting "required_signatures" contains an invalid value. It will be set to "False"')

    if required_signatures:
        response = requests.post(REQ_URL, headers = {'Accept': ACCEPT_HEADER, "Authorization": "token %s" % GH_TOKEN})
    else:
        response = requests.delete(REQ_URL, headers = {'Accept': ACCEPT_HEADER, "Authorization": "token %s" % GH_TOKEN})

    if not (200 <= response.status_code < 300):
        js = response.json()
        raise Exception(
            "[GitHub] Request error with message: \"%s\". (status code: %s)" % (
                js.get("message"),
                response.status_code
            )
        )

    title = "Protected Branches"
    message = "GitHub Protected Branches has set requires signature setting on branch '%s' to '%s'" % (pb_branch, required_signatures)
    print(message)
    notifiyPrivateMailingList(cfg, title, message)

    return response

def formatProtectedBranchRequiredStatusChecks(required_status_checks):
    if type(required_status_checks) is dict:
        # Update the "required_status_checks" data to ensure it has correct allowed data.
        required_status_checks = {
            # We are expecting a boolean value
            'strict': required_status_checks.get('strict', False),

            # WIP: Contexts
            'contexts': required_status_checks.get('contexts', [])
        }
    elif required_status_checks is not None:
        # If "required_status_checks" was not None but also it is not an object, we will force set it to None.
        required_status_checks = None

    return required_status_checks

def formatProtectedBranchRequiredPullRequestReview(required_pull_request_reviews):
    # Update the "required_pull_request_reviews" to ensure it has correct allowed data.
    if type(required_pull_request_reviews) is dict:
        reviewRequiredCount = required_pull_request_reviews.get('required_approving_review_count', 1)

        if reviewRequiredCount > 6:
            reviewRequiredCount = 6
            print('The maximum allowed review count can not be greater than 6. The review count has been changed to 6.')
        elif reviewRequiredCount < 1:
            reviewRequiredCount = 1
            print('The minimum allowed review count can not be less than 1. The review count has been changed to 1.')

        required_pull_request_reviews = {
            'dismiss_stale_reviews': required_pull_request_reviews.get('dismiss_stale_reviews', False),
            'require_code_owner_reviews': required_pull_request_reviews.get('require_code_owner_reviews', False),
            'required_approving_review_count': reviewRequiredCount
        }
    elif required_pull_request_reviews is not None:
        # If "required_pull_request_reviews" was not None but also it is not an object, we will force set it to None.
        required_pull_request_reviews = None

    return required_pull_request_reviews

def notifiyPrivateMailingList(cfg, title, body):
    # infer project name
    m = re.match(r"(?:incubator-)?([^-.]+)", cfg.repo_name)
    pname = m.group(1)
    pname = WSMAP.get(pname, pname)

    # Tell project what happened, on private@
    message = "The following changes were applied to %s by %s.\n\n%s\n\nWith regards,\nASF Infra.\n" % (cfg.repo_name, cfg.committer, body)
    subject = "%s for %s.git has been updated" % (title, cfg.repo_name)
    asfpy.messaging.mail(
        sender='GitBox <gitbox@apache.org>',
        recipients=['private@%s.apache.org' % pname],
        subject=subject,
        message=message)

def github(cfg, yml):
    """ GitHub settings updated. Can set up description, web site and topics """
    # Test if we need to process this
    ref = yml.get('refname', 'master').replace('refs/heads/', '')
    if ref != 'master' and ref != asfgit.cfg.default_branch:
        print("Saw GitHub meta-data in .asf.yaml, but not master or default branch, not updating...")
        return
    # Check if cached yaml exists, compare if changed
    ymlfile = '/tmp/ghsettings.%s.yml' % cfg.repo_name
    try:
        if os.path.exists(ymlfile):
            oldyml = yaml.safe_load(open(ymlfile).read())
            if cmp(oldyml, yml) == 0:
                return
    except yaml.YAMLError as e: # Failed to parse old yaml? bah.
        pass
    
    # Update items
    print("GitHub meta-data changed, updating...")
    GH_TOKEN = open('/x1/gitbox/matt/tools/asfyaml.txt').read().strip()
    GH = pygithub.Github(GH_TOKEN)
    repo = GH.get_repo('apache/%s' % cfg.repo_name)
    # If repo is on github, update accordingly
    if repo:
        desc = yml.get('description')
        homepage = yml.get('homepage')
        merges = yml.get('enabled_merge_buttons')
        features = yml.get('features')
        topics = yml.get('labels')
        ghp_branch = yml.get('ghp_branch')
        ghp_path = yml.get('ghp_path', '/docs')
        autolink = yml.get('autolink') # TBD: https://help.github.com/en/github/administering-a-repository/configuring-autolinks-to-reference-external-resources
        protected_branches = yml.get('protected_branches')
        collabs = yml.get('collaborators')

        if desc:
            repo.edit(description=desc)
            # Update on gitbox as well
            desc_path = os.path.join(cfg.repo_dir, "description")
            if isinstance(desc, str):
                desc = unicode(desc, "utf-8")
            with io.open(desc_path, "w", encoding="utf8") as f:
                f.write(desc)
        if homepage:
            repo.edit(homepage=homepage)
        if merges:
            repo.edit(allow_squash_merge=merges.get("squash", False),
                allow_merge_commit=merges.get("merge", False),
                allow_rebase_merge=merges.get("rebase", False))
        if features:
            repo.edit(has_issues=features.get("issues", False),
                has_wiki=features.get("wiki", False),
                has_projects=features.get("projects", False))
        if topics and type(topics) is list:
            for topic in topics:
                if not re.match(r"^[-a-z0-9]{1,35}$", topic):
                    raise Exception(".asf.yaml: Invalid GitHub label '%s' - must be lowercase alphanumerical and <= 35 characters!" % topic)
            repo.replace_topics(topics)
        print("GitHub repository meta-data updated!")

        # Fetches a collection of enabled protected branches.
        # Branches will be removed from this collection if they exist in the ".asf.yaml" file with settings.
        # Removing branches from this collection does not refer to removing protection settings.
        # The reaming items are considered as old and invalid branches that have protection currently enabled.
        # These branches will be stripped of its protection settings at the end.
        enabledProtectedBranches = getEnabledProtectedBranchList(GH_TOKEN, cfg.repo_name, False, False)

        if isinstance(protected_branches, dict) and all(isinstance(x, basestring) for x in protected_branches):
            # For each defined branch, fetch and format the user-defined settings and submit GH API.
            for pb_branch in protected_branches:
                pb_branch_data = protected_branches.get(pb_branch)

                # If a user-defined a branch with no settings provided, this branch will be skipped.
                # Additionally, no settings mean no protection. If the branch used to have protection enabled, it will be removed.
                if type(pb_branch_data) is not dict:
                    print('There is no protected branch data to set for the branch: %s' % pb_branch)
                    continue

                # Here is where we remove the item from the known enabledProtectedBranches collection.
                # This will ensure that this branch's with defined settings are not removed.
                try:
                    enabledProtectedBranches.remove(pb_branch)
                except:
                    print('Branch "%s" is not in the exisiting branch collection. No action is required.' % (pb_branch))

                # Get user settings and format for sending
                required_status_checks = formatProtectedBranchRequiredStatusChecks(
                    pb_branch_data.get("required_status_checks", None)
                )

                required_pull_request_reviews = formatProtectedBranchRequiredPullRequestReview(
                    pb_branch_data.get("required_pull_request_reviews", None)
                )

                required_signatures = pb_branch_data.get("required_signatures", False)
                required_linear_history = pb_branch_data.get("required_linear_history", False)

                # GH API Calls to add/update
                setProtectedBranch(
                    GH_TOKEN,
                    cfg,
                    pb_branch,
                    required_status_checks,
                    required_pull_request_reviews,
                    required_linear_history
                )

                setProtectedBranchRequiredSignature(
                    GH_TOKEN,
                    cfg,
                    pb_branch,
                    required_signatures
                )

        # Here is where the remaining branches as considered invalid/old branches with protection and will be removed.
        # This requires that protected_branches is set to none (~), see INFRA-21073 for why.
        # The cleanup process
        if 'protected_branches' in yml:
            for branch_to_disable_protection in enabledProtectedBranches:
                removeProtectedBranch(GH_TOKEN, cfg, branch_to_disable_protection)

        # GitHub Pages?
        if ghp_branch:
            GHP_URL = 'https://api.github.com/repos/apache/%s/pages' % cfg.repo_name
            # Test if GHP is enabled already
            rv = requests.get(GHP_URL, headers = {"Authorization": "token %s" % GH_TOKEN, 'Accept': 'application/vnd.github.switcheroo-preview+json'})
            
            # Not enabled yet, enable?!
            if rv.status_code == 404:
                try:
                    rv = requests.post(
                        GHP_URL,
                        headers = {"Authorization": "token %s" % GH_TOKEN, 'Accept': 'application/vnd.github.switcheroo-preview+json'},
                        json = {
                            'source': {
                                'branch': ghp_branch,
                                'path': ghp_path
                            }
                        }
                    )
                    print("GitHub Pages set to branch=%s, path=%s" % (ghp_branch, ghp_path))
                except:
                    print("Could not set GitHub Pages configuration!")
            # Enabled, update settings?
            elif 200 <= rv.status_code < 300:
                ghps = '%s /docs' % cfg.default_branch
                if ghp_branch in ['main', 'master', 'gh-pages', cfg.default_branch]:
                    if ghp_path == '/docs':
                        ghps = ghp_branch + ' /docs'
                    else:
                        ghps = ghp_branch
                else:
                    print("Could not set GitHub Pages: Branch must be gh-pages or default branch!")
                    return
                try:
                    rv = requests.put(
                        GHP_URL,
                        headers = {'Accept': 'application/vnd.github.switcheroo-preview+json'},
                        json = {
                            'source': ghps,
                        }
                    )
                    print("GitHub Pages updated to %s" % ghps)
                except:
                    print("Could not set GitHub Pages configuration!")

        # Collaborator list edits?
        if collabs:
            assert isinstance(collabs, list), "Collaborators data must be a list of GitHub user IDs."
            collaborators(collabs, cfg, GH_TOKEN)

        # Save cached version for late checks
        with open(ymlfile, "w") as f:
            f.write(yaml.dump(yml, default_flow_style=False))

def staging(cfg, yml):
    """ Staging for websites. Sample entry .asf.yaml entry:
      staging:
        profile: gnomes
        # would stage current branch at https://$project-gnomes.staged.apache.org/
        # omit profile to stage at $project.staged.a.o
    """
    # infer project name
    m = re.match(r"(?:incubator-)?([^-.]+)", cfg.repo_name)
    pname = m.group(1)
    pname = WSMAP.get(pname, pname)
    
    # Get branch
    ref = yml.get('refname', 'master').replace('refs/heads/', '')
    
    # If whoami specified, ignore this payload if branch does not match
    # Unless autostage is enabled here
    autostage = yml.get('autostage')
    if autostage:
        assert isinstance(autostage, str), "autostage parameter must be a string!"
        assert autostage.endswith('/*'), "autostage parameter must be $foo/*, e.g. site/* or feature/*"
    do_autostage = autostage and fnmatch.fnmatch(ref, autostage) and ref.endswith('-staging')  # site/foo-staging, matching site/*
    whoami = yml.get('whoami')
    if whoami and whoami != ref and not do_autostage:
        return
    
    subdir = yml.get('subdir', '')
    if subdir:
        if not re.match(r"^[-_a-zA-Z0-9/]+$", subdir):
            raise Exception(".asf.yaml: Invalid subdir '%s' - Should be [-_A-Za-z0-9/]+ only!" % subdir)
    
    # Get profile from .asf.yaml, if present, or autostage derivation
    profile = yml.get('profile', '')
    if do_autostage:
        profile = ref.replace(autostage[:-1], '', 1)[:-8] # site/foo-staging -> foo -> $project-foo.staged.a.o
    
    # Try sending staging payload to pubsub
    try:
        payload = {
            'staging': {
                'project': pname,
                'subdir': subdir,
                'source': "https://gitbox.apache.org/repos/asf/%s.git" % cfg.repo_name,
                'branch': ref,
                'profile': profile,
                'pusher': cfg.committer,
            }
        }

        # Send to pubsub.a.o
        requests.post("http://pubsub.apache.org:2069/staging/%s" % pname,
                      data = json.dumps(payload))
        
        wsname = pname
        if profile:
            wsname += '-%s' % profile
        print("Staging contents at https://%s.staged.apache.org/ ..." % wsname)
    except Exception as e:
        print(e)
        asfgit.log.exception()

def publish(cfg, yml):
    """ Publishing for websites. Sample entry .asf.yaml entry:
      publish:
        whoami: asf-site
        # would publish current branch (if asf-site) at https://$project.apache.org/
    """
    # infer project name
    m = re.match(r"(?:incubator-)?([^-.]+)", cfg.repo_name)
    pname = m.group(1)
    pname = WSMAP.get(pname, pname)
    
    # Get branch
    ref = yml.get('refname', 'master').replace('refs/heads/', '')
    
    # Get optional target domain:
    target = yml.get('hostname', '')
    if 'apache.org' in target:
        if WS_HOSTNAME_OVERRIDES.get(cfg.repo_name, '') != target:
            raise Exception(".asf.yaml: Invalid hostname '%s' - you cannot specify *.apache.org hostnames, they must be inferred!" % target)
    
    # If whoami specified, ignore this payload if branch does not match
    whoami = yml.get('whoami')
    if whoami and whoami != ref:
        return
    
    subdir = yml.get('subdir', '')
    if subdir:
        if not re.match(r"^[-_a-zA-Z0-9/]+$", subdir):
            raise Exception(".asf.yaml: Invalid subdir '%s' - Should be [-_A-Za-z0-9/]+ only!" % subdir)
    
    # Try sending publish payload to pubsub
    try:
        payload = {
            'publish': {
                'project': pname,
                'subdir': subdir,
                'source': "https://gitbox.apache.org/repos/asf/%s.git" % cfg.repo_name,
                'branch': ref,
                'pusher': cfg.committer,
                'target': target,
            }
        }

        # Send to pubsub.a.o
        requests.post("http://pubsub.apache.org:2069/publish/%s" % pname,
                      data = json.dumps(payload))
        
        print("Publishing contents at https://%s.apache.org/ ..." % pname)
    except Exception as e:
        print(e)
        asfgit.log.exception()


def notifications(cfg, yml):
    """ Notification scheme setup """

    # Get branch
    ref = yml.get('refname', 'master').replace('refs/heads/', '')

    # Ensure this is master, trunk or repo's default branch - otherwise bail
    if ref != 'master' and ref != 'trunk' and ref != asfgit.cfg.default_branch:
        print("[NOTICE] Notification scheme settings can only be applied to the master/trunk or default branch.")
        return

    # Grab list of valid mailing lists
    valid_lists = json.loads(open(VALID_LISTS_FILE).read())
    
    # infer project name
    m = re.match(r"(?:incubator-)?([^-.]+)", cfg.repo_name)
    pname = m.group(1)
    pname = WSMAP.get(pname, pname)

    # Verify that we know all settings in the yaml
    if not isinstance(yml, dict):
        raise Exception("Notification schemes must be simple 'key: value' pairs!")
    del yml['refname'] # Don't need this
    for k, v in yml.items():
        if not isinstance(v, str):
            raise Exception("Invalid value for setting '%s' - must be string value!" % k)
        if k not in VALID_NOTIFICATION_SCHEMES:
            raise Exception("Invalid notification scheme '%s' detected, please remove it!" % k)
        # Verify that all set schemes pass muster and point to $foo@$project.a.o
        if k != 'jira_options':
            if not RE_VALID_MAILINGLIST.match(v)\
                or not (
                    v.endswith('@apache.org') or
                    v.endswith('@%s.apache.org' % pname) or
                    v.endswith('@%s.incubator.apache.org' % pname)
                ) or v not in valid_lists:
                raise Exception("Invalid notification target '%s'. Must be a valid @%s.apache.org list!" % (v, pname))

    # All seems kosher, update settings if need be
    scheme_path = os.path.join(cfg.repo_dir, NOTIFICATION_SETTINGS_FILE)
    old_yml = {}
    if os.path.exists(scheme_path):
        old_yml = yaml.safe_load(open(scheme_path).read())

    # If old and new are identical, do nothing...
    if old_yml == yml:
        return

    print("Updating notification schemes for repository: ")
    changes = ""
    # Figure out what changed since last
    for key in VALID_NOTIFICATION_SCHEMES:
        if key not in old_yml and key in yml:
            changes += "- adding new scheme (%s): %s\n" % (key, yml[key])
        elif key in old_yml and key not in yml:
            changes += "- removing old scheme (%s) - was %s\n" % (key, old_yml[key])
        elif key in old_yml and key in yml and old_yml[key] != yml[key]:
            changes += "- updating scheme %s: %s -> %s" % (key, old_yml[key], yml[key])
    print(changes)
    
    with open(scheme_path, 'w') as fp:
        yaml.dump(yml, fp, default_flow_style=False)

    # Tell project what happened, on private@
    msg = "The following notification schemes have been changed on %s by %s:\n\n%s\n\nWith regards,\nASF Infra.\n" \
          % (cfg.repo_name, cfg.committer, changes)
    asfpy.messaging.mail(
        sender='GitBox <gitbox@apache.org>',
        recipients=['private@%s.apache.org' % pname],
        subject="Notification schemes for %s.git updated" % cfg.repo_name,
        message=msg)


def collaborators(collabs, cfg, token):
    old_collabs = set()
    new_collabs = set(collabs)
    if len(new_collabs) > MAX_COLLABORATORS:
        raise Exception("You can only have a maximum of %u external triage collaborators, please reduce the list." % MAX_COLLABORATORS)
    if os.path.exists(COLLABORATOR_FILE):
        old_collabs = set([x.strip() for x in open(COLLABORATOR_FILE) if x.strip()])
    if new_collabs != old_collabs:
        print("Updating collaborator list for GitHub")
        to_remove = old_collabs - new_collabs
        to_add = new_collabs - old_collabs
        for user in to_remove:
            print("Removing GitHub triage access for %s" % user)
            requests.delete("https://api.github.com/repos/apache/%s/collaborators/%s" % (cfg.repo_name, user),
                            headers={"Authorization": "token %s" % token}
                            )
        for user in to_add:
            print("Adding GitHub triage access for %s" % user)
            requests.put("https://api.github.com/repos/apache/%s/collaborators/%s" % (cfg.repo_name, user),
                            headers={"Authorization": "token %s" % token},
                            json={"permission": "triage"}
                            )
        with open(COLLABORATOR_FILE, "w") as f:
            f.write("\n".join(collabs))
            f.close()
