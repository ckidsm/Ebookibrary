"""캡처 후처리 규칙 엔진 단위 테스트 — QC · 중복꼬리 · 챕터감지.

실행: book-capture/.venv/bin/python tests/test_postcapture.py
합성 PNG/OCR 파일로 하드웨어·API 없이 검증.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bookcapture import postcapture as pc
from PIL import Image


import random as _random


def _png(path: Path, size=None, color=(128, 128, 128), blank=False):
    """content=결정적 시드 노이즈로 >MIN_PAGE_KB(같은 color=같은 해시). blank=solid(작은 파일).
    크기·터미널크기 등은 하드코딩 대신 pc.QCRules 상수 참조(단일 관리처)."""
    if size is None:
        size = pc.QCRules.FIXTURE_PAGE_SIZE
    if blank:
        Image.new("RGB", size, color).save(path); return
    seed = color[0] * 65536 + color[1] * 256 + color[2]
    rnd = _random.Random(seed)
    img = Image.new("RGB", size)
    img.putdata([(rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255))
                 for _ in range(size[0] * size[1])])
    img.save(path)


class TestCaptureQC(unittest.TestCase):
    def _book(self, tmp):
        raws = Path(tmp) / "source_raws"; raws.mkdir()
        return raws

    def test_clean_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            raws = self._book(tmp)
            for i in range(1, 6):  # 5장, 서로 다른 색(다른 해시), 같은 크기
                _png(raws / f"raw_{i:03d}.png", color=(10 * i, 20, 30))
            rep = pc.CaptureQC(tmp).validate()
            self.assertTrue(rep["ok"], rep["flags"])
            self.assertEqual(rep["count"], 5)
            self.assertEqual(rep["unique_hashes"], 5)

    def test_terminal_contamination_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            raws = self._book(tmp)
            for i in range(1, 5):
                _png(raws / f"raw_{i:03d}.png", color=(10 * i, 20, 30))
            _png(raws / "raw_005.png", size=pc.QCRules.FIXTURE_TERMINAL_SIZE, color=(0, 0, 0), blank=True)  # 터미널 해상도
            rep = pc.CaptureQC(tmp).validate()
            self.assertFalse(rep["ok"])
            self.assertTrue(rep["terminal_suspect"])
            self.assertTrue(any("터미널" in f for f in rep["flags"]))

    def test_duplicate_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            raws = self._book(tmp)
            for i in range(1, 4):
                _png(raws / f"raw_{i:03d}.png", color=(10 * i, 20, 30))
            _png(raws / "raw_004.png", color=(30, 20, 30))  # raw_003 과 동일 색=동일 해시
            rep = pc.CaptureQC(tmp).validate()
            self.assertFalse(rep["ok"])
            self.assertGreaterEqual(rep["duplicate_groups"], 1)


class TestTrimTail(unittest.TestCase):
    def test_trims_repeated_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            raws = Path(tmp) / "source_raws"; raws.mkdir()
            # 1~3 고유, 4~8 = 같은 마지막 페이지 반복(5장)
            for i in range(1, 4):
                _png(raws / f"raw_{i:03d}.png", color=(10 * i, 20, 30))
            for i in range(4, 9):
                _png(raws / f"raw_{i:03d}.png", color=(99, 99, 99))
            r = pc.trim_duplicate_tail(tmp, min_run=2)
            self.assertEqual(r["tail_run"], 5)          # 5장 반복 감지
            self.assertEqual(len(r["trimmed"]), 4)      # 1장 남기고 4장 삭제
            self.assertEqual(r["kept"], 4)              # 3 고유 + 반복 1장

    def test_no_trim_when_unique_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            raws = Path(tmp) / "source_raws"; raws.mkdir()
            for i in range(1, 5):
                _png(raws / f"raw_{i:03d}.png", color=(10 * i, 20, 30))
            r = pc.trim_duplicate_tail(tmp, min_run=2)
            self.assertEqual(len(r["trimmed"]), 0)
            self.assertEqual(r["kept"], 4)


class TestChapterDetector(unittest.TestCase):
    def test_detects_empty_ocr_dividers(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp)
            raws = book / "source_raws"; raws.mkdir()
            ocrd = book / "summary" / "ocr_text"; ocrd.mkdir(parents=True)
            for i in range(1, 11):  # 10장
                _png(raws / f"raw_{i:03d}.png")
                # 3, 7 은 빈 OCR(구분 페이지), 나머지는 내용
                txt = "" if i in (3, 7) else "본문 내용이 충분히 길게 들어 있는 페이지입니다 " * 3
                (ocrd / f"page_{i:03d}.txt").write_text(txt, encoding="utf-8")
            det = pc.ChapterDetector(book)
            self.assertEqual(det.detect(), [3, 7])
            ch = det.scaffold_chapters()
            self.assertEqual(len(ch), 2)
            self.assertEqual(ch[0]["start"], 3)
            self.assertEqual(ch[0]["end"], 6)     # 다음 경계 7 직전
            self.assertEqual(ch[1]["start"], 7)
            self.assertEqual(ch[1]["end"], 10)    # 마지막 페이지


if __name__ == "__main__":
    unittest.main(verbosity=2)
