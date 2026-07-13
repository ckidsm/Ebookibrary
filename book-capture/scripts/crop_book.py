"""raws/ 폴더의 전체창 raw → 책 페이지 크롭(page_NNN.png) + 썸네일(thumbs/).

표준 크롭(page_crop.crop_page): 안 잘림 + 자연 여백. 앱 캡처(app_capture_raws.py) 다음 단계.
사용: python scripts/crop_book.py <raws_dir> <out_dir> [--thumb 1800] [--chrome L,T,R,B]

⚠️ chrome(고정 크롭)은 캡처 방식마다 다르다. 기본값(135,150,135,155)은 웹뷰어(wviewer)용 —
   교보 **데스크탑 앱** raw 는 상·하 크롬이 거의 없어(흰 여백만) 큰 top 값이 **본문(섹션 헤더)을
   잘라먹는다**. 앱 캡처는 `--chrome 20,20,20,20` 처럼 작게 주고 content_crop 이 여백을 처리하게 한다.
   (2026-07-12 '이미지 처리 바이블' p11 섹션 헤더 '1.1 …' 상단 잘림 = top=150 과다 → 20 으로 교정.)
"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bookcapture"))
from page_crop import crop_page, CropRules  # noqa: E402
from PIL import Image  # noqa: E402


def _parse_chrome(s):
    parts = [int(x) for x in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("chrome 는 'L,T,R,B' 4개 정수")
    return tuple(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raws_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--thumb", type=int, default=CropRules.THUMB_MAX_W, help="썸네일 최대 폭(px)")
    ap.add_argument("--chrome", type=_parse_chrome, default=None,
                    help="고정 크롭 'L,T,R,B'(px). 미지정=crop_page 기본(웹뷰어용). 앱 raw 는 '20,20,20,20' 권장.")
    a = ap.parse_args()
    raws = sorted(Path(a.raws_dir).glob("raw_*.png"))
    out = Path(a.out_dir); (out / "thumbs").mkdir(parents=True, exist_ok=True)
    if not raws:
        print(f"raw_*.png 없음: {a.raws_dir}"); return 1
    ckw = {"chrome": a.chrome} if a.chrome else {}
    for f in raws:
        n = int(f.stem.split("_")[1])
        c = crop_page(Image.open(f), **ckw)
        c.save(out / f"page_{n:03d}.png")
        tw = a.thumb
        th = c.resize((tw, round(c.size[1] * tw / c.size[0])), Image.LANCZOS) if c.size[0] > tw else c
        th.save(out / "thumbs" / f"page_{n:03d}.png")
    print(f"완료 {len(raws)}장 → {out} (+thumbs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
