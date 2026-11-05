"""Semantic analyzer tests runnable with pytest"""

import io
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from mid.frontend.analyzer import analyzer, valid_cast
from mid.frontend.lexer import lexer
from mid.frontend.parser import parser
from mid.types import ast as A
from mid.types.sem_type import BOOL, ERROR, F32, I32, U8, U32, USIZE, VOID, SemType
from mid.types.symbol_table import ScopeKind, Symbol, SymbolKind, SymbolTable

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "examples"


def analyze(source, allow_syntax_errors=False):
    """Lex, parse and analyze. Returns (ast, symbol table, analyzer errors)."""
    tokens, lexer_errors = lexer(source)
    tree, parser_errors = parser(tokens)
    if not allow_syntax_errors:
        assert lexer_errors + parser_errors == [], [str(e) for e in lexer_errors + parser_errors]
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(output):
        result, table, errors = analyzer(tree)
    # The analyzer returns its errors; it must not print anything itself.
    assert output.getvalue() == ""
    assert result is tree
    return tree, table, errors


def codes(source):
    return [error.code for error in analyze(source)[2]]


def valid(source):
    tree, table, errors = analyze(source)
    assert errors == [], [str(e) for e in errors]
    return tree, table


def in_main(body):
    """Codes produced by ``body`` placed inside ``fn main``."""
    return codes("fn main() { " + body + " }")


def main_stmts(source):
    """Analyze a valid program and return the statements of main."""
    tree, _ = valid(source)
    main = next(d for d in tree.program.decl if isinstance(d, A.FnDecl) and d.name == "main")
    return main.block.stmts


# ------------------------------------------------------------ symbol table

def test_symbol_table_scopes_lookup_and_no_shadowing():
    table = SymbolTable()
    assert table.lookup("u8").kind == SymbolKind.TYPE
    assert table.lookup("write").kind == SymbolKind.BUILTIN_FUNCTION
    assert table.lookup("write").parameters == [U8.slice()]
    assert table.lookup("write").return_type == VOID

    x = Symbol("x", SymbolKind.VARIABLE, type=I32, mutable=True)
    assert table.define(x) is None
    assert x.is_global

    table.enter_scope(ScopeKind.FUNCTION)
    assert table.lookup("x") is x  # visible from nested scopes
    assert table.define(Symbol("x", SymbolKind.VARIABLE)) is x  # shadowing rejected
    y = Symbol("y", SymbolKind.VARIABLE, type=U8)
    assert table.define(y) is None and not y.is_global
    table.exit_scope()

    assert table.lookup("y") is None  # left the scope
    assert table.define(Symbol("y", SymbolKind.VARIABLE)) is None  # sibling reuse is fine
    assert table.define(Symbol("i32", SymbolKind.VARIABLE)).kind == SymbolKind.TYPE
    assert len(table.global_scope.children) == 1


# ------------------------------------------------------------ examples

def test_valid_examples_have_no_errors():
    for path in [
        EXAMPLES / "simple" / "assignment.mid",
        EXAMPLES / "complex" / "stringify.mid",
        EXAMPLES / "complex" / "algorithms.mid",
        EXAMPLES / "complex" / "interactive.mid",
    ]:
        valid(path.read_text())


def test_error_example_reports_each_commented_error():
    source = (EXAMPLES / "errors" / "semantic_errors.mid").read_text()
    expected = []
    for line_number, line in enumerate(source.splitlines(), 1):
        match = re.search(r"//\s*(\d+):", line)
        if match:
            expected.append((line_number, int(match.group(1))))
    _, _, errors = analyze(source)
    found = [(e.span.start.line, e.code) for e in errors]
    assert sorted(code for code in found if code[1] != 11) == sorted(expected)
    assert [e.code for e in errors].count(11) == 1  # no main


# ------------------------------------------------------------ main

def test_main_is_required_with_the_right_signature():
    assert codes("x := 1;") == [11]
    assert codes("") == [11]
    assert codes("fn main(a: i32) { }") == [11]
    assert codes("fn main() -> i32 { return 0; }") == [11]
    assert codes("main := 1;") == [11]
    valid("fn main() { }")


# ------------------------------------------------------------ names and scopes

def test_undeclared_names_and_use_before_declaration():
    assert in_main("x = 1;") == [1]
    assert in_main("y := x; x := 1;") == [1]
    assert in_main("x := x;") == [1]
    assert in_main("print(\"hi\");") == [1]
    assert in_main("if true { z := 1; } z = 2;") == [1]  # z left its scope


