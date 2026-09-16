#!/usr/bin/env python3
"""Initial SDN-IoT topology: one broker, one sink, and N IoT publishers."""

import argparse

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.topo import Topo


class IoTTopology(Topo):
    def build(self, devices=5):
        switch = self.addSwitch("s1", dpid="0000000000000001")
        broker = self.addHost("broker", ip="10.0.0.250/24")
        sink = self.addHost("sink", ip="10.0.0.251/24")
        self.addLink(broker, switch, bw=100, delay="1ms")
        self.addLink(sink, switch, bw=100, delay="1ms")
        for index in range(1, devices + 1):
            host = self.addHost(f"iot{index}", ip=f"10.0.0.{index}/24")
            self.addLink(host, switch, bw=20, delay="2ms")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--devices", type=int, choices=(5, 10, 20), default=5)
    args = parser.parse_args()

    topo = IoTTopology(devices=args.devices)
    controller = RemoteController("c0", ip="127.0.0.1", port=6653)
    net = Mininet(topo=topo, controller=None, switch=OVSSwitch, link=TCLink, autoSetMacs=True)
    net.addController(controller)
    net.start()
    print(f"SDN-IoT topology started with {args.devices} publishers.")
    print("Run: pingall")
    CLI(net)
    net.stop()


if __name__ == "__main__":
    main()

