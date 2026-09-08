import pytest
from src import assistant

def test_parse_key():
    assert assistant._parse_key("sk-test12345") == "sk-test12345"
    assert assistant._parse_key("ANTHROPIC_API_KEY=sk-test12345") == "sk-test12345"
    assert assistant._parse_key('ANTHROPIC_API_KEY="sk-test12345"') == "sk-test12345"
    assert assistant._parse_key("ANTHROPIC_API_KEY='sk-test12345'") == "sk-test12345"
    assert assistant._parse_key("# comment\nsk-test12345") == "sk-test12345"
    assert assistant._parse_key("") is None
    assert assistant._parse_key("# only a comment") is None

def test_api_key_env_var(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-key")
    assert assistant.api_key() == "sk-env-key"

def test_api_key_file(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    key_file = tmp_path / "anthropic.key.txt"
    key_file.write_text("sk-file-key")
    monkeypatch.setattr(assistant, "_KEY_FILE", key_file)
    assert assistant.api_key() == "sk-file-key"

def test_api_key_none(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(assistant, "_KEY_FILE", tmp_path / "nonexistent.txt")
    assert assistant.api_key() is None


def test_answer(monkeypatch):
    class MockBlock:
        type = "text"
        text = "Hello!"

    class MockResponse:
        content = [MockBlock()]

    class MockMessages:
        def create(self, **kwargs):
            return MockResponse()

    class MockClient:
        messages = MockMessages()

    class MockAnthropic:
        def __init__(self, api_key):
            pass

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    import anthropic
    monkeypatch.setattr("anthropic.Anthropic", MockAnthropic)

    # We also need to mock anthropic.Anthropic in assistant
    monkeypatch.setattr(assistant, "api_key", lambda: "sk-test")
    monkeypatch.setattr(assistant, "MODEL", "test-model")

    # Needs a bit more intricate mocking for the client inside
    def mock_anthropic(*args, **kwargs):
        class C:
            messages = MockMessages()
        return C()

    import sys
    class FakeAnthropicMod:
        Anthropic = mock_anthropic
    sys.modules["anthropic"] = FakeAnthropicMod()

    text, usage = assistant.answer([{"role": "user", "content": "Hi"}], "System")
    assert text == "Hello!"
    assert usage == {"input_tokens": 0, "output_tokens": 0,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}

    empty_text, empty_usage = assistant.answer([], "System")
    assert empty_text == "Ask me anything about the portfolio."
    assert empty_usage == usage

def test_answer_no_key(monkeypatch):
    monkeypatch.setattr(assistant, "api_key", lambda: None)
    with pytest.raises(RuntimeError, match="no_key"):
        assistant.answer([{"role": "user", "content": "Hi"}], "System")


def test_cost_usd():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
              "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
    assert assistant.cost_usd(usage) == pytest.approx(1.00 + 5.00 + 1.25 + 0.10)
    assert assistant.cost_usd({}) == 0
