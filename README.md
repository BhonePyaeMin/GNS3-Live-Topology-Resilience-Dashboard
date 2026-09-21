# GNS3 Live Topology & Resilience Dashboard

Talks directly to GNS3's REST API (no extra GNS3 nodes, no packet
sniffing) and shows your lab's topology in a live, auto-refreshing web
page: node status (started/stopped) in color, and single-point-of-failure
links highlighted automatically using graph theory (bridge edges).

## Quick start

GNS3 must be running (the GUI starts the local server on port 3080).

```powershell
pip install -r requirements.txt
python setup_lab.py --from-gns3-config                        # builds + starts the demo lab
python app.py --project CriticalLinkDemo --from-gns3-config   # dashboard
```

Open http://localhost:3500. To see the lab in the GNS3 GUI: `File > Open project`.

### About credentials

"Protect server with password" is on in GNS3, so the API needs a login. The
GUI generated one for you (user `admin`) and stores it in
`%APPDATA%\GNS3\2.2\gns3_server.ini`. `--from-gns3-config` reads it from
there, so you never need to know or type it. Alternatives:

- `--user admin --password ...`
- environment variables `GNS3_USER` / `GNS3_PASSWORD`

Use `--host 127.0.0.1 --port 3080` (the default: the local server). The GNS3
VM address (e.g. `192.168.217.128`) is a compute node the local server drives,
not the endpoint for this dashboard.

## The demo lab

`setup_lab.py` creates project `CriticalLinkDemo` with built-in nodes only
(no images needed):

```
PC1 --- Switch1 ===(two parallel trunks)=== Switch2 --- PC2
```

Don't ping PC1<->PC2 while both trunks are up: the built-in switches don't
run spanning tree, so it's an L2 loop.

You can also build it by hand in the GUI: 2x VPCS, 2x Ethernet switch, wire
PC1-Switch1, PC2-Switch2 and Switch1-Switch2 twice on different ports, then
Start all nodes.

## What you should see

| State | Switch1--Switch2 | PC access links |
|---|---|---|
| Two trunk links | blue (redundant) | red dashed |
| One trunk link (delete one in GNS3) | red dashed | red dashed |
| Second link re-added | blue again | red dashed |

The PC access links are always red dashed: each PC has a single cable, so
that cable really is a single point of failure for that PC. The demo is the
trunk going blue -> red -> blue, within 3-6 seconds of each change (the
server polls GNS3 every 3 s and the page polls the server every 3 s). The
footer shows `nodes started / links / critical` counts, and a stopped node
turns red. In this lab only the PCs can turn red: GNS3's built-in Ethernet
switches have no off state and always report `started`.

## Troubleshooting

- **Graph is dimmed with a red message under it**: the dashboard lost contact
  (with GNS3, or with its own server). The picture is the last known state, not
  live. It clears by itself when the connection returns; no page reload needed.

- **`GNS3 rejected the credentials (HTTP 401)`**: wrong login; use
  `--from-gns3-config`.
- **`Cannot reach GNS3`**: GNS3 isn't running, or wrong `--host`/`--port`.
- **`No project named ...`**: `--project` must match the project name exactly
  (or omit it to use the first open project). The project must be open.
- **Node shows red / won't start with `error while attempting to bind`**:
  something else holds one of the node's ports. GNS3 uses TCP 5000-10000 for
  consoles, so never run other tools in that range (the dashboard defaults to
  3500 for this reason). Don't kill `vpcs.exe` by hand: on Windows each VPCS is
  a launcher + child process and killing only one leaves GNS3 out of sync.
  Stop nodes from GNS3, or close and reopen the project to reset it.
- **Port 3500 in use**: pass `--web-port 4000` (keep it outside 5000-10000).

## How it works

- `gns3_client.py`: small REST client + credential loading, shared by both scripts.
- `app.py` polls `GET /v2/projects`, `/v2/projects/{id}/nodes` and `/links`
  every 3 s and builds a `networkx` graph.
- It runs `nx.bridges()`. networkx collapses parallel edges, so multiplicity is
  counted separately: a bridge is only critical if exactly one physical link
  backs it.
- The page (`vis-network` from a CDN) polls `/api/topology` and updates in
  place. Boxes are drawn at the same positions as on the GNS3 canvas, so move
  a device in GNS3 and it moves here; parallel cables curve in opposite
  directions so both stay visible.
- The dashboard binds to `127.0.0.1` only (it has no authentication of its own).
- `setup_lab.py` creates the project, nodes and links with `POST` calls.

## Files

- `app.py` -- polls the API, computes critical links, serves the dashboard.
- `gns3_client.py` -- GNS3 API client and credential helper.
- `setup_lab.py` -- builds the demo lab through the API.
- `requirements.txt` -- Python dependencies.
- `GNS3_Live_Topology_Resilience_Dashboard_Report.pdf` -- project report with
  architecture, results and validation.