def test_globals_are_predeclared():
    # Functions may use globals and functions declared later.
    valid("fn main() { x = later(); } fn later() -> i32 { return x; } x: i32 = 1;")
    # Explicitly typed globals may be read by earlier initializers...
    valid("a: i32 = b; b: i32 = 1; fn main() { }")
    # ... but a ':=' global has no type until its initializer runs.
    assert codes("a := b; b := 1; fn main() { }") == [1]
    valid("b := 1; a := b; fn main() { }")
    # Global initializers do not need to be constant.
    valid("n := f(); fn f() -> i32 { return 3; } fn main() { }")


def test_duplicates_and_shadowing_are_rejected():
    assert codes("x := 1; x := 2; fn main() { }") == [2]
    assert codes("fn f() { } fn f() { } fn main() { }") == [2]
    assert codes("write := 1; fn main() { }") == [2]
    assert codes("fn eof() -> bool { return true; } fn main() { }") == [2]
    assert codes("x := 1; fn f(x: i32) { } fn main() { }") == [2]
    assert codes("fn f(a: i32, a: u8) { } fn main() { }") == [2]
    assert in_main("x := 1; if true { x := 2; }") == [2]
    assert in_main("u8 := 1;") == [2]
    assert in_main("main := 1;") == [2]
    # Sibling blocks do not see each other.
    assert in_main("if true { y := 1; } else { y := 2; } loop { y := 3; break; }") == []


# ------------------------------------------------------------ types and literals

def test_unknown_and_invalid_types():
    assert in_main("x: byte;") == [3]
    assert in_main("x: [0]u8;") == [3]
    assert codes("fn f(a: ^foo) -> bar { } fn main() { }") == [3, 3]
    assert in_main("x := 1; y: x;") == [3]  # a variable is not a type
    valid("fn main() { a: ^[3][]u8; b: [][4]^bool; }")


def test_integer_literals_take_their_type_from_context():
    stmts = main_stmts(
        "fn main() { a: u8 = 255; b: usize = 0; c: u32 = 4294967295; d := 1;"
        " e: i32 = -2147483648; f: usize = 18446744073709551615; g := b + 1; }"
    )
    assert [s.ty for s in stmts] == [U8, USIZE, U32, I32, I32, USIZE, USIZE]
    assert stmts[0].init.ty == U8
    assert stmts[4].init.ty == I32 and stmts[4].init.value.ty == I32
    assert stmts[6].init.right.ty == USIZE


def test_literal_arithmetic_and_defaults():
    stmts = main_stmts("fn main() { a: u8 = 1; b := 1 + 2 + a; c := 2 + 2; d: u32 = (3 * 4) % 5; }")
    assert [s.ty for s in stmts] == [U8, U8, I32, U32]
    assert stmts[1].init.left.ty == U8


def test_literals_out_of_range_or_wrong_kind():
    assert in_main("a: u8 = 256;") == [4]
    assert in_main("a: u32 = -1;") == [4]
    assert in_main("a := 2147483648;") == [4]
    assert in_main("a: f32 = 1;") == [4]
    assert in_main("a: i32 = 1.5;") == [4]
    assert in_main("a: bool = 1;") == [4]
    valid("fn main() { a: f32 = 1.5; b: u8 = 'a'; c: []u8 = \"hi\"; d: bool = false; }")


def test_no_implicit_conversions_between_widths():
    assert in_main("a: u8 = 1; b: i32 = 2; a = b;") == [4]
    assert in_main("a: u8 = 1; b: i32 = 2; c := a + b;") == [5]
    assert in_main("a: u32 = 1; b: usize = a;") == [4]
    assert in_main("a: u8 = 1; b: i32 = a as i32;") == []


# ------------------------------------------------------------ operators

@pytest.mark.parametrize("body, expected", [
    ("x := !true;", []),
    ("x := !1;", [5]),
    ("x := -1.5;", []),
    ("u: u32 = 1; x := -u;", [5]),
    ("i: i32 = 1; x := -i;", []),
    ("x := 1 % 2;", []),
    ("x := 1.0 % 2.0;", [5]),
    ("x := 1.0 + 2.0 * 3.0;", []),
    ("x := 1.0 + 2;", [5]),
    ("x := true + false;", [5]),
    ("x := true == false;", []),
    ("x := 1.0 < 2.0;", []),
    ("x := true < false;", [5]),
    ("x := 1 < 2 && 3 >= 4 || !(5 != 6);", []),
    ("x := 1 && true;", [5]),
    ("p: ^i32; q: ^i32; b := p == q;", [5]),
    ("s: []u8; t: []u8; b := s != t;", [5]),
    ("p: ^i32; q := p + 1;", [5]),
])
def test_operator_rules(body, expected):
    assert in_main(body) == expected


