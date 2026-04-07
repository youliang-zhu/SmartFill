"""ODL fallback helpers for preprocess label completion.

This module owns the preprocess-level ODL fallback signal and the shared
helpers used by multiple collectors. It is intentionally limited to:

- resolving the raw-dir signal
- loading ODL text lines
- offering generic label-completion matching

It does not decide fill_rect geometry or table structure.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.native.preprocess.core.types import RectTuple

_ODL_TEXT_TYPES = {"paragraph", "heading", "caption", "list item", "text block"}
_ODL_OPTION_TEXTS = {"yes", "no", "true", "false", "si", "sí"}
_ODL_FALLBACK_RAW_DIR_ENV = "SMARTFILL_ODL_FALLBACK_RAW_DIR"
_REPO_ROOT = Path(__file__).resolve().parents[6]
_DEFAULT_ODL_RUNS_ROOT = (
    _REPO_ROOT / "Testspace-opensourced-tools" / "opendataloader" / "runs" / "opendataloader"
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_IF_PREFIX_RE = re.compile(r"^\s*[\(\[]?\s*if\s+(?:yes|no|true|false)\b", re.I)
_TRAILING_OPTION_PAIR_RE = re.compile(
    r"^(?P<prefix>.+?)\s+(?P<tail>(?:yes(?:\s*/\s*si)?|true)\b.*\b(?:no|false)\b.*)$",
    re.I,
)


def _iter_odl_elements(node: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    if isinstance(node, dict):
        if all(k in node for k in ("type", "page number", "bounding box")):
            bbox = node.get("bounding box")
            if isinstance(bbox, list) and len(bbox) == 4:
                found.append(
                    {
                        "type": str(node.get("type", "")),
                        "page_num": int(node.get("page number", 0)),
                        "bbox": tuple(float(v) for v in bbox),
                        "content": str(node.get("content", "") or "").strip(),
                    }
                )
        for value in node.values():
            found.extend(_iter_odl_elements(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_iter_odl_elements(item))
    return found


def _pdf_to_top_origin_bbox(
    pdf_bbox: Tuple[float, float, float, float],
    page_height: float,
) -> List[float]:
    x0, y_bottom, x1, y_top = pdf_bbox
    return [
        round(x0, 2),
        round(page_height - y_top, 2),
        round(x1, 2),
        round(page_height - y_bottom, 2),
    ]


@lru_cache(maxsize=128)
def _load_odl_fallback_lines_cached(
    raw_json_path: str,
    page_num: int,
    page_height: float,
) -> Tuple[Tuple[str, Tuple[float, float, float, float]], ...]:
    path = Path(raw_json_path)
    if not path.exists():
        return tuple()
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    seen: Set[Tuple[str, Tuple[float, float, float, float]]] = set()
    rows: List[Tuple[str, Tuple[float, float, float, float]]] = []
    for elem in _iter_odl_elements(raw.get("kids", [])):
        if elem["page_num"] != page_num or elem["type"] not in _ODL_TEXT_TYPES:
            continue
        text = elem["content"].strip()
        if not text:
            continue
        bbox = tuple(_pdf_to_top_origin_bbox(elem["bbox"], page_height))
        key = (text, bbox)
        if key in seen:
            continue
        seen.add(key)
        rows.append(key)
    rows.sort(key=lambda item: (item[1][1], item[1][0]))
    return tuple(rows)


@lru_cache(maxsize=1)
def _discover_default_odl_fallback_raw_dir() -> str:
    if not _DEFAULT_ODL_RUNS_ROOT.exists():
        return ""
    run_dirs = sorted(
        (path for path in _DEFAULT_ODL_RUNS_ROOT.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    for run_dir in run_dirs:
        raw_dirs = sorted(
            (path for path in run_dir.glob("mode_*/stage_01_convert/raw") if path.is_dir()),
            key=lambda path: str(path),
            reverse=True,
        )
        if raw_dirs:
            return str(raw_dirs[0])
    return ""


def _resolve_odl_fallback_raw_dir() -> str:
    explicit = os.environ.get(_ODL_FALLBACK_RAW_DIR_ENV, "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    return _discover_default_odl_fallback_raw_dir()


def _load_odl_fallback_lines(
    pdf_path: str,
    page_num: int,
    page_size: RectTuple | None,
) -> List[Dict[str, Any]]:
    raw_dir = _resolve_odl_fallback_raw_dir()
    if not raw_dir or not pdf_path or page_size is None:
        return []
    raw_json = Path(raw_dir) / f"{Path(pdf_path).stem}.json"
    page_height = float(page_size[3] - page_size[1])
    rows = _load_odl_fallback_lines_cached(str(raw_json), page_num, page_height)
    return [
        {
            "text": text,
            "bbox": list(bbox),
            "font_size": 10.0,
            "page_num": page_num,
            "source": "odl",
        }
        for text, bbox in rows
    ]


def _token_set(text: str) -> Set[str]:
    return {tok.lower() for tok in _TOKEN_RE.findall(text or "")}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _strip_enum_prefix(text: str) -> str:
    return re.sub(r"^\s*(?:\d+\.\s*|[A-Za-z]\.\s*)", "", _normalize_text(text))


def _enum_prefix(text: str) -> str:
    m = re.match(r"^\s*((?:\d+\.|[A-Za-z]\.))\s*", _normalize_text(text))
    if not m:
        return ""
    return m.group(1)


def _looks_like_option_text(text: str) -> bool:
    toks = _token_set(text)
    if not toks:
        return True
    if toks <= _ODL_OPTION_TEXTS:
        return True
    if len(toks) <= 2 and all(tok in _ODL_OPTION_TEXTS for tok in toks):
        return True
    return False


def _is_polluted_label(text: str) -> bool:
    toks = _token_set(text)
    if not toks:
        return False
    if {"yes", "no"} <= toks:
        return True
    if {"true", "false"} <= toks:
        return True
    if "si" in toks and ("yes" in toks or "no" in toks):
        return True
    return False


def _strip_trailing_option_tail(text: str) -> str:
    m = _TRAILING_OPTION_PAIR_RE.match(_normalize_text(text))
    if not m:
        return _normalize_text(text)
    return _normalize_text(m.group("prefix"))


def _find_odl_label_completion(
    baseline_label: str,
    baseline_bbox: RectTuple | List[float] | None,
    odl_lines: List[Dict[str, Any]],
    allow_shorter: bool = False,
    allow_if_prefix: bool = False,
) -> Tuple[str, Optional[RectTuple]]:
    baseline_label = _normalize_text(baseline_label)
    if not baseline_label or baseline_bbox is None:
        return "", None

    baseline_core = _strip_enum_prefix(_strip_trailing_option_tail(baseline_label))
    baseline_tokens = _token_set(baseline_core)
    if not baseline_tokens:
        return "", None

    base_bbox = tuple(float(v) for v in baseline_bbox)
    best: Optional[Tuple[float, str, RectTuple]] = None
    for line in odl_lines:
        text = _normalize_text(str(line.get("text", "")))
        if not text or _looks_like_option_text(text) or _is_polluted_label(text):
            continue
        if not allow_if_prefix and _IF_PREFIX_RE.match(text):
            continue

        bbox = tuple(line.get("bbox", []))
        if len(bbox) != 4:
            continue
        bbox = tuple(float(v) for v in bbox)

        cand_core = _strip_enum_prefix(_strip_trailing_option_tail(text))
        cand_tokens = _token_set(cand_core)
        overlap = len(baseline_tokens & cand_tokens) / max(1, len(baseline_tokens))
        if overlap < 0.8:
            continue
        if abs(bbox[0] - base_bbox[0]) > 18.0:
            continue
        if bbox[1] > base_bbox[1] + 8.0:
            continue
        if bbox[2] < base_bbox[2] - 20.0:
            continue
        if bbox[3] < base_bbox[3] - 2.0:
            continue
        if not allow_shorter and len(text) < len(baseline_label) + 8:
            continue

        score = overlap * 1000.0 + len(text) - abs(bbox[0] - base_bbox[0]) - abs(bbox[1] - base_bbox[1])
        if best is None or score > best[0]:
            best = (score, text, bbox)

    if best is None:
        return "", None

    prefixed = best[1]
    prefix = _enum_prefix(baseline_label)
    if prefix and not _enum_prefix(prefixed):
        prefixed = f"{prefix} {prefixed}"
    return prefixed, best[2]


def _apply_odl_label_completion_to_lines(
    text_lines: List[Dict[str, Any]],
    pdf_path: str,
    page_num: int,
    page_size: RectTuple | None,
    allow_if_prefix: bool = True,
) -> List[Dict[str, Any]]:
    """Preprocess-level Phase 1.7: complete split native lines using ODL text blocks.

    This stage is intentionally limited to text completion:
    - native geometry extraction and merge stay unchanged
    - ODL only upgrades line text/bbox when a high-confidence completion exists
    - duplicate completed lines are collapsed before collectors run
    """
    odl_lines = _load_odl_fallback_lines(
        pdf_path=pdf_path,
        page_num=page_num,
        page_size=page_size,
    )
    if not odl_lines:
        return text_lines

    completed: List[Dict[str, Any]] = []
    for line in text_lines:
        text = _normalize_text(str(line.get("text", "")))
        bbox = line.get("bbox")
        if not text or bbox is None:
            completed.append(line)
            continue
        try:
            base_bbox = tuple(float(v) for v in bbox)
        except Exception:
            completed.append(line)
            continue
        if len(base_bbox) != 4:
            completed.append(line)
            continue

        odl_label, odl_bbox = _find_odl_label_completion(
            baseline_label=text,
            baseline_bbox=base_bbox,
            odl_lines=odl_lines,
            allow_shorter=False,
            allow_if_prefix=allow_if_prefix,
        )
        if not odl_label or odl_bbox is None:
            completed.append(line)
            continue

        patched = dict(line)
        patched["text"] = odl_label
        patched["bbox"] = list(odl_bbox)
        completed.append(patched)

    deduped: List[Dict[str, Any]] = []
    dedup_index: Dict[Tuple[str, Tuple[float, float, float, float]], int] = {}
    for line in completed:
        text = _normalize_text(str(line.get("text", "")))
        bbox = line.get("bbox")
        if not text or bbox is None:
            deduped.append(line)
            continue
        try:
            bbox_key = tuple(round(float(v), 2) for v in bbox)
        except Exception:
            deduped.append(line)
            continue
        if len(bbox_key) != 4:
            deduped.append(line)
            continue

        text_core = _strip_enum_prefix(_strip_trailing_option_tail(text))
        key = (text_core, bbox_key)
        if key not in dedup_index:
            dedup_index[key] = len(deduped)
            deduped.append(line)
            continue

        prev = deduped[dedup_index[key]]
        prev_text = _normalize_text(str(prev.get("text", "")))
        if len(text) > len(prev_text):
            deduped[dedup_index[key]] = line

    deduped.sort(
        key=lambda line: (
            float(line.get("bbox", [0.0, 0.0, 0.0, 0.0])[1]),
            float(line.get("bbox", [0.0, 0.0, 0.0, 0.0])[0]),
        )
    )
    return deduped
