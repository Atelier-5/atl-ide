# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""
cloud.py — linking this edge to clouds made from template-dlab5-cloud, and
calling them. Owned by the edge layer: change settings.py, not this.

The device flow of DigitalHome's edges (DH-SPEC-100, RFC 8628), as the cloud
template's docs/specs/edge-cloud-api.md profiles it:

    start_link(cloud)      POST /device_authorization → user_code + URL to show
    poll_link(pending)     POST /token until a tenant admin approves on /link
    call(path, body)       POST with the device token as a Bearer
    rotate()               POST /token/rotate, 30 days before expiry
    keep_fresh()           rotate every linked connection that is due
    tenant()               the tenant this edge was linked to, and its spaces

One edge can be linked to several clouds at once (sandbox, stage, prod),
each a CONNECTION with its own token. The device token is the only
credential: a 0600 file outside the repository (~/.config/<tool>/cloud.json,
or $<ENV>_EDGE_STATE). Standard library only.
"""

from __future__ import annotations

try:                                    # POSIX
    import fcntl
except ImportError:                     # Windows
    fcntl = None
    import msvcrt
import json
import os
import platform
import re
import socket
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from . import settings

GRANT = "urn:ietf:params:oauth:grant-type:device_code"
ROTATE_BEFORE = timedelta(days=30)
TIMEOUT_S = 30
VERSION_HEADER = "X-Edge-Version"


class CloudError(Exception):
    """A cloud answer a person can act on."""

    def __init__(self, message: str, status: int = 0, code: str = "", payload: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.payload = payload or {}


class NotLinked(CloudError):
    pass


class EdgeTooOld(CloudError):
    """The cloud accepts only edges from a minimum version on (426)."""


class NoTenant(CloudError):
    """Linked without a tenant: link again, approving it for a tenant."""


class Revoked(CloudError):
    """An admin revoked this edge (a bare 410): its token is forgotten."""


class Gone(CloudError):
    """One ITEM is gone for good (410 with the product's own error code). The
    edge is fine: never treat this as a revoke, or edges unlink themselves."""


def _version() -> str:
    from ..core.version import __version__
    return __version__


def state_path() -> Path:
    env = os.environ.get(f"{settings.ENV}_EDGE_STATE")
    return Path(env).expanduser() if env else Path.home() / ".config" / settings.TOOL / "cloud.json"


# ------------------------------------------------------------- connections --
#
#   {"current": "prod", "machine_id": "…",
#    "profiles": {"prod": {cloud, site, edge_id, device_token, tenant, …}, …}}

PROFILE: Optional[str] = None
PROFILE_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}")


def _load_file() -> Dict[str, Any]:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"profiles": {}}
    data.setdefault("profiles", {})
    return data


def _save_file(data: Dict[str, Any]) -> None:
    """Atomically, and readable by this user only."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


@contextmanager
def _locked() -> Iterator[None]:
    """One writer at a time across processes: the page and the command line
    both keep connections here, and a read-modify-write without a lock once
    let one erase the other's."""
    lock = state_path().with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if fcntl:
            fcntl.flock(fd, fcntl.LOCK_EX)
        else:
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        yield
    finally:
        if fcntl:
            fcntl.flock(fd, fcntl.LOCK_UN)
        else:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        os.close(fd)


def active_profile() -> str:
    return PROFILE or _load_file().get("current") or "default"


def check_profile(name: str) -> str:
    if not PROFILE_NAME.fullmatch(name or ""):
        raise CloudError("a connection's name is lowercase letters, digits and -, e.g. prod or stage")
    return name


def profiles() -> Dict[str, Dict[str, Any]]:
    """Every connection's public state (never the token)."""
    return {name: public_state(st, name) for name, st in sorted(_load_file()["profiles"].items())}


def linked_profiles() -> List[str]:
    return [n for n, st in _load_file()["profiles"].items() if st.get("device_token")]


def use_profile(name: str) -> None:
    with _locked():
        data = _load_file()
        if check_profile(name) not in data["profiles"]:
            raise CloudError(f"no connection {name}; link one first")
        data["current"] = name
        _save_file(data)


def load_state(profile: Optional[str] = None) -> Dict[str, Any]:
    return dict(_load_file()["profiles"].get(profile or active_profile(), {}))


def update_state(changes: Dict[str, Any], profile: Optional[str] = None, drop: tuple = ()) -> Dict[str, Any]:
    """Change some fields of one connection, under the lock, leaving every
    other connection exactly as it is on disk now."""
    with _locked():
        data = _load_file()
        name = profile or active_profile()
        state = {k: v for k, v in {**data["profiles"].get(name, {}), **changes}.items() if k not in drop}
        data["profiles"][name] = state
        data["current"] = data.get("current") or name
        _save_file(data)
        return state


def forget(profile: Optional[str] = None) -> None:
    """Drop one connection (its token), keeping the others. An admin revokes
    the edge itself in that cloud's Settings → Edges."""
    with _locked():
        data = _load_file()
        name = profile or active_profile()
        data["profiles"].pop(name, None)
        if data.get("current") == name:
            data["current"] = next(iter(data["profiles"]), None)
        _save_file(data)


def public_state(state: Optional[Dict[str, Any]] = None, name: Optional[str] = None) -> Dict[str, Any]:
    """A connection's state without the token, for pages and agents."""
    if state is None:
        name = name or active_profile()
        state = load_state(name)
    t = state.get("tenant") or {}
    return {"profile": name, "linked": bool(state.get("device_token")), "cloud": state.get("cloud"),
            "site": state.get("site"), "edge_id": state.get("edge_id"), "linked_at": state.get("linked_at"),
            "token_expires": state.get("token_expires"), "last_telemetry_at": state.get("last_telemetry_at"),
            "tenant": t.get("tenant"), "spaces": t.get("spaces") or [],
            "no_tenant": bool(state.get("no_tenant")), "rotate_error": state.get("rotate_error")}


def base_url(cloud: str) -> str:
    """Accept the API root or the /edge/v1 base, with or without a slash."""
    cloud = cloud.strip().rstrip("/")
    if not cloud.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise CloudError("the cloud address must be https:// (plain http only for localhost)")
    return cloud if cloud.endswith("/edge/v1") else f"{cloud}/edge/v1"


def _post(url: str, body: Dict[str, Any], token: Optional[str] = None) -> tuple[int, Dict[str, Any]]:
    # every call names this edge's version: a cloud refuses edges older than
    # its minimum (426), so an edge without the latest fixes cannot work
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          VERSION_HEADER: _version()})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        try:
            payload = json.loads(err.read() or b"{}")
        except ValueError:
            payload = {}
        if err.code == 426:
            need = payload.get("min_version") or "a newer version"
            raise EdgeTooOld(f"{settings.CLOUD_NAME} needs edge {need} or newer (this is {_version()}); update the edge",
                             426, "edge_too_old", payload)
        return err.code, payload
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise CloudError(f"cannot reach {url}: {getattr(err, 'reason', err)}")


