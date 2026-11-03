"""Parser tests runnable with pytest"""

import io
from contextlib import redirect_stderr, redirect_stdout

from mid.frontend.lexer import lexer
from mid.frontend.parser import Parser, parser
from mid.types import ast as A
from mid.types.util import Pos


def parse(source):
    """Lex and parse. Returns (ast, diagnostics, stderr text)."""
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        p = Parser(lexer(source))
        tree = p.parse()
    return tree, p.diagnostics, stderr.getvalue()


def valid(source):
    tree, diagnostics, stderr = parse(source)
    assert diagnostics == []
    assert stderr == ""
    return tree.program


def body(source):
    """Statements of the only function in a program (wrapped in fn main)."""
    program = valid("fn main() { " + source + " }")
    return program.decl[0].block.stmts


def expr(source):
    """Expression of a single 'x := <source>;' statement."""
    return body("x := " + source + ";")[0].init


def kinds(node_list):
    return [type(n).__name__ for n in node_list]


# ---------------------------------------------------------------- structure

def test_function_with_params_and_return_type():
    program = valid("fn suma(a: i32, b: i32) -> i32 { return a + b; }")
    fn = program.decl[0]
    assert isinstance(fn, A.FnDecl)
    assert fn.name == "suma"
    assert [(p.name, p.type.name) for p in fn.params] == [("a", "i32"), ("b", "i32")]
    assert fn.ret_type.name == "i32"
    ret = fn.block.stmts[0]
    assert isinstance(ret, A.ReturnStmt)
    assert isinstance(ret.value, A.BinaryExpr)
    assert ret.value.op == A.BinaryExpr.Op.ADD


def test_top_level_variables_and_functions():
    program = valid("g := 1; h: u8 = 2; k: i32; fn main() {}")
    assert kinds(program.decl) == ["VarDecl", "VarDecl", "VarDecl", "FnDecl"]
    g, h, k, _ = program.decl
    assert g.type is None and g.init.val == 1
    assert h.type.name == "u8" and h.init.val == 2
    assert k.type.name == "i32" and k.init is None


def test_empty_program_and_empty_function():
    assert valid("").decl == []
    fn = valid("fn f() {}").decl[0]
    assert fn.params == [] and fn.ret_type is None and fn.block.stmts == []


def test_trailing_commas_in_params_and_calls():
    fn = valid("fn f(a: i32, b: i32,) { g(1, 2,); h(); }").decl[0]
    assert len(fn.params) == 2
    calls = [s.expr for s in fn.block.stmts]
    assert [len(c.args) for c in calls] == [2, 0]


# --------------------------------------------------------------- statements

def test_variable_declaration_forms_inside_blocks():
    a, b, c = body("a := 1; b: i32 = 2; c: [4]u8;")
    assert (a.name, a.type, a.init.val) == ("a", None, 1)
    assert (b.name, b.type.name, b.init.val) == ("b", "i32", 2)
    assert c.init is None


def test_assignments_and_expression_statements():
    stmts = body("x = 1; x += 2; x -= 3; x *= 4; x /= 5; x %= 6; f(x);")
    ops = [s.op for s in stmts[:6]]
    assert ops == [
        A.AssignStmt.Op.DIRECT, A.AssignStmt.Op.ADD, A.AssignStmt.Op.SUB,
        A.AssignStmt.Op.MULT, A.AssignStmt.Op.DIV, A.AssignStmt.Op.MOD,
    ]
    assert isinstance(stmts[6], A.ExprStmt)
    assert isinstance(stmts[6].expr, A.CallExpr)


def test_if_else_if_else_is_one_statement():
    stmt = body("if a { x = 1; } else if b { x = 2; } else if c { x = 3; } else { x = 4; }")[0]
    assert isinstance(stmt, A.IfStmt)
    assert [b.cond.name for b in stmt.branches] == ["a", "b", "c"]
    assert stmt.else_body is not None
    assert len(stmt.else_body.stmts) == 1


def test_if_without_else_and_loop_with_break_continue():
    if_stmt, loop = body("if a { } loop { if b { break; } continue; }")
    assert if_stmt.else_body is None
    assert kinds(loop.body.stmts) == ["IfStmt", "ContinueStmt"]
    assert kinds(loop.body.stmts[0].branches[0].body.stmts) == ["BreakStmt"]


def test_return_with_and_without_value():
    a, b = body("return; return 1;")
    assert a.value is None
    assert b.value.val == 1


# -------------------------------------------------------------- expressions

def test_precedence_and_left_associativity():
    e = expr("1 + 2 * 3")
    assert e.op == A.BinaryExpr.Op.ADD
    assert e.right.op == A.BinaryExpr.Op.MULT

    e = expr("a - b - c")  # (a - b) - c
    assert e.op == A.BinaryExpr.Op.SUB
    assert e.left.op == A.BinaryExpr.Op.SUB
    assert e.left.left.name == "a" and e.right.name == "c"

    e = expr("a || b && c == d")
    assert e.op == A.BinaryExpr.Op.OR
    assert e.right.op == A.BinaryExpr.Op.AND
    assert e.right.right.op == A.BinaryExpr.Op.EQUAL


