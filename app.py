#!/usr/bin/env python3
"""
GNS3 Live Topology & Resilience Dashboard
--------------------------------------
Connects to the GNS3 server's REST API, pulls the current topology
(nodes + links) for a running project, and serves a live web page
showing the topology as an interactive graph. Node color reflects
whether the device is started or stopped, and "critical links" (links
whose failure would split the network into two disconnected pieces)
are highlighted automatically using basic graph theory (bridge edges).

No packet capture, no extra GNS3 nodes needed -- this just talks to
the GNS3 application's own API, so it works with any topology you
already have open.

Usage:
    python app.py --project "My Lab" --from-gns3-config
    python app.py --project "My Lab" --user admin --password SECRET

Then open http://localhost:3500 in a browser.
"""
import argparse
import threading
import time
from collections import Counter

import networkx as nx
import requests
from flask import Flask, jsonify, render_template_string

from gns3_client import add_connection_args, client_from_args

app = Flask(__name__)

STATE = {"nodes": [], "links": [], "critical_links": [], "project": None, "error": None}
ARGS = None
GNS3 = None


def gns3_api(path):
    return GNS3.get(path)


def find_project():
    projects = gns3_api("/projects")
    if ARGS.project:
        for p in projects:
            if p["name"] == ARGS.project:
                if p["status"] != "opened":
                    raise RuntimeError(f'Project "{ARGS.project}" exists but is not open in the GNS3 GUI')
                return p
        raise RuntimeError(f'No project named "{ARGS.project}" -- check the name matches the GNS3 title bar')
    # no name given: fall back to the first opened project
    for p in projects:
        if p["status"] == "opened":
            return p
    raise RuntimeError("No opened GNS3 project found -- open one in the GNS3 GUI first")


def find_critical_links(nodes, links):
    """Return the set of link_ids whose loss would disconnect the topology.

    Parallel links between the same two nodes are redundant with each
    other, so they are never critical. networkx collapses parallel edges
    into one, so we count multiplicity ourselves: a bridge in the
    collapsed graph is only a real single point of failure if exactly one
    physical link backs it.
    """
    g = nx.Graph()
    for n in nodes:
        g.add_node(n["node_id"])

    pair_links = {}
    for l in links:
        endpoints = [n["node_id"] for n in l["nodes"]]
        if len(endpoints) != 2 or endpoints[0] == endpoints[1]:
            continue
        pair = frozenset(endpoints)
        pair_links.setdefault(pair, []).append(l["link_id"])
        g.add_edge(*endpoints)

    multiplicity = Counter({pair: len(ids) for pair, ids in pair_links.items()})

    critical = set()
    for a, b in nx.bridges(g):
        pair = frozenset((a, b))
        if multiplicity[pair] == 1:
            critical.add(pair_links[pair][0])
    return critical


def poll_loop():
    while True:
        try:
            project = find_project()
            nodes = gns3_api(f"/projects/{project['project_id']}/nodes")
            links = gns3_api(f"/projects/{project['project_id']}/links")

            # compute first, then publish in one step so a request can never see
            # new nodes paired with old critical-link results
            critical = sorted(find_critical_links(nodes, links))
            STATE.update(project=project["name"], nodes=nodes, links=links,
                         critical_links=critical, error=None)
        except requests.ConnectionError:
            STATE["error"] = f"Cannot reach GNS3 at {ARGS.host}:{ARGS.port} -- is GNS3 running?"
        except Exception as e:
            STATE["error"] = str(e)

        time.sleep(3)


PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>GNS3 Topology Resilience Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.6/standalone/umd/vis-network.min.js"></script>
<style>
  body { font-family: system-ui, sans-serif; background:#0f1115; color:#e6e6e6; margin:0; padding:20px; }
  h1 { font-size:20px; margin:0 0 4px; }
  #sub { font-size:13px; color:#9aa0a6; margin-bottom:12px; }
  #network { width:100%; height:70vh; background:#1a1d24; border-radius:10px; }
  .legend { margin-top:12px; font-size:13px; color:#9aa0a6; }
  .dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin:0 6px 0 12px; }
  #summary { margin-top:10px; font-size:14px; }
  #err { color:#ff6b6b; margin-top:10px; }
</style>
</head>
<body>
  <h1>GNS3 Live Topology &amp; Resilience Dashboard</h1>
  <div id="sub">project: <span id="proj">-</span></div>
  <div id="network"></div>
  <div class="legend">
    <span class="dot" style="background:#4caf50; margin-left:0"></span> started
    <span class="dot" style="background:#f44336"></span> stopped
    &nbsp;&nbsp; red dashed line = critical link (single point of failure)
  </div>
  <div id="summary"></div>
  <div id="err"></div>

<script>
const container = document.getElementById('network');
const nodeSet = new vis.DataSet([]);
const edgeSet = new vis.DataSet([]);
const options = {
  nodes: { shape: 'box', font: { color: '#fff' }, margin: 10 },
  edges: { color: '#5b8def', width: 2, smooth: false },
  physics: false   // node positions come from the GNS3 canvas, so this mirrors your lab
};
const network = new vis.Network(container, { nodes: nodeSet, edges: edgeSet }, options);

// Re-center whenever the set of nodes changes (first load, node added/removed),
// but not on every poll, so the user's own pan/zoom isn't fought.
let knownNodes = '';
function fitIfNodesChanged() {
  const ids = nodeSet.getIds().sort().join();
  if (ids !== knownNodes) {
    knownNodes = ids;
    network.fit();
  }
}

// Only push a node's GNS3 position when it changes in GNS3, so dragging a box
// in the browser isn't snapped back on every poll.
const lastPos = {};

// Update in place (instead of clear + add) so the layout doesn't jump every poll.
function sync(dataset, items) {
  const keep = new Set(items.map(i => i.id));
  dataset.remove(dataset.getIds().filter(id => !keep.has(id)));
  dataset.update(items);
}

async function poll() {
  try {
    const res = await fetch('/api/topology');
    const state = await res.json();

    // On error the graph below is the last known state, not live: dim it and say so.
    container.style.opacity = state.error ? 0.35 : 1;
    document.getElementById('summary').style.opacity = state.error ? 0.35 : 1;
    document.getElementById('err').innerText = state.error
      ? ('Error: ' + state.error + (state.nodes.length ? ' (graph below is the last known state, not live)' : ''))
      : '';
    document.getElementById('proj').innerText = state.project || '-';

    const nodes = state.nodes.map(n => {
      const item = {
        id: n.node_id,
        label: n.name,
        color: n.status === 'started' ? '#4caf50' : '#f44336'
      };
      const pos = n.x + ',' + n.y;
      if (lastPos[n.node_id] !== pos) {
        lastPos[n.node_id] = pos;
        item.x = n.x;
        item.y = n.y;
      }
      return item;
    });

    const critical = new Set(state.critical_links);
    const twoEnded = state.links.filter(l => l.nodes.length === 2);
    // Parallel cables between the same two nodes get opposite curves so both stay visible.
    const pairKey = l => l.nodes.map(x => x.node_id).sort().join('|');
    const pairTotal = {}, pairSeen = {};
    twoEnded.forEach(l => { pairTotal[pairKey(l)] = (pairTotal[pairKey(l)] || 0) + 1; });
    const edges = twoEnded.map(l => {
      const key = pairKey(l);
      const i = pairSeen[key] = (pairSeen[key] === undefined ? 0 : pairSeen[key] + 1);
      const [from, to] = key.split('|');
      const isCrit = critical.has(l.link_id);
      return {
        id: l.link_id,
        from, to,
        color: isCrit ? '#ff4d4f' : '#5b8def',
        dashes: isCrit,
        width: isCrit ? 3 : 2,
        smooth: pairTotal[key] === 1 ? false
          : { enabled: true, type: i % 2 === 0 ? 'curvedCW' : 'curvedCCW', roundness: 0.25 + 0.2 * Math.floor(i / 2) }
      };
    });

    sync(nodeSet, nodes);
    sync(edgeSet, edges);
    fitIfNodesChanged();

    const up = state.nodes.filter(n => n.status === 'started').length;
    document.getElementById('summary').innerText =
      `${up}/${state.nodes.length} nodes started, ${state.links.length} links, ${critical.size} critical`;
  } catch (e) {
    container.style.opacity = 0.35;
    document.getElementById('summary').style.opacity = 0.35;
    document.getElementById('err').innerText = 'Dashboard backend unreachable (graph is stale): ' + e;
  }
}
setInterval(poll, 3000);
poll();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/api/topology")
def api_topology():
    return jsonify(STATE)


def main():
    global ARGS, GNS3
    parser = argparse.ArgumentParser()
    add_connection_args(parser)
    parser.add_argument("--project", default="", help="GNS3 project name to watch (default: first opened project)")
    # GNS3 hands out console ports from 5000-10000 (Preferences > Server), so the
    # dashboard must stay outside that range or it can steal a node's port.
    parser.add_argument("--web-port", type=int, default=3500, help="dashboard port (keep outside 5000-10000)")
    ARGS = parser.parse_args()
    GNS3 = client_from_args(ARGS)

    threading.Thread(target=poll_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=ARGS.web_port)


if __name__ == "__main__":
    main()
