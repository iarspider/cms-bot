#!/usr/bin/env python3
import sys
from os.path import exists, join
import json
from es_utils import get_summary_stats_from_json_file

data = []
e, o = subprocess.getstatusoutput(
    "find %s -maxdepth 6 -mindepth 6 -name opts.json -type f | sed 's|/opts.json$||'" % sys.argv[1]
)
for d in o.split("\n"):
    tool = d.split("/")[-2]
    jf = join(d, "opts.json")
    lf = join(d, "log")
    sf = join(d, "%s.json" % tool)
    if not exists(lf) or not exists(sf):
        continue
    e, c = subprocess.getstatusoutput("tail -1 %s | grep 'exit 0' | wc -l" % lf)
    if c == "0":
        continue
    jopts = {}
    with open(jf) as opts_dict_f:
        jopts = json.load(opts_dict_f)
    item = get_summary_stats_from_json_file(sf, 1)
    item.update(jopts)
    data.append({"_source": item})

print(json.dumps(data, sort_keys=True, indent=2))
