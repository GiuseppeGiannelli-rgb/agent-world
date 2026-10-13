import json

import pytest

from backend.app import ROOT


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    d = tmp_path / "config"
    d.mkdir()
    (d / "default.json").write_text(
        json.dumps(
            {
                "server": {"host": "127.0.0.1", "port": 4300},
                "limits": {"maxParallel": 8},
                "pacing": {"fetchMs": 2600},
                "router": {"defaultCombo": "fast"},
                "providers": {"mock": {"kind": "mock", "latencyMs": [600, 1600]}},
                "combos": {"fast": {"strategy": "fallback", "models": ["mock/mock-any"]}},
                "media": {"image": ["mock/mock"]},
                "skills": {"sources": ["skills"]},
                "ceo": {"id": "ada", "name": "Ada"},
                "teams": {
                    "research": {"lead": {"id": "rino", "name": "Rino"}, "workers": [{"id": "sara", "name": "Sara"}]},
                    "dev": {"lead": {"id": "leo", "name": "Leo"}, "workers": []},
                },
            }
        )
    )
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("AGENT_WORLD_ALLOW_SHELL", raising=False)
    monkeypatch.delenv("AGENT_WORLD_FAST", raising=False)
    return d


def test_real_default_json_loads_and_derives_staff():
    from backend.config import Config

    cfg = Config(ROOT / "config")
    v = cfg.get()
    assert v["ceo"]["id"] == "ada"
    staff_ids = [s["id"] for s in v["staff"]]
    assert staff_ids[0] == "ada"
    assert "rino" in staff_ids and "sara" in staff_ids
    assert v["staff"][0]["kind"] == "ceo"


def test_merge_is_deep_and_arrays_overwrite(config_dir):
    from backend.config import Config

    (config_dir / "local.json").write_text(json.dumps({"limits": {"maxParallel": 2}}))
    cfg = Config(config_dir)
    v = cfg.get()
    assert v["limits"]["maxParallel"] == 2
    assert v["pacing"]["fetchMs"] == 2600  # untouched section survives the merge


def test_env_overrides(config_dir, monkeypatch):
    from backend.config import Config

    monkeypatch.setenv("PORT", "9999")
    monkeypatch.setenv("AGENT_WORLD_ALLOW_SHELL", "1")
    monkeypatch.setenv("AGENT_WORLD_FAST", "1")
    cfg = Config(config_dir)
    v = cfg.get()
    assert v["server"]["port"] == 9999
    assert v["limits"]["allowShell"] is True
    assert v["pacing"]["fetchMs"] == 20
    assert v["providers"]["mock"]["latencyMs"] == [10, 40]


def test_update_only_editable_keys(config_dir):
    from backend.config import Config

    cfg = Config(config_dir)
    cfg.update({"limits": {"maxParallel": 3}, "server": {"port": 1111}})
    local = json.loads((config_dir / "local.json").read_text())
    assert "server" not in local
    assert local["limits"]["maxParallel"] == 3
    assert cfg.get()["server"]["port"] == 4300  # unaffected


def test_update_replaces_combos_whole(config_dir):
    from backend.config import Config

    cfg = Config(config_dir)
    cfg.update({"combos": {"fast": {"strategy": "fallback", "models": ["mock/other"]}}})
    v = cfg.get()
    assert v["combos"] == {"fast": {"strategy": "fallback", "models": ["mock/other"]}}


def test_staff_order_matches_teams_order(config_dir):
    from backend.config import Config

    cfg = Config(config_dir)
    v = cfg.get()
    ids = [s["id"] for s in v["staff"]]
    assert ids == ["ada", "rino", "sara", "leo"]
