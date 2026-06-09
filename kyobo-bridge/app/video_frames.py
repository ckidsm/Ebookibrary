"""화면녹화 영상 → 페이지별 프레임 추출 (ffmpeg + Pillow 중복제거).

iPad/모바일에서 교보 책을 넘기며 화면녹화한 영상을 업로드하면,
일정 fps 로 프레임을 뽑은 뒤 '같은 페이지' 연속 프레임을 합쳐(중복 제거)
페이지당 대표 1장만 book_dir/page_NNN.png 로 저장한다.

전략: 사용자가 페이지마다 잠깐 머무르므로(읽는 동안), 직전에 '채택한'
프레임과 충분히 다르면(=페이지가 넘어감) 새 페이지로 채택. 넘김 애니메이션
중간 프레임은 다음 안정 프레임에 의해 흡수되거나, 약간의 과추출은 OCR 단계
빈텍스트로 걸러진다. (임계값 diff_thresh 로 튜닝)
"""
from __future__ import annotations
import subprocess, tempfile, glob, logging
from pathlib import Path
from PIL import Image

log = logging.getLogger("kyobo-bridge.video")


def _ahash(img: Image.Image, size: int = 8) -> int:
    """average hash (64bit) — 페이지 유사도 비교용."""
    g = img.convert("L").resize((size, size), Image.LANCZOS)
    px = list(g.getdata())
    avg = sum(px) / len(px) if px else 0
    bits = 0
    for i, p in enumerate(px):
        if p >= avg:
            bits |= (1 << i)
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def extract_pages(video_path: str | Path, out_dir: str | Path,
                  fps: float = 1.5, scale_w: int = 1280,
                  diff_thresh: int = 8, max_pages: int = 3000) -> dict:
    """영상 → page_NNN.png. 반환 {ok, frames_raw, pages}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not has_ffmpeg():
        return {"ok": False, "error": "ffmpeg 미설치", "pages": 0}

    with tempfile.TemporaryDirectory() as td:
        raw_pat = str(Path(td) / "raw_%05d.png")
        cmd = ["ffmpeg", "-i", str(video_path),
               "-vf", f"fps={fps},scale={scale_w}:-1",
               "-vsync", "vfr", "-loglevel", "error", "-y", raw_pat]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=900)
        except subprocess.CalledProcessError as e:
            return {"ok": False, "error": "ffmpeg 실패: " + (e.stderr.decode("utf-8", "ignore")[:200] if e.stderr else ""), "pages": 0}
        except Exception as e:
            return {"ok": False, "error": f"ffmpeg 오류: {e}", "pages": 0}

        frames = sorted(glob.glob(str(Path(td) / "raw_*.png")))
        kept = 0
        last_hash = None
        for f in frames:
            try:
                img = Image.open(f)
                img.load()
            except Exception:
                continue
            h = _ahash(img)
            if last_hash is None or _hamming(h, last_hash) > diff_thresh:
                kept += 1
                try:
                    img.save(out_dir / f"page_{kept:03d}.png")
                except Exception:
                    kept -= 1
                    continue
                last_hash = h
                if kept >= max_pages:
                    break
        log.info("🎞 영상 추출: raw=%d → 페이지=%d (fps=%s, diff=%s)", len(frames), kept, fps, diff_thresh)
        return {"ok": True, "frames_raw": len(frames), "pages": kept}
