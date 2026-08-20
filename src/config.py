"""
config/*.yaml 로더. 프로젝트 루트 기준 경로를 사용하므로 실행 위치(cwd)에
관계없이 항상 같은 설정 파일을 읽는다.
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_column_roles() -> dict:
    return load_yaml("column_roles.yaml")["roles"]


def load_thresholds() -> dict:
    return load_yaml("thresholds.yaml")


def load_weights() -> dict:
    return load_yaml("weights.yaml")
