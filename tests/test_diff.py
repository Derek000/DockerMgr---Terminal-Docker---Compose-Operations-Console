from dockermgr.utils.diff import unified_text_diff


def test_diff_produces_unified_format():
    d = unified_text_diff("a\n", "b\n", "x", "y")
    assert "--- x" in d
    assert "+++ y" in d
    assert "-a" in d
    assert "+b" in d
