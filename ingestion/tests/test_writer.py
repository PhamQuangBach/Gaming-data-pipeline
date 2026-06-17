import pytest, json, sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from writer import write_jsonl


def test_write_jsonl_creates_file(tmp_path):
    """Should create a valid JSONL file in the correct partition folder."""
    records = [{"id": 1, "name": "Hades"}, {"id": 2, "name": "Celeste"}]
    output = write_jsonl(records, entity="games", base_dir=str(tmp_path))

    assert output.exists()
    lines = output.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["name"] == "Hades"


def test_write_jsonl_partitions_by_date(tmp_path):
    """Output path should include today's date as a folder."""
    from datetime import date
    records = [{"id": 1}]
    output = write_jsonl(records, entity="games", base_dir=str(tmp_path))
    assert date.today().isoformat() in str(output)