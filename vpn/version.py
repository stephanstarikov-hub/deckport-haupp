"""package.json is the sole product version source, including packaged builds."""
import json
from pathlib import Path

VERSION = json.loads((Path(__file__).resolve().parents[1] / "package.json").read_text(encoding="utf-8"))["version"]
PROTOCOL_VERSION = 1
