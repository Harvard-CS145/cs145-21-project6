#!/usr/bin/env python

import collections
from collections import defaultdict
import os
import re
import shutil
import time
import sys
import commands
import math
import argparse

# h1 and h10 is used for video applications.
HOSTS=["h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9", "h10", "h11", "h12", "h13", "h14", "h15", "h16"]

MN_PATH='~/mininet'
MN_UTIL=os.path.join(MN_PATH, 'util', 'm')

LOG_DIR='logs'

CmdMemcachedClient = {
	'start': 'stdbuf -o0 -e0 python apps/memcached_client.py {start_time} {host_name} {traffic_file} > {log_dir}/{host_name}_mc.log 2> {log_dir}/{host_name}_mc_error.log &',
	# 'start': 'python apps/memcached_client.py {start_time} {host_name} {traffic_file} > logs/{host_name}_mc.log 2>/dev/null &',
	'kill': 'sudo pkill "python apps/memcached_client.py" 2>/dev/null'
}

CmdMemcachedServer = {
	'start': 'memcached -u p4 -m 100 >/dev/null 2>&1 &',
	'kill': 'sudo killall memcached 2>/dev/null'
}

CmdIperfClient = {
	'start': 'stdbuf -o0 -e0 python apps/iperf_client.py {start_time} {host_name} {traffic_file} > {log_dir}/{host_name}_iperf.log 2> {log_dir}/{host_name}_iperf_error.log &',
	# 'start': 'python apps/iperf_client.py {start_time} {host_name} {traffic_file} > logs/{host_name}_iperf.log 2>/dev/null &',
	'kill': 'sudo pkill "python apps/iperf_client.py" 2>/dev/null'
}

CmdIperfServer = {
	'start': 'iperf3 -s -p {port_num} >/dev/null 2>&1 &',
	'kill': 'sudo killall iperf3 2>/dev/null'
}

def MnExec(hostName, command):
	cmd = '%s %s %s' % (MN_UTIL, hostName, command)
	os.system(cmd)

def wait_util(t):
	now = time.time()
	if now >= t:
		return
	time.sleep(t - now)

def read_mc_latencies():
	res = []
	for host in HOSTS:
		log_fn = "%s/%s_mc.log" % (LOG_DIR, host)
		with open(log_fn, "r") as f:
			lines = f.readlines()[1:]
			res.extend(lines)
	res = map(float, res)
	return res

def read_iperf_throughputs():
	res = []
	for host in HOSTS:
		log_fn = "%s/%s_iperf.log" % (LOG_DIR, host)
		with open(log_fn, "r") as f:
			lines = f.readlines()[1:]
			res.extend(lines)
	res = map(float, res)
	return res
		
