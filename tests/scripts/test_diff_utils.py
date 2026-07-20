from scripts.common.diff_utils import ChangedFile, build_diff_bundle, is_excluded, truncate


def test_is_excluded_matches_glob():
    assert is_excluded("app/build/generated/Foo.kt", ["**/build/**"])
    assert not is_excluded("app/src/main/kotlin/Foo.kt", ["**/build/**"])


def test_truncate_keeps_head_and_tail_under_limit():
    text = "A" * 1000
    result = truncate(text, max_chars=100)
    assert len(result) <= 100
    assert result.startswith("A")
    assert "[TRUNCATED]" in result


def test_truncate_noop_when_under_limit():
    text = "short text"
    assert truncate(text, max_chars=1000) == text


def test_build_diff_bundle_respects_global_cap():
    files = [
        ChangedFile(filename=f"File{i}.kt", status="modified", patch="X" * 500, additions=5, deletions=1)
        for i in range(10)
    ]
    bundle = build_diff_bundle(files, max_total_chars=1200, max_chars_per_file=500, max_files=10)
    assert len(bundle) <= 1200 + 200  # allow for the "omitted" notice
    assert "omitted" in bundle


def test_build_diff_bundle_respects_max_files():
    files = [
        ChangedFile(filename=f"File{i}.kt", status="modified", patch="short", additions=1, deletions=0)
        for i in range(5)
    ]
    bundle = build_diff_bundle(files, max_total_chars=100000, max_chars_per_file=500, max_files=2)
    assert "File0.kt" in bundle
    assert "File1.kt" in bundle
    assert "File2.kt" not in bundle
