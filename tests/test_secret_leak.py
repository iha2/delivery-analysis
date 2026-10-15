from delivery_analysis.cli.main import main
from delivery_analysis.connectors.fake import FakeConnector
from delivery_analysis.model.records import Batch, Record
from delivery_analysis.settings import Secret

TOKEN = "tok-LEAK-CHECK-123"


def test_no_token_reaches_output_database_or_repr(tmp_path, capsys):
    env = {"GITHUB_ANALYSIS_RESULTS": str(tmp_path), "ATLASSIAN": TOKEN}
    record = Record("work_item", {"source": "fake", "source_id": "1", "key": "MD-1"})
    fake = FakeConnector(
        batches={"main": [Batch([record], cursor="c1"), Batch([record])]},
        fail_on_batch=1,
        fail_message=f"401 Unauthorized for {TOKEN}",
    )
    missing_env = tmp_path / "missing.env"

    assert main(["sync"], env_path=missing_env, environ=env, connectors=[fake]) == 1
    assert main(["doctor"], env_path=missing_env, environ=env) == 0
    output = capsys.readouterr()
    assert TOKEN not in output.out
    assert TOKEN not in output.err

    database_files = [path for path in tmp_path.glob("delivery.sqlite*") if path.is_file()]
    assert database_files, "the sync should have created the database"
    for path in database_files:
        assert TOKEN.encode("utf-8") not in path.read_bytes()

    assert TOKEN not in repr(Secret(TOKEN))
    assert TOKEN not in str(Secret(TOKEN))
