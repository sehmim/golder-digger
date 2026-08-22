"""Ingest runs Essentia in-process now, which is far too slow for a suite that
ingests in most of its fixtures. It is off unless a test asks for it; the inline
path has its own coverage in test_ingest_essentia.py.
"""
import pytest

from goldigger import config


@pytest.fixture(scope="session", autouse=True)
def no_essentia_in_ingest():
    """Session-scoped so it beats the session-scoped corpora other tests build:
    a function-scoped patch would land after those fixtures had already run."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config, "ESSENTIA_ON_INGEST", False)
        yield