class Experiment:
	def __init__(self, traffic_file, hosts, duration, port_num=5001):
		self.traffic_file = traffic_file
		self.hosts = hosts
		self.duration = duration
		self.port_num = port_num
		self.mode = 0
		with open(traffic_file, "r") as file:
			lines = file.readlines()
			if lines[0][:-1] == '':
				self.mode = 1
	def start(self):
		now = time.time()
		print "start iperf and memcached servers"
		for host in self.hosts:
			# host = "h%d"%(i+1)
			if self.mode == 0:
				self.run_mc_server(host)
			self.run_iperf_server(host)
		print "wait 5 sec for iperf and memcached servers to start"
		time.sleep(5)
		print "start iperf and memcached clients"
		self.start_time = int(now) + 3
		for host in self.hosts:
			# host = "h%d"%(i+1)
			if self.mode == 0:
				self.run_mc_client(host)
			print "Run iperf client on host", host
			self.run_iperf_client(host)

		print "wait for experiment to finish"
		wait_util(self.start_time + self.duration)
		print "stop everything"
		for host in self.hosts:
			# host = "h%d"%(i+1)
			if self.mode == 0:
				self.stop_mc_server(host)
				self.stop_mc_client(host)
			self.stop_iperf_server(host)
			self.stop_iperf_client(host)
		# print "wait 60 sec to make log flushed"
		# time.sleep(60)

	def run_mc_server(self, host):
		MnExec(host, CmdMemcachedServer["start"])
	def stop_mc_server(self, host):
		MnExec(host, CmdMemcachedServer["kill"])
	def run_mc_client(self, host):
		MnExec(host, CmdMemcachedClient["start"].format(start_time = self.start_time, host_name = host, traffic_file = self.traffic_file, log_dir = LOG_DIR))
	def stop_mc_client(self, host):
		MnExec(host, CmdMemcachedClient["kill"])
	def run_iperf_server(self, host):
		MnExec(host, CmdIperfServer["start"].format(port_num = self.port_num))
	def stop_iperf_server(self, host):
		MnExec(host, CmdIperfServer["kill"])
	def run_iperf_client(self, host):
		MnExec(host, CmdIperfClient["start"].format(start_time = self.start_time, host_name = host, traffic_file = self.traffic_file, log_dir = LOG_DIR))
	def stop_iperf_client(self, host):
		MnExec(host, CmdIperfClient["kill"])

	def calc_score(self, a, b):
		scorea = 0
		scoreb = 0

		if self.mode == 0:
			#mc_latency = map(float, filter(is_not_comment, commands.getoutput("cat %s/*_mc.log" % LOG_DIR).split('\n')))
			mc_latency = read_mc_latencies()
			latency_scores = map(lambda x: math.log(x, 10), mc_latency)
			if len(latency_scores) > 0:
				scoreb = sum(latency_scores) / len(latency_scores)
				print "Average latency of Memcached Requests:", sum(mc_latency) / len(mc_latency), "(us)"
				print "Average log(latency) of Memcached Requests:", sum(latency_scores) / len(latency_scores)

		#iperf_bps = map(float, filter(is_not_comment, commands.getoutput("cat %s/*_iperf.log" % LOG_DIR).split('\n')[1:]))
		iperf_bps = read_iperf_throughputs()
		bps_scores = map(lambda x: math.log(x, 10), iperf_bps)
		if len(bps_scores) > 0:
			scorea = sum(bps_scores) / len(bps_scores)
			print "Average throughput of Iperf Traffic:", sum(iperf_bps) / len(iperf_bps), "(bps)"
			print "Average log(throughput) of Iperf Traffic:", sum(bps_scores) / len(bps_scores)

		print a * scorea - b * scoreb

def is_not_comment(line):
	return len(line) > 0 and line[0] != '#'

def read_score_config(score_file):
        with open(score_file, "r") as file:
                a,b = map(float, file.readlines())
        return a,b

def make_log_dir():
        if os.path.exists(LOG_DIR): shutil.rmtree(LOG_DIR)
        os.makedirs(LOG_DIR)

def parse_hosts(host_string):
	host_list = []
	host_items = host_string.split(',')
	for host_item in host_items:
		if '-' in host_item:
			hosts = host_item.split('-')
			host_start = int(hosts[0])
			host_end = int(hosts[1])
			for i in range(host_start, host_end + 1):
				host_list.append("h%d" % i)
		else:
			host_list.append("h%d" % int(host_item))
	return host_list

if __name__ == '__main__':
	parser = argparse.ArgumentParser(description='A trace generator')
	parser.add_argument('--trace', help='Traffic trace file', required=True)
	parser.add_argument('--host', help='Hosts running the traffic', required=True)
	parser.add_argument('--length', help='The time length running the traffic', required=True, type=float)
	parser.add_argument('--logdir', help='The directory storing the logs', default="logs")
	parser.add_argument('--port', help='The port number running iperf servers', default=5001, type=int)
	args = parser.parse_args()
	
	HOSTS = parse_hosts(args.host)
	print(HOSTS)
	
	LOG_DIR = args.logdir

	a = 1
	b = 1

	make_log_dir()

	e = Experiment(args.trace, HOSTS, args.length)
	e.start()
	e.calc_score(a, b)
