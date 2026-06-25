import pytest

import scraper.human_behavior as hb
from scraper.human_behavior import _bezier_points, move_mouse_humanlike, wander_mouse
from scraper.navigate import click_listing, BlockedError
from scraper.browser import BrowserManager
from scraper.config import PX_SENSOR_PATTERNS


# --- human mouse movement ---

def test_bezier_path_ends_exactly_at_target():
    pts = _bezier_points(0, 0, 100, 200, 20)
    assert len(pts) == 20
    assert abs(pts[-1][0] - 100) < 1e-6 and abs(pts[-1][1] - 200) < 1e-6


class _FakeMouse:
    def __init__(self): self.moves = []
    def move(self, x, y): self.moves.append((x, y))


class _FakeMousePage:
    def __init__(self): self.mouse = _FakeMouse()


def test_move_mouse_humanlike_curves_to_target(monkeypatch):
    monkeypatch.setattr(hb.time, "sleep", lambda *a, **k: None)
    p = _FakeMousePage()
    move_mouse_humanlike(p, 300, 400, start=(0, 0), steps=15)
    assert len(p.mouse.moves) == 15
    assert abs(p.mouse.moves[-1][0] - 300) < 1e-6 and abs(p.mouse.moves[-1][1] - 400) < 1e-6
    # not a straight line — at least one midpoint deviates from the s->e diagonal
    assert any(abs(y - x * 400 / 300) > 1.0 for x, y in p.mouse.moves[:-1])


def test_wander_mouse_emits_moves(monkeypatch):
    monkeypatch.setattr(hb.time, "sleep", lambda *a, **k: None)
    p = _FakeMousePage()
    wander_mouse(p, moves=3)
    assert len(p.mouse.moves) > 0


# --- click_listing (real-link navigation) ---

class _El:
    def __init__(self): self.clicked = False
    def click(self, timeout=None): self.clicked = True


def test_click_listing_lookuperror_when_anchor_absent():
    class P:
        def query_selector(self, sel): return None
    with pytest.raises(LookupError):
        click_listing(P(), "12345")


def test_click_listing_success_when_detail_renders():
    el = _El()
    class P:
        url = "https://www.sahibinden.com/ilan/x-12345/detay"
        def query_selector(self, sel): return el
        def wait_for_selector(self, sel, timeout=None): return True
    assert click_listing(P(), "12345") is True
    assert el.clicked is True


def test_click_listing_raises_blocked_on_block_timeout():
    class P:
        url = "https://www.sahibinden.com/ilan/x-12345/detay"
        def query_selector(self, sel): return _El()
        def wait_for_selector(self, sel, timeout=None): raise Exception("Timeout")
        def content(self):
            return '<div class="too-many-requests">Olağan dışı erişim tespit ettik</div>'
    with pytest.raises(BlockedError):
        click_listing(P(), "12345")


# --- PerimeterX sensor arm/disarm ---

def test_arm_disarm_px_routes_all_patterns_and_is_idempotent():
    bm = BrowserManager()
    routed, unrouted = [], []
    class P:
        def route(self, pat, handler): routed.append(pat)
        def unroute(self, pat, handler): unrouted.append(pat)
    p = P()

    bm.disarm_px(p)
    assert bm._px_blocked is True
    assert len(routed) == len(PX_SENSOR_PATTERNS)
    bm.disarm_px(p)  # idempotent — no double-routing
    assert len(routed) == len(PX_SENSOR_PATTERNS)

    bm.arm_px(p)
    assert bm._px_blocked is False
    assert len(unrouted) == len(PX_SENSOR_PATTERNS)
