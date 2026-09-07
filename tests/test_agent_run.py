import pytest
import io
import time
from src import agent_run
from src.assistant import api_key

class MockBetaFiles:
    def upload(self, file):
        class MockFile:
            id = "file_123"
        return MockFile()

class MockBetaEnvironments:
    def create(self, name, config):
        class MockEnv:
            id = "env_123"
        return MockEnv()

class MockBetaSessionsEvents:
    def __init__(self, run_time=0.0):
        self.run_time = run_time

    def stream(self, session_id):
        class MockStream:
            def __init__(self, rt):
                self.rt = rt
            def __enter__(self):
                class MockBlock:
                    type = "text"
                    text = "Agent response text"

                class MockEventMessage:
                    type = "agent.message"
                    content = [MockBlock()]

                class MockEventIdle:
                    type = "session.status_idle"

                class MockIterator:
                    def __init__(self, rt):
                        self.events = [MockEventMessage(), MockEventIdle()]
                        self.rt = rt

                    def __iter__(self):
                        time.sleep(self.rt)
                        return iter(self.events)
                return MockIterator(self.rt)
            def __exit__(self, *args):
                pass
        return MockStream(self.run_time)

    def send(self, session_id, events):
        pass

class MockBetaSessions:
    def __init__(self, run_time=0.0):
        self.events = MockBetaSessionsEvents(run_time)

    def create(self, **kwargs):
        class MockSession:
            id = "sess_123"
        return MockSession()

class MockBeta:
    def __init__(self, run_time=0.0):
        self.files = MockBetaFiles()
        self.environments = MockBetaEnvironments()
        self.sessions = MockBetaSessions(run_time)

class MockAnthropic:
    def __init__(self, api_key, run_time=0.0):
        self.beta = MockBeta(run_time)

def test_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    import anthropic
    monkeypatch.setattr("anthropic.Anthropic", MockAnthropic)
    client = agent_run._client()
    assert client is not None

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(agent_run, "api_key", lambda: None)
    with pytest.raises(RuntimeError, match="no_key"):
        agent_run._client()

def test_environment_id(monkeypatch):
    agent_run._ENV_CACHE["id"] = None
    client = MockAnthropic("dummy")
    assert agent_run._environment_id(client) == "env_123"
    assert agent_run._ENV_CACHE["id"] == "env_123"

    # Should use cache now
    assert agent_run._environment_id(client) == "env_123"

def test_run_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    agent_run._ENV_CACHE["id"] = None

    def mock_client():
        return MockAnthropic("dummy")
    monkeypatch.setattr(agent_run, "_client", mock_client)

    # Test no agent
    with pytest.raises(RuntimeError, match="no_agent"):
        agent_run.run_agent("", "task")

    # Test success
    res = agent_run.run_agent(
        "agent_id",
        "task",
        context="ctx",
        attachments=[{"filename": "test.txt", "content": "data", "mount_path": "/path/test.txt"}]
    )
    assert res == "Agent response text"

def test_run_agent_timeout(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    agent_run._ENV_CACHE["id"] = None
    monkeypatch.setattr(agent_run, "RUN_TIMEOUT_S", 0.01)

    def mock_client():
        return MockAnthropic("dummy", run_time=0.02)
    monkeypatch.setattr(agent_run, "_client", mock_client)

    res = agent_run.run_agent("agent_id", "task")
    assert "exceeded the time limit" in res
