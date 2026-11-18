import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Isolate all app data in a throwaway directory *before* the app is imported.
_DATA = tempfile.mkdtemp(prefix="clipwizard-test-")
os.environ["CLIPWIZARD_DATA_DIR"] = _DATA
os.environ["CLIPWIZARD_SKIP_DOTENV"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


@pytest.fixture(scope="session")
def demo_video(tmp_path_factory) -> Path:
    from app.demo import make_demo_video

    return make_demo_video(tmp_path_factory.mktemp("media") / "demo.mp4")
