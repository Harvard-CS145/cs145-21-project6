# Project 6: Congestion Aware Load Balancing

## Objectives:
- Implementing the [CONGA](https://people.csail.mit.edu/alizadeh/papers/conga-sigcomm14.pdf) load balancing algorithm.
- Understand the benefits of congestion aware load balancing

## Overview

In this project, we will support a better load balancing solution than ECMP---congestion-aware load balancing.
We will collect queuing information (i.e. for example how many packets are waiting to be transmitted) at switches to detect congestion (i.e. if a queue contains many packets). If an egress (the switch right before the destination host)identifies that the packet has experienced congestion, then it sends a notification message to the ingress switch of the packet. Upon receiving the message, the switch randomly moves the flow to another path. Obviously, this is by far not the best way of exploring available paths, but it will be enough to show how to collect information as packets cross the network, how to communicate between switches, and how to make them react to network states.

We encourage you to revisit `p4_explanation.md` in project 3 for references if you incur P4 related questions in this project.


## Part 1: Observing the problem

Here is a diagram of the `Medium topology` we will use for this Part:
![medium topology](images/MediumTopologyDiagram.png)

The bandwidth of each link is 10Mbps.

We will send flows from h1-h4 to h5-h8, and each flow will have four different potential paths to travel on. Let's use the current code and observe how flows collide.

1. Start the medium size topology:

   ```bash
   sudo p4run --config topology/p4app-medium.json
   ```

2. Open a `tmux` terminal by typing `tmux` (or if you are already using `tmux`, open another window and type `tmux`). And run monitoring script (`nload_tmux_medium.sh`). This script, will use `tmux` to create a window with 4 panes, in each pane it will lunch a `nload` session with a different interface (from `s1-eth1` to `s1-eth4`), which are the interfaces directly connected to `h1-h4`. nload, which has already been installed in our provided vm, is a console application which monitors network traffic and bandwidth usage in real time.

   ```bash
   tmux
   ./nload_tmux_medium.sh
   ```

3. Send traffic from `h1-h4` to `h5-h8`. Create the traffic trace via

   ```bash
   python apps/trace/generate_trace.py --simple --iperfhost 1-8 --length <time_to_send> --file apps/trace/onetoone.trace
   ```

Then send the trace using this command

   ```bash
   sudo apps/trace/send_traffic.py --trace apps/trace/onetoone.trace --host 1-8 --length <time_to_send> --port <port_number>
   ```

4. If you want to send 4 different flows, you can just run the command again with different port numbers. 

If each flow gets placed to a different path (very unlikely) you should get a bandwidth close to `9.5mbps` (remember, we set the link's bandwidth to that). For example,
after trying once, we got that 3 flows collide in the same path, and thus they get ~3mbps, and one flow gets full bandwidth:

<p align="center">
<img src="images/example.png" title="Bandwidth example">
<p/>

The objective of this exercise is to provide the network the means to detect these kind of collisions and react.

## Part 2: Detecting Congestion

Before implementing the real solution we will first do a small modification to the starting p4 program so to show how to read queue information. Some of the code
we will implement in this section will have to be changed for the final solution. Our objective in this example is
to add the telemetry header to all the tcp packets with dst port 7777. We add the `telemetry` header if the packet does not have it (first switch), and then update its `enq_qdepth` value setting it to the highest we find along the path.

1. First add a new header to the program and call it `telemetry`. This header has two fields: `enq_qdepth` (16 bits) and `nextHeaderType` (16 bits). You need to place this header between the `ethernet` and `ipv4` (take this into account when you define the deparser).
2. Update deparser accordingly.
3. When packets carry the `telemetry` header, the `ethernet.etherType` has to be set to `0x7777` (telemetry). Update the parser accordingly. Note, that the `telemetry` header
has a `nextHeaderType` that can be used by the parser to know which is the next header. Typically `0x800` (ipv4).
4. When the switch enqueues a packet to its output port, we get its queuing information at the egress pipeline. Specifically, `standard_metadata.enq_qdepth` contains the number of packets in the queue when this packet was enqueued (You can check out all the queue metadata fields in the [v1model.p4](https://github.com/p4lang/p4c/blob/master/p4include/v1model.p4#L59). You may need to do a casting when using the standard `enq_qdepth` (eg, `(bit<16>)standard_metadata.enq_qdepth`). 

To make this simple test work, you should implement the following logic at the egress pipeline:

   (1) If the `tcp` header is valid, and the `tcp.dstPort == 7777`, we identify this packet as a probe packet and run (2) and (3) on this packet

   (2) If there is no `telemetry` header, add the `telemetry` header to the packet and set the depth field to `standard_metadata.enq_qdepth`.  Modify the ethernet type to the one mentioned above, set the `nextHeaderType` to the ipv4 ethernet type.

   (3) If there is already a `telemetry` header and if `standard_metadata.enq_qdepth` value is higher than the value already in the header, store the new value. 

<!-- (a trick we use to send probes, see [scapy sending script](./probe_send.py)). -->

### Testing
At this point your switches should add the telemetry header to all the tcp packets with dst port 7777. This telemetry header will carry the worst queue depth found
across the path. To test if your toy congestion reader works do the following:

1. Start the topology.

   ```bash
   sudo p4run --config topology/p4app-medium.json
   ```

2. Open a terminal in `h1` and `h6`. And run the send.py and receive.py scripts. Note that these commands should be run in a new terminal tab or window, not as commands in the Mininet command line.

   ```bash
   mx h6
   python probe_receiver.py
   ```

   ```bash
   mx h1 python probe_sender.py 10.6.6.2 1000
   ```

  You should now see that the receiver prints the queue depth observed by the probes we are sending (packets with dst port == 7777). Of course, since we are not sending any traffic queues
  are always 0.

3. Run the traffic trace `apps/trace/onetoone.trace` again, you do not have to login into `h1`. This script will generate two flows from `h1`, `h2`, `h3` and `h4` to `h5`, `h6`, `h7`, and `h8`. These two
flows will collide (since there is one single path). If you continue sending probes you should see how the queue fills up to 63 and starts oscillating (due to tcp nature).


## Part 3: Keeping the telemetry in-network

In Part 2, we were setting the telemetry header as the packet entered the network with a specific destination port and kept the telemetry header until the destination. We just did that for the sake of showing you how the queue depth changes as we make flows collide in one path.

Now in Part 3 (the real implementation of CONGA), only switches from the inside the network use the telemetry header to detect congestion and move flows. Thus, packets leaving the internal network (going to a host) should not have the telemetry header in them. Therefore, we need to remove it before the packet reaches a host.

To do that you need to know which type of node (host or switch) is connected to each switch's port. As you have seen, to do something like that we need to use a table, the control plane, and the topology object that knows how nodes are connected. In brief, in this section you have to:

1. Define a new table `egress_type_table` and action in the ingress pipeline in P4. This table should match to the `egress_spec` and call an action that sets to which type of node (host or switch) the packet is going to (save that in a metadata field). For example, you can use the number 1 for hosts and 2 for switches. The type of outgoing node decides how whether to send feedback packet or not.
   
2. Apply this table `egress_type_table` at the ingress control once `egress_spec` is known.

3. Fill up the `set_egress_type_table` function in `routing-controller.py` program. The goal of this function is to install entries in `egress_type_table` based on your topology. For each switch, you should have one entry for each output port and the type of its connected node (i.e., host(1) or switch(2)).

4. Based on `egress_type_table`, manage the telemtry packets in the P4 egress pipeline. 
   
   (1) Do not check for the dst port 7777 anymore (remove that part of the code, for the final real implementation).

   (2) Identify if this is an ingress switch (the first hop on a path) , an egress switch (the last hop on a path), or a switch in the middle. **Hint:** You can check if there is a telemetry header in the packet, and check the output of the `egress_type_table`. If we haven't added any telemetry header to a packet yet, it's the ingress switch. If we have seen the telemetry header and the next hop is connected to a host, it's the egress switch. The rest are middle switches.

   (3) Ingress switch: Add the `telemetry` header, set the `enq_qdepth` field, `nextHeaderType`, and set the `etherType` to `0x7777` (telemetry).

   (4) Middle switch: Update the `enq_qdepth` field if its bigger than the current one.
   
   (5) Egress switch: Remove the `telemetry` header, and set the `etherType` to `0x800` (ipv4).
   

### Testing
At this point, for each TCP packet that enters the network, your switches should add the telemetry header and remove it when the packet exits to a host. To test that this is working, you can send TCP traffic and capture the packets on selected links into pcap files.  You can parse the pcap file with e.g., Wireshark to check: 
1. There are telemetry packets in the internal links. That is, these packets have Ethernet headers `0x7777` and that the next 4 bytes belong to the `telemetry` headers.
2. Traffic exiting the network (going to hosts) look normal (i.e., no telemetry headers).

**Note:** Due to adding extra bytes to packets you will not be able to run the `mininet> iperf` command anymore directly from the CLI. 
This is because by default, iperf sends packets with the maximum transmission unit (MTU). Thus if the ingress switch adds 4 bytes to packets, the interface would drop the over-sized packets. 
So when you run `iperf`, you should use `-M` to set its packet size. 
In our network created using `P4-utils`, the MTU is set to 9500. That's why in 
our `send_traffic*` scripts, we set iperf packtet size to be <= 9000 bytes.

## Part 4: Congestion notification

In this part, you will implement the egress logic that detects congestion for a flow, and send a feedback packet to the previous-hop ingress switch (the switch this flow used to enter the network in the topology). To generate
a packet and send it to the ingress switch you need to `clone` the packet that triggers the congestion, modify it, and send it back to the switch.

### Step 1: Notification conditions
There are several considerations to decide when to send a congestion notification. You should implement these conditions by extending the part in which egress switches remove the `telemetry` header.

1. Set notification threshold. The switch should only send a notification when the received queue `depth` is above a threshold. As default queues are 64 packets long, you can set the threshold as any number between 30 and 60 to trigger the notification message.

2. Reduce notifications per flow. Upon congestion the switch receives a burst of packets that would trigger many notification messages. To reduce the number of messages, we set a timeout per flow. For instance, every time you send a notification
message for flow X you save in a `register` the current timestamp. The next time you need to send a notification message, you check in the register if the time difference is bigger than some seconds (for example 0.5-1 second).

3. Probabilistic notifications across flows. Furthermore, during congestion, all the flows that see the congestion would trigger notification messages. Moving all the flows to a new path can be suboptimal. You may end up creating congestion in other paths and leaving the current one empty. Thus, sometimes it's better if you don't move them all. You can use a probability p (i.e., 33%) to decide whether to notify a flow and move it.

### Step 2: Generate notification packets
If all the conditions above are true, you can now generate the congestion notification packet. You can clone an incoming packet (you have to clone from egress to egress, see `p4_explaintion.md` in project 3 for more details) and modify the cloned packet to carry the congestion notification. 
You need to decide which port to clone the packet to. Here you have two options:

a. You define a `mirror_session` for each switch port.  For that you would need to use the `ingress_port` and a table that maps it to a mirror id that would send it to the port the packet came from.

b. You clone the packet to any port (lets say port 1, it really does not matter). And then you recirculate it by using the `recirculate` extern. This will allow you to send this packet again to the ingress pipeline so you can use the normal forwarding tables to forward the packet. I recommend you to use this second option since it does not require an extra table and you make sure the packet is properly forwarded using the routing table.

For the notification packet, you need to modify its ethernet type to the telemetry type we define (0x7778). Remember to update the parser accordingly.

**Hint 1:** Since we want to send the notification packet back to the ingress switch, you can just swap the source and destination IP addresses of the original packet, so the cloned packet's destination is the original source host. In this way, the notification packet is automatically routed to the ingress
switch and the ingress switch can drop the notification packet there.

**Hint 2:** To differentiate between `NORMAL`, `CLONED`, and `RECIRCULATED` packets, you can use the metadata `standard_metadata.instance_type` (see more at `p4_explaination.md`). 

<!-- Check the
standard metadata [documentation](https://github.com/p4lang/behavioral-model/blob/master/docs/simple_switch.md#standard-metadata). -->

### Testing
To test if your implementation sends notifications to the ingress switch, you can generate congestion, capture packets at the ingress switch, and see if you see packets with the telemetry type (0x7777). 

**Hint 3:** If you find testing on the medium topology is too complex, you may consider debugging on the line topology from project 0 and `send_traffic_simple.py` script. 

## Part 5: Move flows to new paths

In this section we will close the loop and implement the logic that makes ingress switches move flows to new paths. For that you need the following steps:

1. For every notification packet that should be dropped at this switch (meaning that the current switch is sending it to a host). You have to update how the congested flow is hashed.

2. For that you will need to save in a `register` an ID value for each flow. Every time you receive a congestion notification for a given flow you will have to update the register value with a new id (use a random number). Remember that
the notification message has the source and destination IPs swapped so to access the register entry of the original flow you have to take that into account when hashing the 5-tuple to get the register index.

3. You will also need to update the hash function used in the original program (ECMP) and add a new field to the 5-tuple hash that will act as a randomizer (something like we did for flowlet switching).

4. Finally make sure you drop the congestion notification message.

**Note:** Remember to use the `standard_metadata.instance_type` to correctly implement the ingress and egress logic.

## Part 6: Testing your full solution

Once your implementation is ready, here is the end-to-end testing steps:

1. Start the medium size topology:

   ```bash
   sudo p4run --config topology/p4app-medium.json
   ```

2. Open a `tmux` terminal by typing `tmux` (or if you are already using `tmux`, open another window and type `tmux`). And run monitoring script (`nload_tmux_medium.sh`). This script, will use `tmux` to create a window
with 4 panes, in each pane it will lunch a `nload` session with a different interface (from `s1-eth1` to `s1-eth4`), which are the interfaces directly connected to `h1-h4`.

   ```bash
   tmux
   ./nload_tmux_medium.sh
   ```

3. Send traffic from `h1-h4` to `h5-h8`. There is a script that will do that for you automatically. It will run 1 flow from each host:

   ```bash
   python send_traffic_onetoone.py 1000
   ```

4. If you want to send 4 different flows, you can just run the command again, it will first stop all the `iperf` sessions, alternatively, if you want
to stop the flow generation you can kill them:

   ```bash
   sudo killall iperf
   ```

This time, if your system works, flows should start moving until eventually converging to four different paths. Since we are using a very, very simple solution in which flows get just randomly re-hashed it can take some time until they converge (even a minute). Of course, this exercise was just a way to show you how to use the queueing information to make switches exchange information and react autonomously. In a more advanced solution you would try to learn what is the occupancy of all the alternative paths and just move flows if there is space.

## Part 7: Compare ECMP and CONGA Load Balancing in an asymmetric topology

In this section, we will use an example to see how a traffic balancer like the one you just developed could be more advantageous than a simpler approach, like ECMP.
As discussed in the CONGA paper, ECMP often incurs problems at asymmetric topologies. Therefore, we choose the following topology for our experiment:

![asym topology](images/AsymmetricTopologyDiagram.png)

We send 5 Mbps of udp traffic from `h1` to `h2`. ECMP would split the flow evenly, leading to underutilization of the upper path(through s2), and packet loss on the lower path(through s3). However, the congestion aware system should shift traffic to allow for efficient utilization of the bandwidth, for example, where 1.5 mbps is sent through s3 while 3.5 mbps is sent through s2, where the bandwidth is higher.

**Note:** Be sure to monitor your cpu utilization during this process. If the cpu utilization gets too high, scale down the bandwidths of the links and of your traffic generator. This should minimize any unexpected behavior during the test.

There are some steps you need to complete before comparing these two systems.

1. Copy over the P4 code and the routing controller code of your ECMP implementation. The routing controller needs to be modified to accommodate the new topology.

2. Modify all your P4 code such that it supports UDP. This means adding a UDP header and parser, and also hashing the UDP source port and dst port in your P4 code instead of the TCP ports.

### Testing

1. Edit the configuration file of the asymmetric topology(`topology/p4app-asym.json`) to run your ECMP code, and also your ECMP controller.

2. Start the asymmetric topology, which connects 2 hosts with two different paths, but the paths have an asymmetric distribution of bandwidth:

   ```bash
   sudo p4run --config topology/p4app-asym.json
   ```

3. Open a `tmux` terminal by typing `tmux` (or if you are already using `tmux`, open another window and type `tmux`). And run monitoring script (`nload_tmux_asym.sh`). This script, will use `tmux` to create a window
with 4 panes, in each pane it will lunch a `nload` session with a different interface. The upper two displays show the traffic from the upper path(through s2, higher bandwidth). The lower two displays show the traffic from the lower path(through s3, lower bandwidth).

   ```bash
   tmux
   ./nload_tmux_asym.sh
   ```

3. Send traffic from `h1` to `h2`. There is a script that will do that for you automatically. This script will send multiple 100 Kbps flows from h1 to h2. The first input specifies the amount of time you want the script to run(set it to something high, like 1000). The second input specifies the total bandwidth you would like to send, in mbps. You can input a float in this spot.

   ```bash
   sudo python send_traffic_asym.py 1000 5
   ```

4. If you would like to stop the traffic, kill all the traffic generators with this command:

   ```bash
   sudo killall iperf3
   ```

Next, try running the topology with your conga.p4 code and the corresponding routing controller.

In your report, please show the performance you observe between ECMP and CONGA and explain the reasons for the performance you get.

## Extra credits

### Investigate the right threshold setting (10 credits)
In Part 4 congestion notification, you can set the notification threshold as a number between 30 and 60. Now your job is to understand the impact of thresholding in the load balancing system. Start by selecting a flow that is involved in the congestion. Draw a graph with x-axis as different thresholds and y-axis as the number of notification messages you get. Next, draw a timeline of the notified congestion levels. Explain what you observe.

## Submission and Grading

### What to Submit

You are expected to submit the following documents:

1. code: The main P4 code should be in `p4src/include/headers.p4`, `p4src/include/parsers.p4`, and `p4src/conga.p4`;  The controller code should be in `controller/routing-controller.py` which fills in table entries when launching those P4 switches.

2. report/report.md: You should describe the performance difference between ECMP and the implementation in this project in `report.md`.

### Grading

The total grades is 100:

- 30: For your description for your code, and your comparison between ECMP load balancing and congestion aware load balancing in `report.md`.
- 70: We will check the correctness of your code for congestion aware load balancing.
- Deductions based on late policies

### Survey

Please fill up the survey when you finish your project.

[Survey link](https://docs.google.com/forms/d/e/1FAIpQLSeMWyivyXvUNogg5RODW1ak8C3A8w-_yw4QvAjZT9THzPTalA/viewform?usp=sf_link)
