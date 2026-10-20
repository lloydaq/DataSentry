import pytest
from fastapi.testclient import TestClient

from app.config import Limits
from app.main import create_app
from app.services.loader import LoadedDataset, load_csv

TEST_LIMITS = Limits(max_upload_bytes=200_000, max_rows=2_000, max_columns=40, max_label_review_rows=1_000)


def load(text: str, filename: str = "data.csv", limits: Limits = TEST_LIMITS) -> LoadedDataset:
    return load_csv(text.encode("utf-8"), limits, filename)


def rows_csv(header: str, rows: list[str]) -> str:
    return header + "\n" + "\n".join(rows) + "\n"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(TEST_LIMITS))


def upload(client: TestClient, path: str, text: str | bytes, filename: str = "data.csv", **fields):
    content = text.encode("utf-8") if isinstance(text, str) else text
    return client.post(path, files={"file": (filename, content, "text/csv")}, data=fields)
