"""캡처 표준 규칙 엔진 단위/기능 테스트 (stdlib unittest, 추가 의존성 0).

실행:  book-capture/.venv/bin/python tests/test_capture_standard.py
  - 단위 테스트: DisplaySpec / CaptureStandardV1 (순수 로직, 하드웨어 무관)
  - 기능 테스트: mac_displays 실기 감지 (macOS 에서만, 없으면 skip)
"""
import os
import sys
import platform
import unittest

# book-capture/ 를 path 에 → `import bookcapture` 가능
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bookcapture import capture_standard as cs


def D(name, w, h, sc, builtin=False, main=False, did=1):
    return cs.DisplaySpec(name, w, h, sc, builtin=builtin, main=main, display_id=did)


class TestDisplaySpec(unittest.TestCase):
    """모니터 한 대의 캡처 능력 판정 — 기기/모니터 무관 상대 계산."""

    def test_backing_width(self):
        self.assertEqual(D("14 내장", 1512, 982, 2.0).backing_width, 3024)
        self.assertEqual(D("외장 1x", 1920, 1200, 1.0).backing_width, 1920)
        self.assertEqual(D("외장 HiDPI", 1280, 800, 2.0).backing_width, 2560)

    def test_page_px_spread_vs_single(self):
        d = D("외장 1x", 1920, 1200, 1.0)
        self.assertEqual(d.page_px(2), 960)    # 양면 = 절반
        self.assertEqual(d.page_px(1), 1920)   # 단면 = 전체 백킹

    def test_meets_spread(self):
        # 16"·14"·4K 2x → 양면 충족 / 외장 1x·HiDPI·11" → 양면 미달
        self.assertTrue(D("16 내장", 1728, 1117, 2.0).meets(2))   # 3456→1728
        self.assertTrue(D("14 내장", 1512, 982, 2.0).meets(2))    # 3024→1512
        self.assertTrue(D("4K 외장", 1920, 1080, 2.0).meets(2))   # 3840→1920
        self.assertFalse(D("외장 1x", 1920, 1200, 1.0).meets(2))  # 1920→960
        self.assertFalse(D("외장 HiDPI", 1280, 800, 2.0).meets(2))# 2560→1280
        self.assertFalse(D("11 내장", 1170, 780, 2.0).meets(2))   # 2340→1170

    def test_meets_single(self):
        self.assertTrue(D("외장 1x", 1920, 1200, 1.0).meets(1))   # 1920≥1400
        self.assertTrue(D("외장 HiDPI", 1280, 800, 2.0).meets(1)) # 2560≥1400
        self.assertFalse(D("저해상", 1000, 700, 1.0).meets(1))     # 1000<1400

    def test_best_layout(self):
        self.assertEqual(D("14 내장", 1512, 982, 2.0).best_layout(), "spread")
        self.assertEqual(D("외장 1x", 1920, 1200, 1.0).best_layout(), "single")
        self.assertIsNone(D("저해상", 1000, 700, 1.0).best_layout())

    def test_boundary_exact_1400(self):
        # 양면 정확히 1400px → 충족(>=). 백킹 2800 = 1400pt×2x
        self.assertTrue(D("경계 양면", 1400, 1000, 2.0).meets(2))   # 2800→1400
        # 백킹 2798 → 1399 < 1400 → 미달
        self.assertFalse(D("경계-2", 1399, 1000, 2.0).meets(2))    # 2798→1399
        # 단면 정확히 1400px → 충족
        self.assertTrue(D("경계 단면", 1400, 1000, 1.0).meets(1))

    def test_kind(self):
        self.assertEqual(D("x", 1512, 982, 2.0, builtin=True).kind(), "내장")
        self.assertEqual(D("x", 1920, 1200, 1.0, builtin=False).kind(), "외장")