def test_all_binary_operators():
    cases = {
        "||": "OR", "&&": "AND", "==": "EQUAL", "!=": "NOT_EQUAL",
        ">": "GREATER", "<": "LESSER", ">=": "GREATER_EQUAL", "<=": "LESSER_EQUAL",
        "+": "ADD", "-": "SUB", "*": "MULT", "/": "DIV", "%": "MOD",
    }
    for symbol, name in cases.items():
        assert expr("a " + symbol + " b").op.name == name


def test_unary_cast_and_parentheses():
    e = expr("-a as f32")  # (-a) as f32
    assert isinstance(e, A.CastExpr)
    assert isinstance(e.value, A.UnaryExpr) and e.value.op == A.UnaryExpr.Op.NEGATE
    assert e.type.name == "f32"

    e = expr("a * b as u8")  # a * (b as u8)
    assert e.op == A.BinaryExpr.Op.MULT
    assert isinstance(e.right, A.CastExpr)

    e = expr("(1 + 2) * 3")
    assert e.op == A.BinaryExpr.Op.MULT
    assert e.left.op == A.BinaryExpr.Op.ADD

    e = expr("!!a")
    assert e.op == A.UnaryExpr.Op.NOT and e.value.op == A.UnaryExpr.Op.NOT
    assert expr("&a").op == A.UnaryExpr.Op.ADDRESS


def test_postfix_chain_is_applied_in_source_order():
    e = expr("f(x)[i]^")
    assert isinstance(e, A.DereferenceExpr)
    assert isinstance(e.value, A.IndexExpr)
    assert isinstance(e.value.target, A.CallExpr)
    assert e.value.target.callee.name == "f"
    assert e.value.index.name == "i"


def test_literals_get_decoded_values():
    assert [type(expr(s)).__name__ for s in ("1", "2.5", "'a'", '"hi"', "true", "false")] == [
        "Int", "Float", "Char", "String", "Bool", "Bool",
    ]
    assert expr("'a'").val == 97
    assert expr('"a\\nb"').val == "a\nb"
    assert expr("true").val is True and expr("false").val is False


def test_type_qualifiers_keep_source_order():
    stmts = body("a: [4]^u8; b: []i32; c: ^^u8;")
    qualifiers = [[type(q).__name__ for q in s.type.qual] for s in stmts]
    assert qualifiers == [["Array", "Pointer"], ["Slice"], ["Pointer", "Pointer"]]
    assert stmts[0].type.qual[0].size == 4
    assert stmts[0].type.name == "u8"


def test_field_access_is_postfix():
    e = expr("buff.len")
    assert isinstance(e, A.FieldExpr)
    assert e.target.name == "buff" and e.name == "len"

    e = expr("f(x).a[0]^.b")  # chain applied in source order
    assert isinstance(e, A.FieldExpr) and e.name == "b"
    assert isinstance(e.target, A.DereferenceExpr)
    assert isinstance(e.target.value, A.IndexExpr)
    assert isinstance(e.target.value.target, A.FieldExpr)


def test_ranges_inside_an_index():
    cases = {
        "buff[1..]": (1, None),
        "buff[..3]": (None, 3),
        "buff[1..3]": (1, 3),
        "buff[..]": (None, None),
    }
    for source, (low, high) in cases.items():
        e = expr(source)
        assert isinstance(e, A.SliceExpr), source
        assert e.target.name == "buff"
        assert (e.low.val if e.low else None) == low
        assert (e.high.val if e.high else None) == high
    assert isinstance(expr("buff[1]"), A.IndexExpr)
    e = expr("buff[a + 1..b * 2]")
    assert e.low.op == A.BinaryExpr.Op.ADD and e.high.op == A.BinaryExpr.Op.MULT


def test_slice_errors_are_reported():
    _, diagnostics, _ = parse("fn main() { x := a[1..; }")
    assert [d.code for d in diagnostics] == [5]
    _, diagnostics, _ = parse("fn main() { x := a.; }")
    assert [d.code for d in diagnostics] == [3]
    _, diagnostics, _ = parse("fn main() { x := a[]; }")
    assert [d.code for d in diagnostics] == [2]
    _, diagnostics, _ = parse("fn main() { x := 1..5; }")  # '..' only inside an index
    assert diagnostics


# -------------------------------------------------------------------- spans

def test_spans_cover_whole_constructs():
    source = "fn f() {\n  x := 1 + 2;\n}"
    fn = valid(source).decl[0]
    assert (fn.span.start, fn.span.end) == (Pos(0, 1, 1), Pos(len(source), 3, 2))
    decl = fn.block.stmts[0]
    assert source[decl.span.start.idx:decl.span.end.idx] == "x := 1 + 2;"
    assert source[decl.init.span.start.idx:decl.init.span.end.idx] == "1 + 2"


def test_parenthesized_expression_span_includes_parentheses():
    source = "fn f() { x := (a + b); }"
    init = valid(source).decl[0].block.stmts[0].init
    assert source[init.span.start.idx:init.span.end.idx] == "(a + b)"


