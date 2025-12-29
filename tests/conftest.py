import pytest
from unittest.mock import patch
from smith.orchestrator import reset_services


@pytest.fixture
def mock_db():
    reset_services()
    with patch("smith.tools.DB_TOOLS.DBTools") as MockDB:
        instance = MockDB.return_value
        # Default behavior: empty valid responses
        instance.read_many.return_value = {"status": "success", "data": []}
        yield instance
    reset_services()


@pytest.fixture
def mock_llm():
    with patch("smith.tools.LLM_CALLER.call_llm") as mock:
        mock.return_value = {"status": "success", "response": "MOCK_RESPONSE"}
        yield mock


@pytest.fixture
def mock_loader():
    with patch("smith.tool_loader.load_tool_function") as mock:
        # Default: echo args
        mock.return_value = lambda **kwargs: {"status": "success", "result": kwargs}
        yield mock
