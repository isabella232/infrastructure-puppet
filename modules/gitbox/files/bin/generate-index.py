#!/usr/bin/python

import os
import sys
import json
import subprocess
import time
import datetime
import re
import requests
import datetime

GITPATH = "/x1/repos/asf"
PODLINGS_URL = "https://whimsy.apache.org/public/public_podlings.json"
TLPS_URL = "https://whimsy.apache.org/public/committee-info.json"
RETIRED_URL = "https://whimsy.apache.org/public/committee-retired.json"
JSONFILE = "/x1/gitbox/htdocs/repositories.json"
TXTFILE = "/x1/gitbox/htdocs/repos.txt"

#PODLINGS['podling'][project]['name']
#TLPS['committees'][project]['display_name']

def newest(path):
    """ Returns the age of the newest object in a repo dir """
    files = os.listdir(path)
    paths = [os.path.join(path, basename) for basename in files]
    return os.stat(max(paths, key=os.path.getmtime)).st_mtime

def getActivity():
    
    # Get Whimsy data first
    PODLINGS = requests.get(PODLINGS_URL).json()
    TLPS = requests.get(TLPS_URL).json()
    RETIRED = requests.get(RETIRED_URL).json()
    
    repos = [x for x in os.listdir(GITPATH) if
                 os.path.isdir(os.path.join(GITPATH, x))
            ]
    
    projects = {}
    gitrepos = {}
    outjson = {
        'updated': int(time.time()),
        'projects': {}
    }
    comcounts = {}
    for repo in repos:
        
        repopath = os.path.join(GITPATH, repo)
        
        # Get repo description
        repodesc = "No Description"
        dpath = os.path.join(repopath, 'description')
        if os.path.exists(dpath):
            repodesc = open(dpath).read().strip()
        
        # Get archive status
        nocommit = os.path.exists(os.path.join(repopath, "nocommit"))
        if nocommit: repodesc += " (archived)"

        # Get latest commit timestamp, default to none
        lcommit = 0
        last_hour = int(time.time())
        last_hour = int(last_hour - (last_hour % 3600))
        try:
            lcommit = int(newest(repopath+"/objects"))
        except:
            pass # if it failed (no commits etc), default to no commits
        
        now = time.time()
        ago = now - lcommit
        
        # Make 'N ago..' string
        agotxt = "No commits"
        if lcommit == 0:
            agotxt = "No commits"
        elif ago < 60:
            agotxt = "&lt;1 minute ago"
        elif ago < 120:
            agotxt = "&lt;2 minutes ago"
        elif ago < 300:
            agotxt = "&lt;5 minutes ago"
        elif ago < 900:
            agotxt = "&lt;15 minutes ago"
        elif ago < 1800:
            agotxt = "&lt;30 minutes ago"
        elif ago < 3600:
            agotxt = "&lt;1 hour ago"
        elif ago < 7200:
            agotxt = "&lt; 2 hours ago"
        elif ago < 14400:
            agotxt = "&lt; 4 hours ago"
        elif ago < 43200:
            agotxt = "&lt; 12 hours ago"
        elif ago < 86400:
            agotxt = "&lt; 1 day ago"
        elif ago < 172800:
            agotxt = "&lt; 2 days ago"
        elif ago <= (31 * 86400):
            agotxt = "%u days ago" % round(ago/86400)
        else:
            agotxt = "%u weeks ago" % round(ago/(86400*7))
        
        if lcommit == 0:
            agotxt = "<span style='color: #777; font-style: italic;'>%s</span>" % agotxt
        elif ago <= 172800:
            agotxt = "<span style='color: #070;'>%s</span>" % agotxt
            
        # Store in project hash
        r = re.match(r"^(?:incubator-(?:retired-)?)?(empire-db|[^-.]+).*", repo)
        project = r.group(1)
        projects[project] = projects.get(project, [])
        repo = repo.replace(".git", "") # Crop this for sorting reasons (INFRA-15952)
        projects[project].append(repo)
        if len(repodesc) > 64:
            repodesc = repodesc[:61] + "..."
        gitrepos[repo] = [agotxt, repodesc, lcommit, nocommit]
    
    html = ""
    a = 0
    for project in sorted(projects):
        a %= 3
        a += 1
        pname = project[0].upper() + project[1:]
        if project in TLPS['committees']:
            pname = "Apache " + TLPS['committees'][project]['display_name']
        elif project in RETIRED['retired']:
            pname = "Apache " + (RETIRED['retired'][project]['display_name'] or pname) + ' (Retired)'
        elif project in PODLINGS['podling'] and PODLINGS['podling'][project]['status'] == 'retired':
            pname = "Apache " + PODLINGS['podling'][project]['name'] + " (Retired Podling)"
        elif project in PODLINGS['podling'] and PODLINGS['podling'][project]['status'] != 'graduated':
            pname = "Apache " + PODLINGS['podling'][project]['name'] + " (Incubating)"
        
        outjson['projects'][project] = {
            'domain': project,
            'description': pname,
            'repositories': {}
        }
        
        table = """
<table class="tbl%u" id="%s">
<thead>
    <tr>
        <td colspan="4"><a href="#%s">%s</a></td>
    </tr>
</thead>
<tbody>
    <tr>
        <th>Repository name:</th>
        <th>Description:</th>
        <th>Last changed:</th>
        <th>Links:</th>
    </tr>
""" % (a, project, project, pname)
        for repo in sorted(projects[project]):
            nclass = "disabled" if gitrepos[repo][3] else ""
            outjson['projects'][project]['repositories'][repo] = {
                'description': gitrepos[repo][1],
                'last_update_txt': gitrepos[repo][0],
                'last_update_int': gitrepos[repo][2]
            }
            table += """
    <tr class="%s">
        <td><a href="/repos/asf/%s.git">%s.git</a></td>
        <td>%s</td>
        <td>%s</td>
        <td>
            <a href="/repos/asf/?p=%s.git;a=summary">Summary</a> |
            <a href="/repos/asf/?p=%s.git;a=shortlog">Short Log</a> |
            <a href="/repos/asf/?p=%s.git;a=log">Full Log</a> |
            <a href="/repos/asf/?p=%s.git;a=tree">Tree View</a>
        </td>
    </tr>
""" % (nclass, repo, repo, gitrepos[repo][1],gitrepos[repo][0], repo, repo, repo, repo)
    
        table += "</table>"
        html += table
    now = datetime.datetime.now().isoformat()
    html += "<hr/><p>Index last updated: %s</p>\n" % now
    return html, outjson, comcounts


html = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<link rel="stylesheet" href="/css/gitbox.css">
<title>Apache GitBox Repositories</title>
</head>

<body>
<img src="/images/gitbox-logo.png" style="margin-left: 125px; width: 750px;"/><br/>
"""

repohtml, asjson, cactivity = getActivity()

html += repohtml
html += """
</body>
</html>
"""
print(html)


# JSON OUTPUTS
with open(JSONFILE, "w") as f:
    json.dump(asjson, f)
    f.close()

# TXT output
repos = [x for x in os.listdir(GITPATH) if
             os.path.isdir(os.path.join(GITPATH, x))
        ]
with open(TXTFILE, "w") as f:
    f.write("\n".join(sorted(repos)))
    f.close()
