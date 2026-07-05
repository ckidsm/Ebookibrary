"""raws/ 폴더의 전체창 raw → 책 페이지 크롭(page_NNN.png) + 썸네일(thumbs/).

표준 크롭(page_crop.crop_page): 안 잘림 + 자연 여백. 앱 캡처(app_capture_raws.py) 다음 단계.
사용: python scripts/crop_book.py <raws_dir> <out_dir> [--thumb 1800]
"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bookcapture"))
from page_crop import crop_page  # noqa: E402
from PIL import Image  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raws_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--thumb", type=int, default=1800, help="썸네일 최대 폭(px)")
    a = ap.parse_args()
    raws = sorted(Path(a.raws_dir).glob("raw_*.png"))
    out = Path(a.out_dir); (out / "thumbs").mkdir(parents=True, exist_ok=True)
    if not raws:
        print(f"raw_*.png 없음: {a.raws_dir}"); return 1
    for f in raws:
        n = int(f.stem.split("_")[1])
        c = crop_page(Image.open(f))
        c.save(out / f"page_{n:03d}.png")
        tw = a.thumb
        th = c.resize((tw, round(c.size[1] * tw / c.size[0])), Image.LANCZOS) if c.size[0] > tw else c
        th.save(out / "thumbs" / f"page_{n:03d}.png")
    print(f"완료 {len(raws)}장 → {out} (+thumbs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
