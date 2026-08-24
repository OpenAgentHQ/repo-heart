from pathlib import Path

import pytest

from tests.helpers.pipeline import run_pipeline


@pytest.mark.parametrize("payload", list(Path("examples").glob("*.json")))
def test_pipeline_exits_zero(payload: Path) -> None:
    code, out = run_pipeline(payload)

    assert code == 0, f"Pipeline failed for {payload.name}:\n{out}"
    assert "event_msg=run_complete" in out
    assert "errors=0" in out
