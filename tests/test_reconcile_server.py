from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from reconcile_server import (
    Candidate,
    DEFAULT_DEST,
    DEFAULT_SOURCES,
    is_candidate_file,
    scan_tree,
    parse_out_blocks,
    resolve_group,
)


REAL_SERVER_ROOTS = [*DEFAULT_SOURCES, DEFAULT_DEST]
BINARY_STYLE_EXTENSION_CASES = {
    ".BIN": ".BIN",
    # No .S41 examples exist in the default roots; .S61 supplies real binary bytes.
    ".S41": ".S61",
    ".S61": ".S61",
    ".000": ".000",
}
TEXT_EXTENSION_CASES = (".LOG", ".MER", ".vit")


def make_candidate(path: Path, content: bytes, *, is_dest: bool = False) -> Candidate:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return Candidate(path=path, size=path.stat().st_size, is_dest=is_dest)


def real_example_path(suffix: str) -> Path:
    for root in REAL_SERVER_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob(f"*{suffix}"):
            if (
                path.is_file()
                and ".git" not in path.parts
                and "__pycache__" not in path.parts
                and is_candidate_file(path)
            ):
                return path
    raise AssertionError(f"No real MERMAID server example found for {suffix}")


def real_example_bytes(suffix: str, *, limit: int | None = None) -> bytes:
    content = real_example_path(suffix).read_bytes()
    if limit is not None:
        content = content[:limit]
    assert content
    return content


def mutate_bytes(content: bytes) -> bytes:
    assert content
    index = min(len(content) - 1, 8)
    replacement = (content[index] + 1) % 256
    return content[:index] + bytes([replacement]) + content[index + 1 :]


def normalized_text_example(suffix: str) -> bytes:
    content = real_example_bytes(suffix, limit=4096).replace(b"\r\n", b"\n")
    lines = [
        line
        for line in content.splitlines(keepends=True)
        if line.strip() and b"mermaid REQUEST:" not in line
    ]
    assert lines
    return b"".join(lines[:8]).rstrip(b"\n") + b"\n\n"


def real_out_block() -> bytes:
    for root in REAL_SERVER_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.out"):
            if not path.is_file() or not is_candidate_file(path):
                continue
            candidate = Candidate(path=path, size=path.stat().st_size)
            parsed = parse_out_blocks(candidate)
            if parsed.conflict is None:
                for block in parsed.blocks:
                    if len(block.splitlines(keepends=True)) > 1:
                        return block
    raise AssertionError("No parseable real .out session block found")


def mutate_out_block_body(block: bytes) -> bytes:
    lines = block.splitlines(keepends=True)
    assert lines
    for index in range(1, len(lines)):
        if lines[index].strip():
            lines[index] = mutate_bytes(lines[index])
            return b"".join(lines)
    return block + b"modified body line\n"


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


def test_text_merge_conflicts_on_different_blank_only_files(tmp_path: Path) -> None:
    source_a = make_candidate(tmp_path / "source_a" / "blank.LOG", b"\n")
    source_b = make_candidate(tmp_path / "source_b" / "blank.LOG", b"\n\n")

    resolution = resolve_group("blank.LOG", [source_a, source_b])

    assert resolution.action == "conflicts"
    assert resolution.conflict is not None
    assert resolution.conflict.difference.left == source_a.path
    assert resolution.conflict.difference.right == source_b.path


def test_scan_order_is_preserved_for_resolution(tmp_path: Path) -> None:
    groups = defaultdict(list)
    seen = set()
    first_root = tmp_path / "z_first_source"
    second_root = tmp_path / "a_second_source"
    make_candidate(first_root / "ordered.out", b"")
    make_candidate(second_root / "ordered.out", b"")

    scan_tree(first_root, is_dest=False, groups=groups, seen=seen)
    scan_tree(second_root, is_dest=False, groups=groups, seen=seen)

    assert [candidate.path.parent.name for candidate in groups["ordered.out"]] == [
        "z_first_source",
        "a_second_source",
    ]


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


def test_real_binary_style_examples_conflict_for_each_allowed_extension(
    tmp_path: Path,
) -> None:
    for suffix, real_suffix in BINARY_STYLE_EXTENSION_CASES.items():
        content = real_example_bytes(real_suffix, limit=4096)
        edited_content = mutate_bytes(content)
        basename = f"real_binary{suffix}"
        source = make_candidate(tmp_path / suffix / "source" / basename, content)
        dest = make_candidate(
            tmp_path / suffix / "dest" / basename,
            content,
            is_dest=True,
        )
        edited_source = make_candidate(
            tmp_path / suffix / "edited_source" / basename,
            edited_content,
        )

        assert is_candidate_file(source.path)
        resolution = resolve_group(basename, [dest, source, edited_source])

        assert resolution.action == "conflicts", suffix
        assert resolution.conflict is not None
        assert resolution.conflict.difference.left == source.path
        assert resolution.conflict.difference.right == edited_source.path
        assert resolution.conflict.difference.left_line != (
            resolution.conflict.difference.right_line
        )


def test_real_text_examples_preserve_spacing_for_each_text_extension(
    tmp_path: Path,
) -> None:
    for suffix in TEXT_EXTENSION_CASES:
        base_content = normalized_text_example(suffix)
        appended_record = f"codex test append for {suffix}\n\n".encode("ascii")
        basename = f"real_text{suffix}"
        source = make_candidate(tmp_path / suffix / "source" / basename, base_content)
        dest = make_candidate(
            tmp_path / suffix / "dest" / basename,
            base_content,
            is_dest=True,
        )
        appended_source = make_candidate(
            tmp_path / suffix / "appended_source" / basename,
            base_content + appended_record,
        )

        assert is_candidate_file(source.path)
        resolution = resolve_group(basename, [dest, source, appended_source])

        assert resolution.action == "merged_deduplicated", suffix
        assert resolution.merged_content == base_content + appended_record
        assert b"\n\n" in resolution.merged_content


def test_real_out_example_conflicts_on_same_session_start_body_edit(
    tmp_path: Path,
) -> None:
    block = real_out_block()
    edited_block = mutate_out_block_body(block)
    source = make_candidate(tmp_path / "source" / "real.out", block)
    dest = make_candidate(
        tmp_path / "dest" / "real.out",
        block + edited_block,
        is_dest=True,
    )

    assert is_candidate_file(source.path)
    resolution = resolve_group("real.out", [source, dest])

    assert resolution.action == "conflicts"
    assert resolution.conflict is not None
    assert resolution.conflict.difference.left == source.path
    assert resolution.conflict.difference.right == dest.path
