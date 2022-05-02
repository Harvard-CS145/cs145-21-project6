import numpy as np
import random as rdm
import string
import sys
from os import path
import argparse
from p4utils.utils.topology import Topology
import json

# Global Modes
mode = "mix" # "mix" / "iperf"
flow_size_dist = "uniform" # "uniform" / "long"
flow_size_min = 1000 # ms
flow_size_max = 8000 # ms
flow_gen_mode = "global" # "global" / "perflow"
per_flow_mode = "random" # "random" / "tiled"
num_flows = 16
gap_dist = "poisson" # "poisson" / "uniform" / "persist"
gap_min = 1000 # ms
gap_max = 2000 # ms
mc_hosts_string = "1-16"
iperf_hosts_string = "1-16"
length = 60000
trace_file_name = "test.trace"

memcached_traces = []
iperf_traces = []

memcached_keys = []

topo = Topology(db="topology.db")

def get_random_string(size):
    return ''.join(rdm.choice(string.ascii_letters + string.digits) for x in range(size))

def gen_memcached_trace():
    p = rdm.uniform(0, 1)
    if p <= 0.5 or len(memcached_keys) == 0:
        if p <= 0.25 or len(memcached_keys) == 0:
            key = get_random_string(8)
            memcached_keys.append(key)
            value = rdm.randint(0, 65535)
            return key, value
        else:
            idx = rdm.randint(0, len(memcached_keys) - 1)
            key = memcached_keys[idx]
            value = rdm.randint(0, 65535)
            return key, value
    else:
        idx = rdm.randint(0, len(memcached_keys) - 1)
        key = memcached_keys[idx]
        value = -1
        return key, value

def gen_memcached(host_list, length):
    if len(host_list) == 0:
        return
    next_req = 0
    
    next_req = next_req + np.random.poisson(100)
    while next_req < length:
        host = host_list[rdm.randint(0, len(host_list) - 1)]
        burst = np.random.zipf(1.5)
        if burst > 1000:
            burst = 1000
        for i in range(1000):
            key, value = gen_memcached_trace()
            memcached_traces.append((next_req + i, host, key, value))
        next_req = next_req + np.random.poisson(100)

def gen_iperf(host_list, length):
    if len(host_list) == 0:
        return
    if flow_gen_mode == 'global':
        next_req = 0
        while next_req < length:
            src = host_list[rdm.randint(0, len(host_list) - 1)]
            dst = host_list[rdm.randint(0, len(host_list) - 1)]
            while dst == src:
                dst = host_list[rdm.randint(0, len(host_list) - 1)]
            if flow_size_dist == 'uniform':
                burst = rdm.randint(flow_size_min, flow_size_max)
            else:
                burst = flow_size_max
            iperf_traces.append((next_req, src, topo.get_host_ip("h%d" % dst), burst))
            if gap_dist == 'poisson':
                next_req = next_req + np.random.poisson(gap_max)
            elif gap_dist == 'uniform':
                next_req = next_req + rdm.randint(gap_min, gap_max)
            else:
                next_req = next_req + gap_max
    else:
        flows = []
        if per_flow_mode == 'random':
            for i in range(num_flows):
                src = host_list[rdm.randint(0, len(host_list) - 1)]
                dst = host_list[rdm.randint(0, len(host_list) - 1)]
                while dst == src:
                    dst = host_list[rdm.randint(0, len(host_list) - 1)]
                flows.append((src, dst))
        else:
            src_idx = 0
            dst_idx = len(host_list) / 2
            for i in range(num_flows):
                src = host_list[src_idx]
                dst = host_list[dst_idx]
                flows.append((src, dst))
                src_idx += 1
                if src_idx == len(host_list) / 2:
                    src_idx = 0
                dst_idx += 1
                if dst_idx == len(host_list):
                    dst_idx = len(host_list) / 2
        for flow in flows:
            next_req = 0
            while next_req < length:
                if flow_size_dist == 'uniform':
                    burst = rdm.randint(flow_size_min, flow_size_max)
                else:
                    burst = flow_size_max
                iperf_traces.append((next_req, flow[0], topo.get_host_ip("h%d" % flow[1]), burst))
                if gap_dist == 'poisson':
                    next_req = next_req + np.random.poisson(gap_max)
                elif gap_dist == 'uniform':
                    next_req = next_req + rdm.randint(gap_min, gap_max)
                else:
                    next_req = next_req + gap_max