class TestCaptureStandardV1(unittest.TestCase):
    """규칙 엔진 — 여러 모니터 판정·추천·조치."""

    def setUp(self):
        self.std = cs.CaptureStandardV1()

    def test_required_backing_width(self):
        self.assertEqual(self.std.required_backing_width(2), 2800)
        self.assertEqual(self.std.required_backing_width(1), 1400)

    def test_evaluate_meets_and_fields(self):
        e = self.std.evaluate(D("14 내장", 1512, 982, 2.0, builtin=True), 2)
        self.assertTrue(e["meets"])
        self.assertEqual(e["page_px"], 1512)
        self.assertEqual(e["single_page_px"], 3024)
        self.assertEqual(e["best_layout"], "spread")
        self.assertEqual(e["advice"], [])   # 충족이면 조치 없음

    def test_evaluate_substandard_has_advice(self):
        e = self.std.evaluate(D("외장 1x", 1920, 1200, 1.0), 2)
        self.assertFalse(e["meets"])
        self.assertTrue(e["meets_single"])
        self.assertEqual(e["single_page_px"], 1920)
        self.assertTrue(any("단면" in a for a in e["advice"]))

    def test_plan_recommends_best_meeting(self):
        internal = D("14 내장", 1512, 982, 2.0, builtin=True, did=1)
        external = D("외장 1x", 1920, 1200, 1.0, builtin=False, did=2)
        p = self.std.plan([internal, external], 2)
        self.assertTrue(p["any_meets"])
        self.assertFalse(p["override_needed"])
        self.assertEqual(p["chosen"]["display_id"], 1)   # 내장 추천

    def test_plan_prefer_id_honored_when_meets(self):
        internal = D("14 내장", 1512, 982, 2.0, builtin=True, did=1)
        big_ext = D("4K 외장", 1920, 1080, 2.0, builtin=False, did=2)  # 양면 1920 충족
        # 사용자가 외장(충족)을 선택 → 외장 존중(외장 강제 아님 = 선택 존중)
        p = self.std.plan([internal, big_ext], 2, prefer_id=2)
        self.assertEqual(p["chosen"]["display_id"], 2)
        self.assertIn("선택", p["chosen_reason"])

    def test_plan_prefer_id_substandard_falls_back(self):
        internal = D("14 내장", 1512, 982, 2.0, builtin=True, did=1)
        external = D("외장 1x", 1920, 1200, 1.0, builtin=False, did=2)
        # 외장(미달) 선호 → 무시하고 충족 모니터(내장)로 폴백
        p = self.std.plan([internal, external], 2, prefer_id=2)
        self.assertEqual(p["chosen"]["display_id"], 1)

    def test_plan_all_substandard_blocks(self):
        external = D("외장 1x", 1920, 1200, 1.0, did=2)
        p = self.std.plan([external], 2, prefer_id=2)
        self.assertFalse(p["any_meets"])
        self.assertIsNone(p["chosen"])
        self.assertTrue(p["override_needed"])
        # 단면 조치에 단면 픽셀(1920) 이 나와야 함(양면 960 아님)
        self.assertTrue(any("1920px" in a for a in p["advice"]))

    def test_plan_tiebreak_prefers_builtin(self):
        a = D("외장 4K", 1920, 1080, 2.0, builtin=False, did=2)   # 양면 1920
        b = D("내장 동급", 1920, 1200, 2.0, builtin=True, did=1)  # 양면 1920 (동률)
        p = self.std.plan([a, b], 2)
        self.assertEqual(p["chosen"]["display_id"], 1)   # 동률 → 내장 우선

    def test_plan_empty_no_crash(self):
        p = self.std.plan([], 2)
        self.assertFalse(p["any_meets"])
        self.assertIsNone(p["chosen"])


@unittest.skipUnless(platform.system() == "Darwin", "macOS 전용 (Quartz 실기 감지)")
class TestMacDisplaysLive(unittest.TestCase):
    """기능 테스트 — 실제 이 Mac 의 모니터 감지 + 준비상태 판정(하드웨어 의존)."""

    def test_detect_and_readiness(self):
        from bookcapture import mac_displays
        disps = mac_displays.detect_displays()
        self.assertGreaterEqual(len(disps), 1, "최소 1개 디스플레이는 감지돼야 함")
        for d in disps:
            self.assertGreater(d.width_pt, 0)
            self.assertGreaterEqual(d.scale, 1.0)
            self.assertIsInstance(d.backing_width, int)
        rd = mac_displays.capture_readiness(2)
        for k in ("ok", "reason", "plan", "lines"):
            self.assertIn(k, rd)
        # 리포트 출력 (사람이 눈으로 현재 모니터 상태 확인)
        print("\n----- 라이브 캡처 준비상태 (양면 2p) -----")
        print("ok:", rd["ok"], "|", rd["reason"])
        for ln in rd["lines"]:
            print(ln)
        # 내장 Retina 가 있으면 반드시 양면 충족이어야(1512pt 2x 이상)
        internal = [e for e in rd["plan"]["evaluations"] if e["builtin"]]
        for e in internal:
            if e["scale"] >= 2 and e["width_pt"] >= 1400:
                self.assertTrue(e["meets"], "내장 Retina(≥1400pt 2x)는 양면 충족해야 함")


if __name__ == "__main__":
    unittest.main(verbosity=2)
