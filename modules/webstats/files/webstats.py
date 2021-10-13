#!/usr/bin/env python3
import elasticsearch
import pyexcel_ods
import collections
import requests
import re
import sys
import yaml
import time
from time import gmtime, strftime
import os

# Exported files go here
EXPORTS = '/var/www/snappy/exports'
LDAPMAP = {}

# Elastic handler
es = elasticsearch.Elasticsearch([
        {'host': 'localhost', 'port': 9200, 'url_prefix': '', 'use_ssl': False},
])

def dump_yaml(data, stream=None, Dumper=yaml.Dumper, **kwds):
    class OrderedDumper(Dumper):
        pass
    def _dict_representer(dumper, data):
        return dumper.represent_mapping(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            data.items())
    OrderedDumper.add_representer(collections.OrderedDict, _dict_representer)
    return yaml.dump(data, stream, OrderedDumper, encoding = None, default_flow_style=False)

        

# Make a "book" (an ODS file)
def makeBook(domain):
        book = collections.OrderedDict()
        
        # This is the global search. We'll adjust as needed
        query = {
            "query": {
                "bool": {
                    "must": [{
                            "query_string": {
                                "query": "vhost:\"%s\" AND document:*.html AND useragent:mozilla" % domain,
                                "analyze_wildcard": True
                            }
                        }, {
                            "range": {
                                "@timestamp": {
                                    "gte": "now-30d",
                                    "lte": "now",
                                    "format": "epoch_millis"
                                }
                            }
                        }
                    ],
                    "must_not": []
                }
            },
            "size": 0,
            "_source": {
                "excludes": []
            },
        }
        
        # Get most of the aggregations
        query['aggs'] = {
                "per_day": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "interval": "1d",
                        "time_zone": "UTC",
                        "min_doc_count": 1
                    },
                    "aggs": {
                        "uniques": {
                            "cardinality": {
                                "field": "client_ip.keyword"
                            }
                        }
                    }
                },
                "popular" : {
                    "terms" : {
                        "field" : "uri.keyword",
                        "size" : 50,
                        "order" : {"_count":"desc"}
                    }
                },
                "refs" : {
                    "terms" : {
                         "field" : "referer.keyword",
                         "size" : 25,
                         "order" : {"_count":"desc"}
                     }
                }
            }
        res = es.search(index='loggy-*', request_timeout=90, body = query)
        
        arr = [['Date', 'Unique visitors']]
        for el in res['aggregations']['per_day']['buckets']:
                d = el['key_as_string'].replace(' 00:00:00', '')
                c = el['uniques']['value']
                arr.append([d,c])
        book.update({'Unique visitors, past month': arr})
        
        
        
        arr = [['Date', 'Pageviews']]
        for el in res['aggregations']['per_day']['buckets']:
                d = el['key_as_string'].replace(' 00:00:00', '')
                c = el['doc_count']
                arr.append([d,c])
        book.update({'Pageviews, past month': arr})
        
        
        
        arr = [['URI', 'Pageviews']]
        for el in res['aggregations']['popular']['buckets']:
                d = el['key']
                c = el['doc_count']
                arr.append([d,c])
        book.update({'Most visited pages, past month': arr})
        
        
        
        arr = [['Referrer', 'Pageviews']]
        for el in res['aggregations']['refs']['buckets']:
                d = el['key']
                c = el['doc_count']
                # We only use it if > 10 people have used it, so as to not divulge PII
                if c > 10 and d != '-':
                        arr.append([d,c])
        book.update({'Top referrers, past month': arr})
        
        
        
        # Geomapping
        # We need to weed out some things here
        query["query"]["bool"]["must_not"].append({"query_string": {"query": '(geo_country.keyword in ("EU", "AP", "A1", "A2", "SX", "SS", "-")) AND NOT geo_country.keyword:"-"'}})
        query["aggs"] = {
                "country" : {
                        "terms" : {
                                "field" : "geo_country.keyword",
                                "size" : 200,
                                "order" : {"_count":"desc"}
                                }
                        }
                }
        res = es.search(index='loggy-*', request_timeout=90, body = query)
        
        arr = [['Country', 'Pageviews']]
        for el in res['aggregations']['country']['buckets']:
                if el['key'] != '-':
                        d = el['key']
                        c = el['doc_count']
                        arr.append([d,c])
        book.update({'Geomapping, past month': arr})
        
        try:
            if domain in LDAPMAP:
                lines = []
                pmc = LDAPMAP[domain]
                print("Fetching download stats for %s..." % pmc)
                eu = requests.get('http://www.eu.apache.org/dyn/stats/%s.log' % pmc)
                us = requests.get('http://www.us.apache.org/dyn/stats/%s.log' % pmc)
                if eu.status_code == 200:
                    lines += eu.text.split("\n")
                if us.status_code == 200:
                    lines += us.text.split("\n")
                cdownloads = {}
                now = time.time()
                for line in lines:
                    try:
                        ts, junk, cca, path = line.split(" ", 3)
                        ts = int(ts)
                        if (ts + (30*86400)) >= now:
                            cdownloads[cca] = cdownloads.get(cca, 0) + 1
                    except:
                        pass
                arr = [['Country', 'Downloads']]
                for k, v in cdownloads.items():
                    arr.append([k.upper(), v])
                book.update({'Downloads, past month': arr})
        except Exception as e:
            print(e)

        pyexcel_ods.save_data("%s/%s.ods" % (EXPORTS, domain), book)

