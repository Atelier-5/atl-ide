# SPDX-License-Identifier: GPL-3.0-or-later
"""The edge layer's cloud link: what goes on the wire, what a status means,
and that tokens are renewed whether or not the edge is in use."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from atl.edge import cloud

NOW = datetime(2027, 9, 10, tzinfo=timezone.utc)


@pytest.fixture
def linked(tmp_path, monkeypatch):
    """Two connections: stage's token is due (20 days left), prod's is not."""
    monkeypatch.setenv("ATL_IDE_EDGE_STATE", str(tmp_path / "cloud.json"))
    for name, days in (("stage", 20), ("prod", 200)):
        cloud.update_state({"cloud": f"https://{name}.example/edge/v1", "device_token": f"dt_v1_{name}.old",
                            "token_expires": (NOW + timedelta(days=days)).isoformat()}, name)
    cloud.use_profile("prod")
    return monkeypatch


def answering(status, body, calls=None):
    def post(url, body_, token=None):
        if calls is not None:
            calls.append((url, body_, token))
        if isinstance(status, Exception):
            raise status
        return status, body
    return post


def test_every_call_names_the_version_and_426_means_update(monkeypatch):
    import io
    import urllib.error
    import urllib.request
    seen = {}

    def urlopen(req, timeout=None):
        seen.update(dict(req.header_items()))
        raise urllib.error.HTTPError(req.full_url, 426, "too old", {}, io.BytesIO(b'{"error":"edge_too_old","min_version":"9.0.0"}'))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(cloud.EdgeTooOld, match="9.0.0"):
        cloud._post("https://x.example/edge/v1/telemetry", {})
    assert "X-edge-version" in seen or "X-Edge-Version" in seen


def test_the_state_file_is_owner_only_and_holds_no_token_in_public(linked, tmp_path):
    assert oct((tmp_path / "cloud.json").stat().st_mode & 0o777) == "0o600"
    assert "device_token" not in str(cloud.profiles())


def test_a_bare_410_is_a_revoke_but_410_with_a_code_is_one_item_gone(linked):
    linked.setattr(cloud, "_post", answering(410, {"error": "deleted_for_good", "message": "gone"}))
    with pytest.raises(cloud.Gone):
        cloud.call("items/x", {})
    assert cloud.load_state("prod")["device_token"]          # still linked
    linked.setattr(cloud, "_post", answering(410, {}))
    with pytest.raises(cloud.Revoked):
        cloud.call("items/x", {})
    assert "device_token" not in cloud.load_state("prod")


def test_no_tenant_says_link_again(linked):
    linked.setattr(cloud, "_post", answering(403, {"error": "no_tenant"}))
    with pytest.raises(cloud.NoTenant):
        cloud.call("graphs/list", {})
    assert cloud.public_state(name="prod")["no_tenant"] is True


def test_only_the_due_connection_is_renewed(linked):
    calls = []
    linked.setattr(cloud, "_post", answering(200, {"access_token": "dt_v1_stage.new", "expires_in": 3600}, calls))
    assert cloud.keep_fresh(NOW) == {"stage": "renewed"}
    assert calls[0][0] == "https://stage.example/edge/v1/token/rotate"
    assert cloud.load_state("stage")["device_token"] == "dt_v1_stage.new"
    assert cloud.load_state("prod")["device_token"] == "dt_v1_prod.old"


def test_a_failed_renewal_is_recorded_kept_and_cleared_by_the_next_success(linked):
    linked.setattr(cloud, "_post", answering(500, {"error": "server_error"}))
    assert cloud.keep_fresh(NOW) == {"stage": "failed"}
    assert cloud.load_state("stage")["device_token"] == "dt_v1_stage.old"
    assert "500" in cloud.public_state(name="stage")["rotate_error"]
    linked.setattr(cloud, "_post", answering(cloud.CloudError("cannot reach it"), None))
    assert cloud.keep_fresh(NOW) == {"stage": "failed"}
    linked.setattr(cloud, "_post", answering(200, {"access_token": "dt_v1_stage.new", "expires_in": 3600}))
    cloud.keep_fresh(NOW)
    assert cloud.public_state(name="stage")["rotate_error"] is None


def test_an_expired_token_is_not_sent_but_reported(linked):
    calls = []
    linked.setattr(cloud, "_post", answering(200, {}, calls))
    assert cloud.keep_fresh(NOW + timedelta(days=30)) == {"stage": "expired"}
    assert calls == []


def test_spaces_are_matched_by_name_not_id(linked):
    cloud.update_state({"tenant": {"tenant": {"id": "t-1", "name": "Workshop"},
                                   "spaces": [{"id": "s-aaa", "name": "Everyone", "kind": "shared"},
                                              {"id": "s-bbb", "name": "Team only", "kind": "private"}]}}, "prod")
    assert cloud.space_by_slug("team-only", "prod")["id"] == "s-bbb"
    assert cloud.space_by_slug("shared", "prod")["id"] == "s-aaa"
    assert cloud.space_by_slug("nothing", "prod") is None
