from __future__ import annotations

from rune_hunter.config import AppConfig, Roi


def test_defaults_reflect_reference_layout(config: AppConfig):
    """예시 프로그램과 같은 구성: 사냥기/보스기 + 버프 여러 개."""
    assert config.attack.hunt.label == "사냥기"
    assert config.attack.boss.label == "보스기"
    assert len(config.attack.buffs) >= 6
    assert config.keys.jump == "ALT"
    assert config.keys.rope == "A"


def test_roi_to_pixels_clamped():
    roi = Roi(0.25, 0.5, 0.5, 0.5)
    assert roi.to_pixels(1000, 800) == (250, 400, 500, 400)
    huge = Roi(0.9, 0.9, 1.0, 1.0)
    x, y, w, h = huge.to_pixels(100, 100)
    assert x + w <= 100 and y + h <= 100


def test_save_and_load_roundtrip(tmp_path, config: AppConfig):
    config.attack.hunt.key = "V"
    config.attack.hunt.interval = 0.07
    config.attack.buffs[2].enabled = True
    config.attack.buffs[2].key = "NUM5"
    config.rune.arrow_roi = Roi(0.3, 0.05, 0.4, 0.2)
    config.rune.detect_scale = 0.5
    config.general.window_titles = ["나루", "MapleStory"]

    path = config.save(tmp_path / "p.json")
    loaded = AppConfig.load(path)

    assert loaded.attack.hunt.key == "V"
    assert loaded.attack.hunt.interval == 0.07
    assert loaded.attack.buffs[2].key == "NUM5"
    assert loaded.attack.buffs[2].enabled is True
    assert loaded.rune.arrow_roi.w == 0.4
    assert loaded.rune.detect_scale == 0.5
    assert loaded.general.window_titles == ["나루", "MapleStory"]
    assert loaded.rune.arrow_templates["LEFT"] == "arrow_left.png"


def test_partial_json_uses_defaults():
    """예전 버전 프로필(필드 일부만 존재)도 열려야 한다."""
    loaded = AppConfig.from_dict({"attack": {"hunt": {"key": "Z"}}, "unknown": 1})
    assert loaded.attack.hunt.key == "Z"
    assert loaded.attack.hunt.label == "사냥기"
    assert loaded.rune.enabled is True
    assert loaded.general.start_hotkey == "F1"


def test_missing_file_returns_defaults(tmp_path):
    loaded = AppConfig.load(tmp_path / "nope.json")
    assert loaded.attack.hunt.key == "U"


def test_template_path_resolution(tmp_path, config: AppConfig):
    config.rune.template_dir = str(tmp_path)
    assert config.template_path("rune.png") == tmp_path / "rune.png"
    absolute = tmp_path / "abs" / "x.png"
    assert config.template_path(str(absolute)) == absolute
