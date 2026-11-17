from asli.unmatched_log import UnmatchedLog


def test_counts_names_case_insensitively(tmp_path):
    log = UnmatchedLog(tmp_path / "logs" / "unmatched.sqlite")
    log.record("Thepla")
    log.record(" thepla ")
    log.record("Misal pav")
    log.record("   ")
    assert log.most_common() == [("thepla", 2), ("misal pav", 1)]