# ------------------------------------------------------------------ device --

def machine_id() -> str:
    """/etc/machine-id, as digitalhome-edge sends it; else a UUID kept with the state."""
    try:
        mid = Path("/etc/machine-id").read_text().strip()
        if mid:
            return mid
    except OSError:
        pass
    with _locked():
        data = _load_file()
        if not data.get("machine_id"):
            data["machine_id"] = uuid.uuid4().hex
            _save_file(data)
        return data["machine_id"]


def lan_ip() -> Optional[str]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))      # TEST-NET: no packet is sent for a UDP connect
            return s.getsockname()[0]
    except OSError:
        return None


def device_info() -> Dict[str, Any]:
    # dhe_version keeps DH-SPEC-100's field name; it carries this tool's version
    return {"machine_id": machine_id(), "hostname": socket.gethostname(), "lan_ip": lan_ip(),
            "dhe_version": f"{settings.TOOL} {_version()}"}


# -------------------------------------------------------------------- link --

def start_link(cloud: str) -> Dict[str, Any]:
    """Ask for a pairing code. Returns what to show a person, plus the secret
    device_code the poll needs (never show that one)."""
    base = base_url(cloud)
    status, body = _post(f"{base}/device_authorization",
                         {"client_id": settings.CLIENT_ID, "scope": settings.SCOPE, "device_info": device_info()})
    if status != 200 or "device_code" not in body:
        raise CloudError(f"device_authorization failed ({status}): {body.get('error', body)}", status)
    # the connection this pairing is for is fixed now, whatever becomes
    # current while an admin takes their time approving it
    return {"cloud": base, "profile": active_profile(), **body, "started": time.time()}