def parse_hosts(hosts_string):
    host_list = []
    if hosts_string == "0":
        return host_list
    hosts = hosts_string.split(',')
    for host_set in hosts:
        if '-' in host_set:
            hlist = host_set.split('-')
            h_start = int(hlist[0])
            h_end = int(hlist[1])
            for host in range(h_start, h_end + 1):
                host_list.append(host)
        else:
            host_list.append(int(host_set))
    return host_list

if __name__ == "__main__":
    config_filename = "apps/trace/trace.json"
    if len(sys.argv) == 2:
        config_filename = sys.argv[1]

    if not path.exists(config_filename):
        print("Config file does not exist!")
        exit()

    with open(config_filename, "r") as f:
        jsonText = f.read()
        jsonDict = json.loads(jsonText)
        print(jsonDict)
        f.close()

    mode = jsonDict.get("mode", "mix")
    flow_size_dist = jsonDict.get('flow_size_dist', 'uniform')
    flow_size_min = int(jsonDict.get('flow_size_min', 1) * 1000)
    flow_size_max = int(jsonDict.get('flow_size_max', 8) * 1000)
    if flow_size_min <= 0 or flow_size_max <= 0:
        print("Flow size must be larger than 0!")
        exit()
    flow_gen_mode = jsonDict.get('flow_generate_mode', 'global')
    per_flow_mode = jsonDict.get('perflow_mode', 'random')
    num_flows = jsonDict.get('flow_num', 16)
    if num_flows <= 0:
        print("Number of flows must be larger than 0!")
        exit()
    gap_dist = jsonDict.get('flow_gap_dist', 'poisson')
    gap_min = int(jsonDict.get('flow_gap_min', 1) * 1000)
    gap_max = int(jsonDict.get('flow_gap_max', 2) * 1000)
    if gap_min < 0 or gap_max < 0:
        print("Inter-flow gap must be no less than 0!")
        exit()
    mc_host_list = jsonDict.get('memcached_host_list', [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
    iperf_host_list = jsonDict.get('iperf_host_list', [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
    length = int(jsonDict.get('length', 60) * 1000)
    if length <= 0:
        print("Trace length must be larger than 0!")
        exit()
    out_file = jsonDict.get('file', "apps/trace/trace.txt")

    if jsonDict.get('simple', False):
        mode = 'iperf'
        flow_size_dist = 'long'
        flow_size_max = length
        flow_gen_mode = 'perflow'
        per_flow_mode = 'tiled'
        num_flows = len(iperf_host_list) / 2
        gap_dist = 'persist'
        gap_max = length + 1000

    if mode == "mix":
        gen_memcached(mc_host_list, length)
    gen_iperf(iperf_host_list, length)

    traces = memcached_traces + iperf_traces
    traces.sort()

    f = open(out_file, "w")
    for i in mc_host_list:
        f.write(topo.get_host_ip("h%d" % i))
        f.write(' ')
    f.write("\n")

    for trace in traces:
        f.write("h%d " % trace[1])
        f.write("%f " % (trace[0] / 1000.0))
        if "." in trace[2]:
            f.write("2 %s %f\n" % (trace[2], trace[3] / 1000.0))
        else:
            if trace[3] == -1:
                f.write("1 %s\n" % trace[2])
            else:
                f.write("0 %s %d\n" % (trace[2], trace[3]))

