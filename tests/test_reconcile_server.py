from pathlib import Path

from reconcile_server import Candidate, parse_out_blocks, resolve_group


def make_candidate(path: Path, content: bytes, *, is_dest: bool = False) -> Candidate:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return Candidate(path=path, size=path.stat().st_size, is_dest=is_dest)


def test_parse_out_blocks_keeps_internal_star_lines_in_one_block(tmp_path: Path) -> None:
    candidate = make_candidate(
        tmp_path / "X.out",
        b"\n"
        b"***20221207-05h50mn19: sending cmd from X.cmd\n"
        b"Tx: ...\n"
        b"*** file X.cmd content sent\n"
        b"*** Clear request commands ***\n"
        b"*** try 1/3 failed for file X.cmd\n"
        b"*** too many errors, skipping file X.cmd\n",
    )

    parsed = parse_out_blocks(candidate)

    assert parsed.conflict is None
    assert parsed.blocks == [
        b"***20221207-05h50mn19: sending cmd from X.cmd\n"
        b"Tx: ...\n"
        b"*** file X.cmd content sent\n"
        b"*** Clear request commands ***\n"
        b"*** try 1/3 failed for file X.cmd\n"
        b"*** too many errors, skipping file X.cmd\n"
    ]


def test_out_merge_retains_identical_footer_lines_in_distinct_sessions(
    tmp_path: Path,
) -> None:
    block_a = (
        b"***20221207-05h50mn19: sending cmd from X.cmd\n"
        b"Tx: one\n"
        b"*** Clear request commands ***\n"
        b"\n"
    )
    block_b = (
        b"***20221207-05h51mn19: sending cmd from Y.cmd\n"
        b"Tx: two\n"
        b"*** Clear request commands ***\n"
        b"\n"
    )
    source_a = make_candidate(tmp_path / "source_a" / "same.out", block_a)
    source_b = make_candidate(tmp_path / "source_b" / "same.out", block_b)

    resolution = resolve_group("same.out", [source_a, source_b])

    assert resolution.action == "merged_disjoint"
    assert resolution.merged_content == block_a + block_b
    assert resolution.merged_content.count(b"*** Clear request commands ***\n") == 2


def test_out_merge_appends_and_dedupes_by_session_block(tmp_path: Path) -> None:
    block_a = (
        b"***20221207-05h50mn19: sending cmd from A.cmd\n"
        b"Tx: A\n"
        b"*** Clear request commands ***\n"
        b"\n"
    )
    block_b = (
        b"***20221207-05h51mn19: sending cmd from B.cmd\n"
        b"Tx: B\n"
        b"*** Clear request commands ***\n"
        b"\n"
    )
    source_a = make_candidate(tmp_path / "source_a" / "merge.out", block_a)
    source_b = make_candidate(tmp_path / "source_b" / "merge.out", block_b + block_a)

    resolution = resolve_group("merge.out", [source_a, source_b])

    assert resolution.action == "merged_deduplicated"
    assert resolution.merged_content == block_a + block_b


def test_out_merge_with_existing_destination_is_already_current(tmp_path: Path) -> None:
    block_a = (
        b"***20221207-05h50mn19: sending cmd from A.cmd\n"
        b"Tx: A\n"
        b"*** Clear request commands ***\n"
        b"\n"
    )
    block_b = (
        b"***20221207-05h51mn19: sending cmd from B.cmd\n"
        b"Tx: B\n"
        b"*** try 1/3 failed for file B.cmd\n"
        b"\n"
    )
    source_a = make_candidate(tmp_path / "source_a" / "rerun.out", block_a)
    source_b = make_candidate(tmp_path / "source_b" / "rerun.out", block_b)
    dest = make_candidate(
        tmp_path / "dest" / "rerun.out", block_a + block_b, is_dest=True
    )

    resolution = resolve_group("rerun.out", [source_a, source_b, dest])

    assert resolution.action == "already_current"
    assert resolution.merged_content is None


def test_out_same_session_start_with_different_body_conflicts(tmp_path: Path) -> None:
    source_a = make_candidate(
        tmp_path / "source_a" / "452.020-P-06.out",
        b"***20221207-05h50mn19: sending cmd from 452.020-P-06.cmd\n"
        b'Rx: "exit"\n'
        b"Rx: no answer, exiting\n"
        b"### cmd timeout\n",
    )
    source_b = make_candidate(
        tmp_path / "source_b" / "452.020-P-06.out",
        b"***20221207-05h50mn19: sending cmd from 452.020-P-06.cmd\n"
        b'Rx: "exit"\n'
        b"Rx: no nswer, exiting\n"
        b"### cmd timeout\n",
    )

    resolution = resolve_group("452.020-P-06.out", [source_a, source_b])

    assert resolution.action == "conflicts"
    assert resolution.conflict is not None
    assert resolution.conflict.difference.left_line == b"Rx: no answer, exiting\n"
    assert resolution.conflict.difference.right_line == b"Rx: no nswer, exiting\n"


