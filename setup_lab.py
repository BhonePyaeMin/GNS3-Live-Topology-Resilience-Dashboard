#!/usr/bin/env python3
"""
Build the demo lab for the dashboard through the GNS3 REST API.

    PC1 --- SW1 ===(2 parallel trunks)=== SW2 --- PC2

Uses only built-in node types (VPCS + Ethernet switch), so no images are needed.

Usage:
    python setup_lab.py --from-gns3-config
"""
import argparse

from gns3_client import add_connection_args, client_from_args


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_connection_args(parser)
    parser.add_argument("--project", default="CriticalLinkDemo", help="name of the project to create")
    args = parser.parse_args()
    gns3 = client_from_args(args)

    if any(p["name"] == args.project for p in gns3.get("/projects")):
        raise SystemExit(f'Project "{args.project}" already exists -- delete it in GNS3 or pass another --project name')

    pid = gns3.post("/projects", {"name": args.project})["project_id"]

    def add_node(name, node_type, x, y):
        body = {"name": name, "node_type": node_type, "compute_id": "local", "x": x, "y": y}
        return gns3.post(f"/projects/{pid}/nodes", body)["node_id"]

    def add_link(a, a_port, b, b_port):
        gns3.post(f"/projects/{pid}/links", {"nodes": [
            {"node_id": a, "adapter_number": 0, "port_number": a_port},
            {"node_id": b, "adapter_number": 0, "port_number": b_port},
        ]})

    pc1 = add_node("PC1", "vpcs", -250, 0)
    pc2 = add_node("PC2", "vpcs", 250, 0)
    sw1 = add_node("Switch1", "ethernet_switch", -80, 0)
    sw2 = add_node("Switch2", "ethernet_switch", 80, 0)

    add_link(pc1, 0, sw1, 0)
    add_link(pc2, 0, sw2, 0)
    add_link(sw1, 1, sw2, 1)  # link A
    add_link(sw1, 2, sw2, 2)  # link B (redundant path)

    gns3.post(f"/projects/{pid}/nodes/start")
    print(f'Created and started project "{args.project}" ({pid})')
    print("In the GNS3 GUI: File > Open project to see it. Do not ping PC1<->PC2 (L2 loop, no spanning tree).")


if __name__ == "__main__":
    main()
