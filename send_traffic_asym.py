import random
import time
from p4utils.utils.topology import Topology
from subprocess import Popen
import sys

topo = Topology(db="topology.db")

iperf_send = "mx {0} iperf3 -c {1} -u -b 100K -l 1000 -t {2} --bind {3} -p {4} 2>&1 >/dev/null"
iperf_recv = "mx {0} iperf3 -s -p {1} --one-off 2>&1 >/dev/null"

Popen("sudo killall iperf iperf3", shell=True)

used_ports = []

duration = int(sys.argv[1])
bandwidth = float(sys.argv[2])

bandwidth = bandwidth * 1000000

num_flows = int(bandwidth/100000)

print("bandwidth : "+ str(bandwidth))
print("num_flows : "+ str(num_flows))

for x in range(num_flows):
	port = random.randint(1024, 65000)
	while port in used_ports:
		port = random.randint(1024, 65000)
	used_ports.append(port)


for port in used_ports:
	Popen(iperf_recv.format("h2", port), shell=True)

time.sleep(2)


for port in used_ports:
	Popen(iperf_send.format("h1", topo.get_host_ip("h2"), duration, topo.get_host_ip("h1"), port), shell=True)
# Popen(iperf_send.format("h1", topo.get_host_ip("h2"), duration, topo.get_host_ip("h1"), dst_port2, dst_port2), shell=True)
