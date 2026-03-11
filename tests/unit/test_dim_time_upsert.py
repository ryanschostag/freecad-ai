from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.utils import upsert_time


class _DimTimeRow:
    def __init__(self, time_id: int):
        self.time_id = time_id


class _FakeQuery:
    def __init__(self, responses):
        self._responses = responses

    def filter(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        if self._responses:
            return self._responses.pop(0)
        return None


class _FakeSession:
    def __init__(self):
        self.added = []
        self.rollbacks = 0
        self.refresh_calls = 0
        self.commit_calls = 0
        self._query = _FakeQuery([None, _DimTimeRow(42)])

    def query(self, _model):
        return self._query

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commit_calls += 1
        if self.commit_calls == 1:
            raise IntegrityError("insert into dim_time", {}, Exception("duplicate"))

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, _obj):
        self.refresh_calls += 1


def test_upsert_time_returns_existing_row_after_duplicate_insert_race():
    db = _FakeSession()

    time_id = upsert_time(db, datetime(2026, 3, 9, 22, 25, 5, tzinfo=timezone.utc))

    assert time_id == 42
    assert len(db.added) == 1
    assert db.rollbacks == 1
    assert db.refresh_calls == 0
