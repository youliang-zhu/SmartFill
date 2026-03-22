"""Native PDF 程序化字段检测（Label-first + 兼容 legacy）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.native.preprocess.extraction import ExtractionMixin
from app.services.native.preprocess.label_first import LabelFirstMixin
from app.services.native.preprocess.legacy import LegacyEnginesMixin
from app.services.native.preprocess.types import LabelCandidate, RectTuple
from app.services.native.preprocess.utils import UtilityMixin


class NativeDetector(LabelFirstMixin, LegacyEnginesMixin, ExtractionMixin, UtilityMixin):
    """Native PDF 结构化检测器。"""


_native_detector = NativeDetector()


def get_native_detector() -> NativeDetector:
    return _native_detector


def _main() -> None:
    parser = argparse.ArgumentParser(description="Native PDF 字段检测（Phase 1）")
    parser.add_argument("--input", required=True, help="输入 PDF 路径")
    parser.add_argument("--output", default="", help="输出 JSON 路径（可选）")
    parser.add_argument("--pretty", action="store_true", help="控制台输出缩进 JSON")
    args = parser.parse_args()

    pdf_path = Path(args.input)
    if not pdf_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {pdf_path}")

    detector = get_native_detector()
    result = detector.detect_all(pdf_path)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"已输出检测结果: {out}")

    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summary = {
            "pdf_path": result["pdf_path"],
            "page_count": result["page_count"],
            "detected_field_count": result["detected_field_count"],
            "fields_per_page": [len(p["detected_fields"]) for p in result["pages"]],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