def test_out_conflict_prefers_source_reference_over_destination_duplicate(
    tmp_path: Path,
) -> None:
    clean_block = (
        b"***20221207-05h50mn19: sending cmd from 452.020-P-06.cmd\n"
        b'Rx: "exit"\n'
        b"Rx: no answer, exiting\n"
        b"### cmd timeout\n"
    )
    edited_block = clean_block.replace(b"no answer", b"no nswer")
    source = make_candidate(
        tmp_path / "source" / "452.020-P-06.out",
        clean_block,
    )
    dest = make_candidate(
        tmp_path / "dest" / "452.020-P-06.out",
        clean_block + edited_block,
        is_dest=True,
    )

    resolution = resolve_group("452.020-P-06.out", [source, dest])

    assert resolution.action == "conflicts"
    assert resolution.conflict is not None
    assert resolution.conflict.difference.left == source.path
    assert resolution.conflict.difference.right == dest.path
    assert resolution.conflict.difference.left_line == b"Rx: no answer, exiting\n"
    assert resolution.conflict.difference.right_line == b"Rx: no nswer, exiting\n"


def test_vit_merge_preserves_blank_spacing_between_appended_blocks(
    tmp_path: Path,
) -> None:
    block_a = b"SESSION A\npayload A\n\n\n"
    block_b = b"SESSION B\npayload B\n\n\n"
    source_a = make_candidate(tmp_path / "source_a" / "merge.vit", block_a)
    source_b = make_candidate(tmp_path / "source_b" / "merge.vit", block_a + block_b)

    resolution = resolve_group("merge.vit", [source_a, source_b])

    assert resolution.action == "merged_deduplicated"
    assert resolution.merged_content == block_a + block_b


def test_text_merge_preserves_blank_spacing_for_log_and_mer(tmp_path: Path) -> None:
    for basename in ("merge.LOG", "merge.MER"):
        source_a = make_candidate(
            tmp_path / basename / "source_a" / basename,
            b"alpha\n\n\n",
        )
        source_b = make_candidate(
            tmp_path / basename / "source_b" / basename,
            b"alpha\n\n\nbeta\n\n",
        )

        resolution = resolve_group(basename, [source_a, source_b])

        assert resolution.action == "merged_deduplicated"
        assert resolution.merged_content == b"alpha\n\n\nbeta\n\n"


def test_request_conflict_prefers_source_reference_over_destination_duplicate(
    tmp_path: Path,
) -> None:
    clean_line = b"mermaid REQUEST: 2022-01-01T00:00:00 clean\n"
    edited_line = b"mermaid REQUEST: 2022-01-01T00:00:00 edited\n"
    dest = make_candidate(
        tmp_path / "dest" / "requests.LOG",
        clean_line + edited_line,
        is_dest=True,
    )
    source = make_candidate(tmp_path / "source" / "requests.LOG", clean_line)

    resolution = resolve_group("requests.LOG", [dest, source])

    assert resolution.action == "conflicts"
    assert resolution.conflict is not None
    assert resolution.conflict.difference.left == source.path
    assert resolution.conflict.difference.right == dest.path
    assert resolution.conflict.difference.left_line == clean_line
    assert resolution.conflict.difference.right_line == edited_line


def test_binary_conflict_prefers_source_reference_over_destination_duplicate(
    tmp_path: Path,
) -> None:
    dest = make_candidate(
        tmp_path / "dest" / "sample.BIN",
        b"clean\n",
        is_dest=True,
    )
    source = make_candidate(tmp_path / "source" / "sample.BIN", b"clean\n")
    edited_source = make_candidate(
        tmp_path / "edited_source" / "sample.BIN",
        b"clxan\n",
    )

    resolution = resolve_group("sample.BIN", [dest, source, edited_source])

    assert resolution.action == "conflicts"
    assert resolution.conflict is not None
    assert resolution.conflict.difference.left == source.path
    assert resolution.conflict.difference.right == edited_source.path
    assert resolution.conflict.difference.left_line == b"clean\n"
    assert resolution.conflict.difference.right_line == b"clxan\n"
