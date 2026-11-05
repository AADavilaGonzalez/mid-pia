"""Integration and CLI tests for the Mid compiler driver and JIT runner."""

import io
import sys
from pathlib import Path

import pytest

from mid.backend.runner import run_jit
from mid.frontend.analyzer import analyzer
from mid.frontend.lexer import lexer
from mid.frontend.parser import parser
from mid.backend.codegen import codegen
from mid.main import create_parser, main

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "examples"


def test_cli_parser_flags_and_mutual_exclusion():
    parser = create_parser()

    # Valid optimization flag parsing
    args = parser.parse_args(["test.mid", "-O"])
    assert args.optimize is True
    assert args.ir is False

    args_long = parser.parse_args(["test.mid", "--optimize"])
    assert args_long.optimize is True

    # Mutually exclusive phase flags should fail when combined
    with pytest.raises(SystemExit):
        parser.parse_args(["test.mid", "-l", "-i"])

    with pytest.raises(SystemExit):
        parser.parse_args(["test.mid", "--lex", "--parse"])


def test_cli_run_assignment(monkeypatch):
    assign_path = str(EXAMPLES / "simple" / "assignment.mid")
    monkeypatch.setattr(sys, "argv", ["mid", assign_path])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_cli_run_stringify_output(monkeypatch, capsys):
    stringify_path = str(EXAMPLES / "complex" / "stringify.mid")
    monkeypatch.setattr(sys, "argv", ["mid", stringify_path])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert captured.out == "2 + 2 is: 4\n"


def test_cli_run_algorithms_output(monkeypatch, capsys):
    alg_path = str(EXAMPLES / "complex" / "algorithms.mid")
    monkeypatch.setattr(sys, "argv", ["mid", alg_path])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "=== Mid Algorithms Suite ===" in captured.out
    assert "After sort:  [-23, -5, 0, 8, 17, 31, 42, 99]" in captured.out
    assert "Sorted verification: PASS" in captured.out
    assert "Binary search for 42 found at index: 6" in captured.out
    assert "Fibonacci(10) = 55" in captured.out
    assert "Suite completed successfully!\n" in captured.out


def test_cli_run_interactive_with_input(monkeypatch, capsys):
    interactive_path = str(EXAMPLES / "complex" / "interactive.mid")
    monkeypatch.setattr(sys, "argv", ["mid", interactive_path])
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO("echo CLI Input Test\ncalc 100 / 4\nquit\n"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert "=== Mid Interactive Input Processor ===" in captured.out
    assert "Echo: CLI Input Test\n" in captured.out
    assert "Result: 25\n" in captured.out
    assert "Total commands executed: 3\n" in captured.out


def test_run_jit_custom_io_streams():
    source = r"""
    fn main() {
        buf: [32]u8;
        full: bool = false;
        line := getline(buf[..], &full);
        if full {
            write("Echo: ");
            write(line);
            write("!\n");
        }
        if eof() {
            write("EOF\n");
        }
    }
    """
    tokens, _ = lexer(source)
    tree, _ = parser(tokens)
    tree, st, _ = analyzer(tree)
    mod = codegen(tree, st)

    in_stream = io.BytesIO(b"Hello World\n")
    out_stream = io.BytesIO()

    exit_code = run_jit(mod, input_stream=in_stream, output_stream=out_stream)
    assert exit_code == 0
    assert out_stream.getvalue() == b"Echo: Hello World!\nEOF\n"
