import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from call_audio.tokens import load_token_counter


def test_default_needs_no_tokenizer_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    assert load_token_counter(None) is None
    with pytest.raises(RuntimeError, match="extra tokens"):
        load_token_counter("o200k_base")


def test_counter_uses_literal_text_and_reuses_loaded_encoding(monkeypatch):
    encode = Mock(return_value=[1, 2, 3])
    get = Mock(return_value=SimpleNamespace(encode_ordinary=encode))
    monkeypatch.setitem(sys.modules, "tiktoken", SimpleNamespace(get_encoding=get))
    count = load_token_counter("o200k_base")
    assert count("<|endoftext|> is the customer's literal string") == 3
    assert count("another final") == 3
    get.assert_called_once_with("o200k_base")
    assert encode.call_count == 3  # Warmup, then exactly the two supplied texts.


def test_load_error_is_actionable_and_redacted(monkeypatch):
    get = Mock(side_effect=OSError("credential/path details"))
    monkeypatch.setitem(sys.modules, "tiktoken", SimpleNamespace(get_encoding=get))
    with pytest.raises(RuntimeError, match="prepare its vocabulary") as error:
        load_token_counter("cl100k_base")
    assert "credential" not in str(error.value)
    with pytest.raises(ValueError, match="supported tokenizer"):
        load_token_counter("untrusted/custom-plugin")
