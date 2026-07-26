import argparse
from types import SimpleNamespace

from chgksuite.cli import ArgparseBuilder
from chgksuite.handouter import pack


def test_pack_skips_multi_handout_files(tmp_path, monkeypatch, capsys):
    multi = tmp_path / "source.hndt"
    multi.write_text(
        """for_question: 1
columns: 3
rows: 1

first
---
for_question: 2
columns: 3
rows: 1

second
""",
        encoding="utf8",
    )
    single = tmp_path / "source_q01.hndt"
    single.write_text(
        """for_question: 1
columns: 3
rows: 1

first
""",
        encoding="utf8",
    )

    processed = []
    merged = []

    def fake_run_hndt(fullpath, args):
        processed.append(fullpath)
        return "source_q01.pdf"

    def fake_pdf_output(pages, filename, compress=True):
        merged.append((pages, filename, compress))

    monkeypatch.setattr(pack, "run_hndt", fake_run_hndt)
    monkeypatch.setattr(pack, "pdf_output", fake_pdf_output)

    args = SimpleNamespace(
        folder=str(tmp_path),
        output_filename_prefix="packed",
        n_teams=2,
        font=None,
        compress_pdf="off",
    )
    pack.pack_handouts(args)

    assert processed == [str(single)]
    assert merged == [(["source_q01.pdf"] * 3, str(tmp_path / "packed_bw.pdf"), False)]
    assert "skipping source.hndt: contains 2 handouts" in capsys.readouterr().out


def test_handouts_subcommands_are_in_workflow_order():
    parser = argparse.ArgumentParser()
    ArgparseBuilder(parser, False).build()
    action = next(a for a in parser._actions if getattr(a, "dest", None) == "action")
    handouts = action.choices["handouts"]
    handouts_action = next(
        a
        for a in handouts._actions
        if getattr(a, "dest", None) == "handoutssubcommand"
    )

    assert list(handouts_action.choices) == [
        "4s2hndt",
        "generate",
        "hndt2pdf",
        "run",
        "install",
        "split_fit",
        "pack",
        "create_html",
        "html2img",
    ]


def test_handouts_optimize_images_cli_defaults_and_override():
    parser = argparse.ArgumentParser()
    ArgparseBuilder(parser, False).build()

    hndt_args = parser.parse_args(["handouts", "hndt2pdf", "source.hndt"])
    split_args = parser.parse_args(["handouts", "split_fit", "source.hndt"])
    hndt_off_args = parser.parse_args(
        ["handouts", "hndt2pdf", "--optimize_images", "off", "source.hndt"]
    )
    split_off_args = parser.parse_args(
        ["handouts", "split_fit", "--optimize_images", "off", "source.hndt"]
    )

    assert hndt_args.optimize_images == "on"
    assert split_args.optimize_images == "on"
    assert hndt_off_args.optimize_images == "off"
    assert split_off_args.optimize_images == "off"
