"""데모용 템플릿 PNG 를 templates/demo/ 에 생성한다.

  python -m rune_hunter.tools.make_demo_templates

실제 게임 스크린샷으로 만든 템플릿이 없어도 파이프라인을 돌려볼 수 있다.
실전에서는 GUI 의 ‘화면에서 캡처’ 로 진짜 이미지를 만들어 쓰는 것이 정확하다.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import DEFAULT_TEMPLATE_DIR
from ..vision.synth import write_demo_templates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="데모 템플릿 생성")
    parser.add_argument(
        "--out", default=str(DEFAULT_TEMPLATE_DIR / "demo"), help="저장 폴더"
    )
    args = parser.parse_args(argv)
    written = write_demo_templates(Path(args.out))
    print(f"{len(written)}개 생성:")
    for path in written:
        print(" -", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
