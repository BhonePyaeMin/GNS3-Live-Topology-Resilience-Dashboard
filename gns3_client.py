"""Tiny GNS3 REST client shared by app.py and setup_lab.py."""
import configparser
import glob
import os

import requests


def load_local_credentials():
    """Return (user, password) that the GNS3 GUI generated for its local server.

    Reads the GUI's own server config on this machine, so nothing needs to be
    typed or stored anywhere else. Returns ("", "") if auth is off or no config
    is found.
    """
    patterns = [os.path.expanduser("~/.config/GNS3/*/gns3_server.conf")]
    if os.environ.get("APPDATA"):
        patterns.insert(0, os.path.join(os.environ["APPDATA"], "GNS3", "*", "gns3_server.ini"))

    for pattern in patterns:
        for path in sorted(glob.glob(pattern), reverse=True):
            cfg = configparser.ConfigParser()
            cfg.read(path)
            if cfg.has_section("Server") and cfg.getboolean("Server", "auth", fallback=False):
                return cfg.get("Server", "user", fallback=""), cfg.get("Server", "password", fallback="")
    return "", ""


def add_connection_args(parser):
    parser.add_argument("--host", default="127.0.0.1", help="GNS3 server host")
    parser.add_argument("--port", type=int, default=3080, help="GNS3 server API port")
    parser.add_argument("--user", default=os.environ.get("GNS3_USER", ""),
                        help="GNS3 server username (env: GNS3_USER); needed when 'Protect server with password' is on")
    parser.add_argument("--password", default=os.environ.get("GNS3_PASSWORD", ""),
                        help="GNS3 server password (env: GNS3_PASSWORD)")
    parser.add_argument("--from-gns3-config", action="store_true",
                        help="read user/password from the local GNS3 GUI config instead of --user/--password")


def client_from_args(args):
    user, password = args.user, args.password
    if args.from_gns3_config and not user:
        user, password = load_local_credentials()
    return Gns3(args.host, args.port, user, password)


class Gns3:
    def __init__(self, host, port, user="", password=""):
        self.base = f"http://{host}:{port}/v2"
        self.auth = (user, password) if user else None

    def _request(self, method, path, body=None):
        r = requests.request(method, self.base + path, json=body, auth=self.auth, timeout=10)
        if r.status_code == 401:
            raise RuntimeError("GNS3 rejected the credentials (HTTP 401) -- check --user / --password")
        if not r.ok:
            try:
                detail = r.json().get("message", r.text)
            except ValueError:
                detail = r.text
            raise RuntimeError(f"GNS3 {method} {path} -> HTTP {r.status_code}: {detail}")
        return r.json() if r.content else None

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, body=None):
        return self._request("POST", path, body if body is not None else {})

    def delete(self, path):
        return self._request("DELETE", path)
