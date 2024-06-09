import json
from typing import Optional


def read_json(path: str, encoding: Optional[str] = None) -> list | dict:
    return json.load(open(path, encoding=encoding))
