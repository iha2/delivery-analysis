import pytest

from delivery_analysis.connectors.fake import FakeConnector
from delivery_analysis.connectors.registry import build_connectors
from delivery_analysis.model.records import Batch, Record
from delivery_analysis.settings import Settings


def batch(n, cursor=None):
    record = Record("work_item", {"source": "fake", "source_id": str(n)})
    return Batch(records=[record], cursor=cursor)


def test_fake_yields_batches_in_order_and_records_calls():
    fake = FakeConnector(batches={"main": [batch(1, "c1"), batch(2, "c2")]})
    assert fake.scopes() == ["main"]
    got = list(fake.sync("main", "2026-05-01T00:00:00Z"))
    assert [b.cursor for b in got] == ["c1", "c2"]
    assert fake.calls == [("main", "2026-05-01T00:00:00Z")]


def test_fake_fails_before_the_chosen_batch():
    fake = FakeConnector(batches={"main": [batch(1), batch(2)]}, fail_on_batch=1, fail_message="down")
    iterator = fake.sync("main", None)
    assert next(iterator).records[0].values["source_id"] == "1"
    with pytest.raises(RuntimeError, match="down"):
        next(iterator)


def test_fake_validate_returns_its_problems():
    assert FakeConnector().validate() == []
    assert FakeConnector(problems=["token missing"]).validate() == ["token missing"]


def test_registry_has_no_connectors_yet(tmp_path):
    assert build_connectors(Settings(db_path=tmp_path / "d.sqlite"), {}) == []


def test_registry_builds_the_bitbucket_connector_only_when_the_token_is_set(tmp_path):
    settings = Settings(db_path=tmp_path / "d.sqlite")
    assert build_connectors(settings, {}) == []
    built = build_connectors(settings, {"BITBUCKET": "tok-bb-1"})
    assert [connector.name for connector in built] == ["bitbucket"]