def poll_link(pending: Dict[str, Any], sleep: Callable[[float], None] = time.sleep,
              cancelled: Callable[[], bool] = lambda: False,
              on_wait: Callable[[str], None] = lambda s: None) -> Dict[str, Any]:
    """Poll /token until approved, denied or expired. Saves and returns the state."""
    interval = int(pending.get("interval", 5))
    deadline = pending["started"] + int(pending.get("expires_in", 600))
    while time.time() < deadline:
        if cancelled():
            raise CloudError("pairing cancelled")
        sleep(interval)
        status, body = _post(f"{pending['cloud']}/token", {
            "grant_type": GRANT, "device_code": pending["device_code"], "client_id": settings.CLIENT_ID})
        if status == 200 and body.get("access_token"):
            site = str(pending.get("verification_uri") or "").rsplit("/link", 1)[0] or None
            name = pending.get("profile") or active_profile()
            state = update_state({"cloud": pending["cloud"], "site": site, "edge_id": body.get("edge_id"),
                                  "device_token": body["access_token"],
                                  "token_expires": _expiry(body.get("expires_in")),
                                  "linked_at": _now()}, name, drop=("rotate_error", "rotate_failed_at"))
            try:
                telemetry(kind="full", profile=name)
            except CloudError:
                pass                              # linked is linked; telemetry retries later
            try:
                tenant(name, refresh=True)        # the tenant it was approved for
                state = load_state(name)
            except CloudError:
                update_state({}, name, drop=("tenant",))
            return public_state(state, name)
        error = body.get("error")
        if error == "authorization_pending":
            on_wait("waiting for approval")
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "access_denied":
            raise CloudError("the pairing was denied on /link", status, error)
        if error == "expired_token":
            raise CloudError("the pairing code expired; start again", status, error)
        raise CloudError(f"token failed ({status}): {error or body}", status, error or "")
    raise CloudError("the pairing code expired; start again", 400, "expired_token")


# ----------------------------------------------------------- authenticated --

def call(path: str, body: Dict[str, Any], profile: Optional[str] = None) -> Dict[str, Any]:
    """POST to /edge/v1/<path> as this edge on one connection (default: the
    current one)."""
    name = profile or active_profile()
    state = load_state(name)
    if not state.get("device_token"):
        raise NotLinked(f"{name} is not linked")
    if _due_for_rotation(state):
        rotate(name)                              # records its own failure; the old token still works
        state = load_state(name)
    status, payload = _post(f"{state['cloud']}/{path.lstrip('/')}", body, state["device_token"])
    if status == 200:
        return payload
    error = str(payload.get("error") or "")
    if status == 410 and error and error != "revoked":
        # one item is gone for good: the edge itself is fine
        raise Gone(f"{path}: {payload.get('message') or error}", status, error, payload)
    if status == 410:
        update_state({}, name, drop=("device_token", "edge_id", "token_expires"))
        raise Revoked(f"an admin revoked this edge on {name}; link it again", status, "revoked")
    if status == 401:
        raise NotLinked(f"{name} no longer accepts this edge's token; link it again", status, "invalid_token")
    if status == 403 and error == "no_tenant":
        update_state({"no_tenant": True}, name)
        raise NoTenant(f"{name}: this edge belongs to no {settings.TENANT_NOUN}; link it again and choose one",
                       status, error, payload)
    raise CloudError(f"{path} failed ({status}): {payload.get('message') or error or payload}", status, error, payload)