#       Convert to YAML
        booky = {}
        booky['Sheet0'] = { # ensure it is first
            'Domain': domain,
            'Created': strftime("%Y-%m-%d %H:%M +0000", gmtime())
        }
        sheetno = 0
        for key,val in book.items():
            sheetno += 1
            tmp = []
            for k,v in val:
                if k: tmp.append((k,v))
            tmp.pop(0) # get rid of titles
            data = collections.OrderedDict(tmp)
            sheet = booky["Sheet%d" % sheetno] = {
                "Name": key,
                "Values": data
                }
        with open("%s/%s.yaml" % (EXPORTS, domain),'w') as wy:
            wy.write("# web statistics for %s\n" % domain)
            wy.write("---\n")
            dump_yaml(booky, wy)


if __name__ == '__main__':
    if sys.argv[1:]: # If arguments provided, then process only those (for testing)
        for sdomain in sys.argv[1:]:
            print("Charting %s" % sdomain)
            makeBook(sdomain)
    else:
        
        # Clean up stale files (more than a week old)
        now = time.time()
        for filename in os.listdir(EXPORTS):
            filepath = os.path.join(EXPORTS, filename)
            mtime = os.path.getmtime(filepath)
            if (mtime < (now - 604800)):
                print("Removing stale file %s" % filepath)
                os.unlink(filepath)

        os.path.getmtime
        # Get all projects, committees, podlings
        cmts = requests.get('https://whimsy.apache.org/public/committee-info.json').json()
        pods = requests.get('https://whimsy.apache.org/public/public_podlings.json').json()
        
        regex = re.compile(r"https?://([^/]+)/?$", re.IGNORECASE)
        # Churn out a list of sub-domains to gather stats for
        subdomains = ['www.openoffice.org', 'openoffice.org', 'www.apache.org', 'apache.org']
        for k, cmt in cmts['committees'].items():
            if not cmt['pmc'] or not cmt['site']:
                continue
            m = regex.match(cmt['site'])
            if m:
                subdomain = m.group(1)
                subdomains.append(subdomain)
                LDAPMAP[subdomain] = k
        
        for k, cmt in pods['podling'].items():
            subdomain = "%s.apache.org" % k
            if cmt['status'] == "current" and subdomain not in subdomains:
                subdomains.append(subdomain)
                
        for sdomain in sorted(subdomains):
                if sdomain:
                        print("Charting %s" % sdomain)
                        makeBook(sdomain)
    print("All done")
