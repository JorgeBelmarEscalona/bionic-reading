import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import Bionic


def test_short_word():
    assert Bionic.bolding("cat") == "<b>c</b>at"


def test_long_word():
    result = Bionic.bolding("reading")
    assert result.startswith("<b>") and "</b>" in result


def test_punctuation():
    text = "Hello, world!"
    assert Bionic.bolding(text) == "<b>Hel</b>lo, <b>wor</b>ld!"
