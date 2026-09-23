import io
import json
from unittest.mock import Mock

import pytest
from aiohttp import web

from call_audio import cli, server
from call_audio.compression import RULES_VERSION
from call_audio.runtime import Controller


@pytest.fixture
def mocked_server(monkeypatch):
    app = object()
    create = Mock(return_value=app)
    run = Mock()
    capture = Mock(side_effect=AssertionError("The CLI must never start capture."))
    monkeypatch.setattr(server, "create_app", create)
    monkeypatch.setattr(web, "run_app", run)
    monkeypatch.setattr(Controller, "start", capture)
    return app, create, run, capture


def mock_health(monkeypatch, payload):
    response = io.BytesIO(json.dumps(payload).encode())
    health = Mock(return_value=response)
    monkeypatch.setattr(cli.urllib.request, "urlopen", health)
    return health


def test_serve_rejects_browser_option(capsys, mocked_server):
    with pytest.raises(SystemExit) as error:
        cli.main(["serve", "--open"])
    assert error.value.code == 2
    assert "unrecognized arguments: --open" in capsys.readouterr().err
    _, create, run, capture = mocked_server
    create.assert_not_called()
    run.assert_not_called()
    capture.assert_not_called()


def test_serve_starts_headless_api_without_capture(monkeypatch, capsys, mocked_server):
    monkeypatch.setattr(cli.urllib.request, "urlopen", Mock(side_effect=ConnectionRefusedError()))
    app, create, run, capture = mocked_server

    assert cli.main(["serve", "--port", "8766", "--model", "tiny"]) == 0

    create.assert_called_once_with(port=8766, model="tiny")
    run.assert_called_once_with(app, host="127.0.0.1", port=8766, access_log=None)
    capture.assert_not_called()
    output = capsys.readouterr().out
    assert "headless API at http://127.0.0.1:8766" in output
    assert "capture remains OFF until POST /api/start" in output


def test_serve_refuses_legacy_ui_without_modifying_it(monkeypatch, capsys, mocked_server):
    mock_health(monkeypatch, {"app": "call-audio-helper", "version": "0.1.0"})

    assert cli.main(["serve"]) == 1

    _, create, run, capture = mocked_server
    create.assert_not_called()
    run.assert_not_called()
    capture.assert_not_called()
    error = capsys.readouterr().err
    assert "Port 8765 is occupied by the legacy Call Audio UI" in error
    assert "another --port" in error
    assert "it has not been changed" in error


def test_serve_reuses_compatible_headless_api(monkeypatch, capsys, mocked_server):
    health = mock_health(monkeypatch, {
        "app": "call-audio-helper", "mode": "headless", "api_version": 1,
        "capabilities": {"compression": ["none", "minimal"]},
        "compression_rules_version": RULES_VERSION,
    })

    assert cli.main(["serve", "--port", "9000"]) == 0

    health.assert_called_once_with("http://127.0.0.1:9000/api/health", timeout=0.5)
    _, create, run, capture = mocked_server
    create.assert_not_called()
    run.assert_not_called()
    capture.assert_not_called()
    assert "headless API is already running at http://127.0.0.1:9000" in capsys.readouterr().out


def test_serve_refuses_incompatible_api_version(monkeypatch, capsys, mocked_server):
    mock_health(monkeypatch, {
        "app": "call-audio-helper", "mode": "headless", "api_version": 2,
    })

    assert cli.main(["serve"]) == 1

    _, create, run, capture = mocked_server
    create.assert_not_called()
    run.assert_not_called()
    capture.assert_not_called()
    assert "incompatible Call Audio API version" in capsys.readouterr().err


def test_serve_refuses_old_headless_without_compression(monkeypatch, capsys, mocked_server):
    mock_health(monkeypatch, {"app": "call-audio-helper", "mode": "headless", "api_version": 1})
    assert cli.main(["serve"]) == 1
    assert "older headless helper" in capsys.readouterr().err
    mocked_server[1].assert_not_called()


def test_serve_loads_optional_tokenizer_before_startup(monkeypatch, mocked_server):
    from call_audio import tokens
    monkeypatch.setattr(cli.urllib.request, "urlopen", Mock(side_effect=ConnectionRefusedError()))
    counter = lambda text: len(text)
    load = Mock(return_value=counter)
    monkeypatch.setattr(tokens, "load_token_counter", load)
    assert cli.main(["serve", "--tokenizer", "o200k_base"]) == 0
    load.assert_called_once_with("o200k_base")
    mocked_server[1].assert_called_once_with(port=8765, model="small", token_counter=counter, tokenizer_name="o200k_base")
    mocked_server[3].assert_not_called()


def test_serve_refuses_silent_tokenizer_mismatch(monkeypatch, capsys, mocked_server):
    mock_health(monkeypatch, {"app": "call-audio-helper", "mode": "headless", "api_version": 1,
                             "capabilities": {"compression": ["none", "minimal"]}, "compression_tokenizer": None,
                             "compression_rules_version": RULES_VERSION})
    assert cli.main(["serve", "--tokenizer", "o200k_base"]) == 1
    assert "different tokenizer" in capsys.readouterr().err
    mocked_server[1].assert_not_called()


@pytest.mark.parametrize("rules_version", [None, "obsolete", "999"])
def test_serve_refuses_stale_compression_rules(monkeypatch, capsys, mocked_server, rules_version):
    mock_health(monkeypatch, {
        "app": "call-audio-helper", "mode": "headless", "api_version": 1,
        "capabilities": {"compression": ["none", "minimal"]},
        "compression_rules_version": rules_version,
    })
    assert cli.main(["serve"]) == 1
    assert "different compression rules version" in capsys.readouterr().err
    mocked_server[1].assert_not_called()
    mocked_server[2].assert_not_called()
    mocked_server[3].assert_not_called()