def test_address_and_dereference():
    stmts = main_stmts("fn main() { x: i32; p := &x; y := p^; a: [3]u8; q := &a[0]; }")
    assert stmts[1].ty == I32.pointer()
    assert stmts[2].ty == I32
    assert stmts[4].ty == U8.pointer()
    assert in_main("p := &1;") == [9]
    assert in_main("x: i32; y := x^;") == [9]
    assert in_main("p := &main;") == [7]


# ------------------------------------------------------------ casts

def test_cast_table():
    integers = ["u8", "i32", "u32", "usize"]
    for a in integers:
        for b in integers + ["f32", "bool"]:
            assert valid_cast(SemType(a), SemType(b)), (a, b)
        assert valid_cast(F32, SemType(a)) and valid_cast(BOOL, SemType(a))
    assert not valid_cast(F32, BOOL)
    assert not valid_cast(BOOL, F32)
    assert valid_cast(I32.pointer(), U8.pointer())
    assert valid_cast(U8.pointer(), U32.pointer())
    assert not valid_cast(I32.pointer(), U32.pointer())
    assert not valid_cast(I32.pointer(), USIZE)
    assert not valid_cast(USIZE, I32.pointer())
    assert not valid_cast(SemType("u8", ()).slice(), U8.pointer())


def test_cast_expressions():
    stmts = main_stmts("fn main() { a := 300 as u8; b := -1 as u32; c := 1.5 as i32; d := 2 as bool; }")
    assert [s.ty for s in stmts] == [U8, U32, I32, BOOL]
    assert stmts[0].init.value.ty == I32  # cast operands default to i32
    assert in_main("x := 1.5 as bool;") == [8]
    assert in_main("x := true as f32;") == [8]
    assert in_main("p: ^i32; q := p as ^u32;") == [8]
    assert in_main("p: ^i32; q := p as ^u8 as ^u32;") == []
    assert in_main("a: [3]u8; s := a as []u8;") == [8]
    assert in_main("p: ^i32; n := p as usize;") == [8]


# ------------------------------------------------------------ assignments

def test_assignment_targets():
    valid("g: i32; fn main() { x: i32; x = 1; g = 2; a: [3]u8; a[0] = 1; p := &x; p^ = 3;"
          " s := a[..]; s[1] = 2; }")
    assert in_main("1 = 2;") == [6]
    assert in_main("main = 1;") == [6]
    assert in_main("eof = true;") == [6]
    assert in_main("u8 = 1;") == [6]
    assert in_main("a: [3]u8; a.len = 2;") == [6]
    assert in_main("x: i32; x + 1 = 2;") == [6]
    assert codes("fn f() -> i32 { return 1; } fn main() { f() = 2; }") == [6]


def test_compound_assignment():
    valid("fn main() { x: u8 = 1; x += 2; x -= 1; x *= 3; x /= 2; x %= 2; f: f32 = 1.0; f *= 2.0; }")
    assert in_main("f: f32 = 1.0; f %= 2.0;") == [5]
    assert in_main("b: bool; b += true;") == [5]
    assert in_main("x: u8; y: i32; x += y;") == [5]


# ------------------------------------------------------------ calls

def test_calls():
    valid("fn add(a: i32, b: i32) -> i32 { return a + b; }"
          " fn main() { x := add(1, 2); write(\"hi\"); e := eof();"
          " buf: [8]u8; ok: bool; line := getline(buf[..], &ok); }")
    assert codes("fn f(a: i32) { } fn main() { f(); }") == [7]
    assert codes("fn f(a: i32) { } fn main() { f(1, 2); }") == [7]
    assert codes("fn f(a: u8) { } fn main() { x: i32; f(x); }") == [7]
    assert in_main("x := write(\"a\");") == [7]       # void used as a value
    assert in_main("x := 1; x();") == [7]             # not a function
    assert in_main("y := main;") == [7]               # function as a value
    assert codes("fn f(s: []u8) { } fn main() { a: [3]u8; f(a); }") == [7]  # no array -> slice
    assert codes("fn f(s: []u8) { } fn main() { a: [3]u8; f(a[..]); }") == []