# ------------------------------------------------------------------- errors

def test_missing_semicolon_is_reported_and_parsing_continues():
    tree, diagnostics, stderr = parse("fn main() { x := 1 y := 2; }")
    assert [d.code for d in diagnostics] == [5]
    assert "ParserError(5)" in stderr
    stmts = tree.program.decl[0].block.stmts
    assert kinds(stmts) == ["VarDecl", "VarDecl"]
    assert stmts[1].name == "y"


def test_missing_expression_creates_error_node_without_eating_the_semicolon():
    tree, diagnostics, _ = parse("fn main() { x := ; y := 1; }")
    assert [d.code for d in diagnostics] == [2]
    stmts = tree.program.decl[0].block.stmts
    assert isinstance(stmts[0].init, A.ErrorNode)
    assert stmts[1].name == "y"


def test_missing_closing_delimiters():
    _, diagnostics, _ = parse("fn main() { f(1, 2; a[1; }")
    assert [d.code for d in diagnostics] == [5, 5]
    _, diagnostics, _ = parse("fn main() { x := (1 + 2; }")
    assert [d.code for d in diagnostics] == [5]


def test_unexpected_eof_inside_block():
    tree, diagnostics, _ = parse("fn main() { x := 1;")
    assert [d.code for d in diagnostics] == [6]
    assert kinds(tree.program.decl[0].block.stmts) == ["VarDecl"]


def test_function_inside_block_is_treated_as_missing_brace():
    tree, diagnostics, _ = parse("fn a() { x := 1; fn b() { } ")
    assert diagnostics[0].code == 5
    assert kinds(tree.program.decl) == ["FnDecl", "FnDecl"]
    assert tree.program.decl[1].name == "b"


def test_invalid_top_level_item_recovers_at_next_declaration():
    tree, diagnostics, _ = parse("if x { } fn ok() { }")
    assert diagnostics[0].code == 8
    assert isinstance(tree.program.decl[0], A.ErrorNode)
    assert tree.program.decl[-1].name == "ok"


def test_bad_statement_becomes_error_node_and_next_statement_survives():
    tree, diagnostics, _ = parse("fn main() { else { } x := 1; }")
    assert diagnostics[0].code == 1
    stmts = tree.program.decl[0].block.stmts
    assert isinstance(stmts[0], A.ErrorNode)
    assert any(isinstance(s, A.VarDecl) and s.name == "x" for s in stmts)


def test_missing_type_name_and_missing_identifier():
    tree, diagnostics, _ = parse("fn main() { x: = 1; y := 2; }")
    assert diagnostics[0].code == 4
    stmts = tree.program.decl[0].block.stmts
    assert isinstance(stmts[0], A.ErrorNode)
    assert stmts[-1].name == "y"

    _, diagnostics, _ = parse("fn (a: i32) { }")
    assert diagnostics[0].code == 3


def test_lexer_error_tokens_are_reported_by_the_parser():
    tree, diagnostics, stderr = parse('fn main() { x := "abc;\n y := 1; }')
    assert 7 in [d.code for d in diagnostics]
    assert "LexerError(2)" in stderr and "ParserError(7)" in stderr
    stmts = tree.program.decl[0].block.stmts
    assert any(isinstance(s, A.VarDecl) and s.name == "y" for s in stmts)


def test_malformed_parameter_list():
    tree, diagnostics, _ = parse("fn f(a i32, b: u8) { }")
    assert diagnostics
    fn = tree.program.decl[0]
    assert [p.name for p in fn.params] == ["b"]


def test_diagnostics_go_to_stderr_only_and_have_positions():
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        p = Parser(lexer("fn main() {\n  x := 1\n}"))
        p.parse()
    assert stdout.getvalue() == ""
    assert "ParserError(5) [line:2, col:9]" in stderr.getvalue()
    assert p.diagnostics[0].span.start == Pos(20, 2, 9)


def test_parser_always_terminates_on_garbage():
    garbage = [
        ")))]]]{{{", "fn fn fn", "} } }", "x := := :=", "fn f( ( ( (", ";;;;",
        "fn main() { ) ] , ; else else }", "@ # $ 'a ", '"unterminated',
        "fn main() { if if if }", "fn main() { x as as as; }", "^ ^ ^ [ [ [",
        "-> -> ->", "fn f() -> -> {}", "a.b.. [..", "x := a[..;", "a b c d e f g", "fn main() { f(,,,); a[,]; }",
    ]
    for source in garbage:
        tree, diagnostics, _ = parse(source)
        assert isinstance(tree.program, A.Program)
        assert diagnostics, source


def test_parser_function_returns_ast_and_accepts_tokens_without_eof():
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        tree = parser(lexer("fn main() { }"))
        tokens = lexer("x := 1;")[:-1]  # EOF removed on purpose
        assert Parser(tokens).parse().program.decl[0].name == "x"
    assert isinstance(tree, A.AST)
    assert stderr.getvalue() == ""
