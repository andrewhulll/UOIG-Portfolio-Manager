import pytest
from pathlib import Path
from src.ingest.thesis import load_theses, stock_thesis
import src.ingest.thesis as thesis_module

def test_load_theses(monkeypatch, tmp_path):
    # Create a mock THESIS.md
    mock_thesis = tmp_path / "THESIS.md"
    mock_thesis.write_text("""
### AAPL Apple Inc.
**2023-10-01 · John Doe**
1. Strong iPhone cycle.
2. Services growth.
3. High margins.

**2023-01-01 · Jane Smith**
1. Old point 1.
2. Old point 2.
3. Old point 3.

### MSFT Microsoft Corp.
**2023-11-01 · Alice**
1. Azure growth.
2. AI integration.
3. Cash flow.
""")

    monkeypatch.setattr(thesis_module, "_PATH", mock_thesis)
    # Reset cache
    thesis_module._cache = None

    theses = load_theses()
    assert "AAPL" in theses
    assert len(theses["AAPL"]) == 2
    assert theses["AAPL"][0]["date"] == "2023-10-01"
    assert theses["AAPL"][0]["analyst"] == "John Doe"
    assert len(theses["AAPL"][0]["points"]) == 3
    assert theses["AAPL"][0]["points"][0] == "Strong iPhone cycle."

    assert "MSFT" in theses
    assert len(theses["MSFT"]) == 1

    # Test stock_thesis
    aapl_thesis = stock_thesis("AAPL")
    assert aapl_thesis["ticker"] == "AAPL"
    assert aapl_thesis["thesis"]["date"] == "2023-10-01"

    unknown_thesis = stock_thesis("UNKNOWN")
    assert unknown_thesis["ticker"] == "UNKNOWN"
    assert unknown_thesis["thesis"] is None

def test_load_theses_no_file(monkeypatch, tmp_path):
    mock_thesis = tmp_path / "NONEXISTENT.md"
    monkeypatch.setattr(thesis_module, "_PATH", mock_thesis)
    thesis_module._cache = None

    theses = load_theses()
    assert theses == {}
