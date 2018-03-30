# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import json
from libmozdata import socorro, connection
import urllib.request
import gzip
import re
from pprint import pprint


URL = 'https://s3-us-west-2.amazonaws.com/org.mozilla.crash-stats.symbols-public/v1/xul.pdb/{}/xul.sym'


def get_buildids():

    def handler(json, data):
        for facets in json['facets']['build_id']:
            bid = facets['term']
            data[bid] = [uuid['term'] for uuid in facets['facets']['uuid']]

    params = {'product': 'Firefox',
              'release_channel': 'nightly',
              'build_id': '>=20180201000000',
              'platform': '=Windows NT',
              '_aggs.build_id': 'uuid',
              '_results_number': 0,
              '_facets': 'product',
              '_facets_size': 1000}

    data = {}
    socorro.SuperSearch(params=params,
                        handler=handler,
                        handlerdata=data).wait()

    return data


def get_xul_debugid(uuids):
    data = socorro.ProcessedCrash.get_processed(uuids)
    for uuid, info in data.items():
        for module in info['json_dump']['modules']:
            if module['debug_file'] == 'xul.pdb':
                return module['debug_id']
    return None


def get_debugids():
    res = {}
    for buildid, uuids in get_buildids().items():
        print('Get debugid for buildid {}'.format(buildid))
        debugid = get_xul_debugid(uuids[0])
        if debugid:
            res[buildid] = debugid
        else:
            for _uuids in connection.Connection.chunks(uuids[1:]):
                debugid = get_xul_debugid(_uuids)
                if debugid:
                    res[buildid] = debugid
                    break
        if buildid not in res:
            print('No debugid for buildid {}.'.format(buildid))
    return res


def save_debugids(path):
    debugids = get_debugids()
    with open(path, 'w') as Out:
        json.dump(debugids, Out)


def get(buildid, debugid):
    print('Get data for buildid {}'.format(buildid))
    request = urllib.request.Request(URL.format(debugid))
    request.add_header('Accept-encoding', 'gzip')
    response = urllib.request.urlopen(request)
    if response.info().get('Content-Encoding') == 'gzip':
        f = gzip.decompress(response.read())
        return list(map(lambda x: x.strip(), f.decode('utf-8').split('\n')))
        

def check(buildid, debugid):
    for line in get(buildid, debugid):
        if 'static bool mozilla::SpinEventLoopUntil' in line:
            return True
    return False


def _find(debugids):
    first = 0
    last = len(debugids) - 1
    found = False

    while first <= last:
        mid = (first + last) // 2
        buildid, uuid = debugids[mid]
        if check(buildid, uuid):
            last = mid - 1
        else:
            first = mid + 1

    return first, last


def get_diff():
    pat = re.compile(r'([^\(<]+)')
    bad, good = read_sym()
    static_bad = {' '.join(x.replace('static ', '').split(' ')[5:]) for x in bad if 'FUNC ' in x and 'static ' in x}
    static_bad = {pat.search(x).group(0) for x in static_bad}
    _good = {' '.join(x.split(' ')[4:]) for x in good if 'FUNC ' in x}
    _good = {pat.search(x).group(0) for x in _good}
    common = static_bad & _good
    common = list(common)
    
    return common

            
def save_sym(bad, good):
    bad, good = get(*bad), get(*good)
    with open('/tmp/bad.json', 'w') as Out:
        json.dump(bad, Out)
    with open('/tmp/good.json', 'w') as Out:
        json.dump(good, Out)

    return bad, good


def read_sym():
    with open('/tmp/bad.json', 'r') as In:
        bad = json.load(In)
    with open('/tmp/good.json', 'r') as In:
        good = json.load(In)

    return bad, good


def find(path):
    with open(path, 'r') as In:
        data = json.load(In)
        debugids = list(sorted(data.items()))        
        bad, good = _find(debugids)
        bad, good = debugids[bad], debugids[good]
        print('Good {}'.format(good))
        print('Bad {}'.format(bad))
        bad, good = save_sym(bad, good)
        


# save_debugids('/tmp/debugids.json')
# find('/tmp/debugids.json')
diff = get_diff()

with open('/tmp/functions.json', 'w') as Out:
    json.dump(diff, Out)