# ------------------------------------------------------------ indexing, slices, .len

def test_index_slice_and_len():
    stmts = main_stmts(
        "fn main() { a: [4]u8; s := a[..]; t := s[1..]; u := a[..2]; v := a[1..3];"
        " i: u8 = 0; w := a[i]; n := a.len; m := s.len; x := \"abc\".len; }"
    )
    assert [s.ty for s in stmts[1:5]] == [U8.slice()] * 4
    assert stmts[6].ty == U8
    assert stmts[7].ty == USIZE and stmts[8].ty == USIZE and stmts[9].ty == USIZE
    assert in_main("x: i32; y := x[0];") == [9]
    assert in_main("a: [4]u8; y := a[1.5];") == [9]
    assert in_main("a: [4]u8; y := a[true..];") == [9]
    assert in_main("x: i32; y := x[1..];") == [9]
    assert in_main("a: [4]u8; y := a.size;") == [9]
    assert in_main("x: i32; y := x.len;") == [9]
    assert codes("fn f() -> [3]u8 { a: [3]u8; return a; } fn main() { s := f()[..]; }") == [9]


# ------------------------------------------------------------ control flow

def test_loop_context():
    valid("fn main() { loop { break; } loop { if true { continue; } break; } }")
    assert in_main("break;") == [10]
    assert in_main("continue;") == [10]
    assert in_main("if true { break; }") == [10]


def test_return_values():
    assert in_main("return;") == []
    assert in_main("return 1;") == [10]
    assert codes("fn f() -> i32 { return; } fn main() { }") == [10]
    assert codes("fn f() -> u8 { return 1; } fn main() { }") == []
    assert codes("fn f() -> u8 { x: i32; return x; } fn main() { }") == [4]


@pytest.mark.parametrize("body, ok", [
    ("return 1;", True),
    ("x := 1;", False),
    ("if true { return 1; }", False),
    ("if true { return 1; } else { return 2; }", True),
    ("if true { return 1; } else if false { return 2; }", False),
    ("if true { return 1; } else if false { return 2; } else { return 3; }", True),
    ("loop { }", True),
    ("loop { break; }", False),
    ("loop { if true { break; } }", False),
    ("loop { loop { break; } }", True),
    ("if true { } return 1;", True),
])
def test_every_path_must_return(body, ok):
    result = codes("fn f() -> i32 { " + body + " } fn main() { }")
    assert result == ([] if ok else [10])


def test_conditions_must_be_bool():
    assert in_main("if 1 { }") == [4]
    assert in_main("x: i32; if x { } else if true { }") == [4]
    assert in_main("if 1 < 2 { }") == []


# ------------------------------------------------------------ annotations

def test_ast_is_annotated_with_types_and_symbols():
    tree, table = valid("g: u32 = 1; fn main() { x := g + 2; y := x; }")
    g_decl, main = tree.program.decl
    x_decl, y_decl = main.block.stmts
    assert g_decl.ty == U32 and g_decl.symbol.is_global
    assert g_decl.type.ty == U32
    assert x_decl.ty == U32 and x_decl.init.ty == U32
    assert x_decl.init.left.symbol is g_decl.symbol
    assert y_decl.init.symbol is x_decl.symbol
    assert not x_decl.symbol.is_global
    assert main.symbol is table.global_scope.lookup("main")
    assert table.global_scope.lookup("main").kind == SymbolKind.FUNCTION
    assert table.current_scope is table.global_scope
    assert table.global_scope.children[0].lookup_local("x") is x_decl.symbol


def test_annotations_do_not_change_ast_equality():
    tokens, _ = lexer("fn main() { x := 1; }")
    plain, _ = parser(tokens)
    annotated, _ = parser(tokens)
    analyzer(annotated)
    assert plain == annotated


def test_errors_do_not_cascade():
    # Syntax errors become ErrorNodes; the analyzer stays quiet about them.
    _, _, errors = analyze("fn main() { x := ; y := x + 1; z: i32 = y; }", allow_syntax_errors=True)
    assert errors == []
    # One semantic error per problem, not one per use.
    assert in_main("x := nope; y := x + 1; z: u8 = y; w := x[0];") == [1]


def test_errors_have_positions():
    _, _, errors = analyze("fn main() {\n  x: u8 = true;\n}")
    assert len(errors) == 1
    assert str(errors[0]).startswith("AnalyzerError(4) [line:2, col:11]")
    assert errors[0].span.start.line == 2
    assert ERROR not in (U8, I32)
