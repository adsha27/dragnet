import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dragnet.tailoring.unicode_normalize import normalize


def test_en_dash():
    assert normalize("2020–2024") == "2020-2024"


def test_em_dash():
    assert normalize("Go—Python backend") == "Go-Python backend"


def test_smart_quotes():
    assert normalize("“Hello” and ‘world’") == '"Hello" and \'world\''


def test_ellipsis():
    assert normalize("more…") == "more..."


def test_bullet():
    assert normalize("• item") == "- item"


def test_nbsp():
    assert normalize("hello world") == "hello world"


def test_zero_width_chars():
    assert normalize("a​b‌c‍d") == "abcd"


def test_clean_passthrough():
    s = "plain ASCII text with numbers 123 and symbols !@#"
    assert normalize(s) == s


def test_combined():
    messy = "“Backed by Go—Python” • 2020–2024"
    assert normalize(messy) == '"Backed by Go-Python" - 2020-2024'