def rotate(profile: Optional[str] = None) -> bool:
    """A new token for this connection; True when it worked.

    A failure is recorded on the connection (`rotate_error`, shown on the page)
    instead of being swallowed: the old token keeps working until it expires,
    so nothing breaks now, but somebody has to know before it does.
    """
    name = profile or active_profile()
    state = load_state(name)
    try:
        status, body = _post(f"{state['cloud']}/token/rotate", {}, state["device_token"])
    except EdgeTooOld:
        update_state({"rotate_error": "this edge is too old: update it", "rotate_failed_at": _now()}, name)
        raise
    except CloudError as exc:                 # offline: try again on the next check
        update_state({"rotate_error": str(exc)[:200], "rotate_failed_at": _now()}, name)
        return False
    if status == 200 and body.get("access_token"):
        update_state({"device_token": body["access_token"], "token_expires": _expiry(body.get("expires_in"))},
                     name, drop=("rotate_error", "rotate_failed_at"))
        return True
    update_state({"rotate_error": f"renewing the token failed ({status}: {body.get('error') or body})"[:200],
                  "rotate_failed_at": _now()}, name)
    return False


def keep_fresh(now: Optional[datetime] = None) -> Dict[str, str]:
    """Renew every linked connection's token that is due, whether or not the
    edge is in use (routes.start_keeper runs it at start and twice a day).
    Returns {connection: "renewed" | "failed" | "expired"} for those it touched."""
    out: Dict[str, str] = {}
    for name in linked_profiles():
        state = load_state(name)
        if _expired(state, now):
            update_state({"rotate_error": "the token expired: link this connection again",
                          "rotate_failed_at": _now()}, name)
            out[name] = "expired"
        elif _due_for_rotation(state, now):
            try:
                out[name] = "renewed" if rotate(name) else "failed"
            except CloudError:
                out[name] = "failed"
    return out


def telemetry(kind: str = "delta", extra: Optional[Dict[str, Any]] = None,
              profile: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"protocol_version": 1, "kind": kind, "client_timestamp": _now()}
    if kind == "full":
        body.update(edge={"machine_id": machine_id(), "hostname": socket.gethostname(), "lan_ip": lan_ip()},
                    software={"dhe_version": f"{settings.TOOL} {_version()}", "os": platform.platform(),
                              "arch": platform.machine()})
    body.update(extra or {})
    answer = call("telemetry", body, profile)
    update_state({"last_telemetry_at": _now()}, profile)
    return answer


# ----------------------------------------------------------- tenant, spaces --

def tenant(profile: Optional[str] = None, refresh: bool = False) -> Dict[str, Any]:
    """{"tenant": {id, name}, "spaces": [{id, name, kind}]} for a connection, cached."""
    name = profile or active_profile()
    state = load_state(name)
    if state.get("tenant") and not refresh:
        return state["tenant"]
    got = call("tenant", {}, name)
    t = {"tenant": got.get("tenant"), "spaces": got.get("spaces") or []}
    update_state({"tenant": t}, name, drop=("no_tenant",))
    return t


def space_slug(space_name: Optional[str]) -> str:
    """A local name for a space's A-Box: spaces are known here by NAME, because
    their ids differ between clouds (stage and prod)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (space_name or "shared").lower()).strip("-")[:40] or "shared"
    return slug if slug[0].isalpha() else f"s-{slug}"[:40]


def space_by_slug(slug: str, profile: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The connection's space whose name gives this slug (its shared space for "shared")."""
    spaces = tenant(profile).get("spaces") or []
    for s in spaces:
        if space_slug(s.get("name")) == slug:
            return s
    if slug == "shared":
        return next((s for s in spaces if s.get("kind") == "shared"), None)
    return None


# ------------------------------------------------------------------- times --

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _expiry(seconds: Any) -> Optional[str]:
    if not isinstance(seconds, (int, float)):
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()


def _expires(state: Dict[str, Any]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(state["token_expires"])
    except (KeyError, TypeError, ValueError):
        return None


def _due_for_rotation(state: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    expires = _expires(state)
    return expires is not None and expires - (now or datetime.now(timezone.utc)) < ROTATE_BEFORE


def _expired(state: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    expires = _expires(state)
    return expires is not None and expires <= (now or datetime.now(timezone.utc))
