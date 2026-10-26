"""Lexer tests runnable with  pytest"""

import io
from contextlib import redirect_stdout

from mid.types.token import TokenType as T
from mid.types.util import Pos


def test_basic_program(self):
    source = "fn main() { x := 2 + 3; return x; }"
    tokens = self.valid(source)
    assert [token.type for token in tokens] == [
        T.FUNCTION, T.IDENT, T.LPAREN, T.RPAREN, T.LBRACE,
        T.IDENT, T.COLON_EQUAL, T.INTEGER, T.PLUS, T.INTEGER,
        T.SEMICOLON, T.RETURN, T.IDENT, T.SEMICOLON, T.RBRACE, T.EOF,
    ]
    assert [token.val for token in tokens if token.type == T.INTEGER] == [2, 3]
    assert tokens[1].lexeme == "main"
    assert tokens[1].val is None

def test_all_operators(self):
    operators = [
        ("(", T.LPAREN), (")", T.RPAREN), ("{", T.LBRACE), ("}", T.RBRACE),
        ("[", T.LBRACKET), ("]", T.RBRACKET), (",", T.COMMA), (";", T.SEMICOLON),
        ("^", T.CARET), (":", T.COLON), (":=", T.COLON_EQUAL),
        ("+", T.PLUS), ("+=", T.PLUS_EQUAL), ("-", T.MINUS), ("-=", T.MINUS_EQUAL),
        ("->", T.ARROW), ("*", T.STAR), ("*=", T.STAR_EQUAL),
        ("/", T.SLASH), ("/=", T.SLASH_EQUAL), ("%", T.PERCENT), ("%=", T.PERCENT_EQUAL),
        (">", T.GREATER), (">=", T.GREATER_EQUAL), ("<", T.LESSER), ("<=", T.LESSER_EQUAL),
        ("!", T.BANG), ("!=", T.BANG_EQUAL), ("&", T.AMP), ("&&", T.AMP_AMP),
        ("||", T.BAR_BAR), ("=", T.EQUAL), ("==", T.EQUAL_EQUAL),
        (".", T.DOT), ("..", T.DOT_DOT),
    ]
    tokens = self.valid(" ".join(lexeme for lexeme, _ in operators))
    assert [(t.lexeme, t.type) for t in tokens[:-1]] == operators
    assert all(t.val is None for t in tokens)

def test_longest_operator_match_without_spaces(self):
    tokens = self.valid("===!==&&&...->-:=:")
    assert [t.lexeme for t in tokens[:-1]] == ["==", "=", "!=", "=", "&&", "&", "..", ".", "->", "-", ":=", ":"]

def test_keywords_and_booleans(self):
    tokens = self.valid("fn as return loop break continue if else true false")
    assert [t.type for t in tokens[:-1]] == [
        T.FUNCTION, T.AS, T.RETURN, T.LOOP, T.BREAK,
        T.CONTINUE, T.IF, T.ELSE, T.TRUE, T.FALSE,
    ]
    assert [t.val for t in tokens[-3:-1]] == [1, 0]

def test_identifiers_are_ascii_and_case_sensitive(self):
    tokens = self.valid("_ _x x2 Fn TRUE true_value i32 u8 for while switch")
    assert all(t.type == T.IDENT for t in tokens[:-1])

def test_comments_whitespace_and_positions(self):
    source = " \tfn main() { // ignored ' \" @\n\tx := 1;\r\n}\n// end"
    tokens = self.valid(source)
    expected = [
        ("fn", 1, 3), ("main", 1, 6), ("(", 1, 10), (")", 1, 11),
        ("{", 1, 13), ("x", 2, 2), (":=", 2, 4), ("1", 2, 7),
        (";", 2, 8), ("}", 3, 1), ("", 4, 7),
    ]
    assert [(t.lexeme, t.pos.line, t.pos.col) for t in tokens] == expected
    for token in tokens[:-1]:
        assert token.pos.idx == source.index(token.lexeme)
    assert tokens[-1].pos.idx == len(source)

def test_comment_does_not_emit_tokens(self):
    assert len(self.valid("// comment without newline")) == 1
    tokens = self.valid("1//comment\n2")
    assert [t.val for t in tokens[:-1]] == [1, 2]
    assert tokens[1].pos == Pos(11, 2, 1)

def test_block_comments_are_not_supported(self):
    tokens = self.valid("/* text */")
    assert [t.type for t in tokens] == [T.SLASH, T.STAR, T.IDENT, T.STAR, T.SLASH, T.EOF]

def test_empty_and_whitespace_only_input(self):
    for source, pos in [("", Pos(0, 1, 1)), (" \t\n\r\n", Pos(5, 3, 1))]:
        tokens = self.valid(source)
        assert len(tokens) == 1
        assert tokens[0].pos == pos

def test_decimal_and_dot_disambiguation(self):
    cases = {
        "3.14": [(T.FLOAT, "3.14")],
        ".5": [(T.DOT, "."), (T.INTEGER, "5")],
        "1.": [(T.INTEGER, "1"), (T.DOT, ".")],
        "1..": [(T.INTEGER, "1"), (T.DOT_DOT, "..")],
        "1..5": [(T.INTEGER, "1"), (T.DOT_DOT, ".."), (T.INTEGER, "5")],
        "buff.len": [(T.IDENT, "buff"), (T.DOT, "."), (T.IDENT, "len")],
        "buff[1..]": [(T.IDENT, "buff"), (T.LBRACKET, "["),
                        (T.INTEGER, "1"), (T.DOT_DOT, ".."), (T.RBRACKET, "]")],
    }
    for source, expected in cases.items():
        assert [(t.type, t.lexeme) for t in self.valid(source)[:-1]] == expected

def test_integer_values_and_signs(self):
    tokens = self.valid("0 00042 18446744073709551615 -128 +2")
    assert [t.val for t in tokens if t.type == T.INTEGER] == [0, 42, 2**64 - 1, 128, 2]
    assert [t.type for t in tokens[3:5]] == [T.MINUS, T.INTEGER]

def test_leading_zeroes_do_not_trigger_python_integer_limit(self):
    tokens = self.valid("0" * 5000 + "42")
    assert tokens[0].val == 42

def test_integer_overflow_recovers_after_digits(self):
    for digits in (str(2**64), "9" * 5000):
        tokens, stderr = self.scan(digits + "; next")
        assert [t.type for t in tokens] == [T.ERROR, T.SEMICOLON, T.IDENT, T.EOF]
        assert tokens[0].lexeme == digits
        assert tokens[0].val is None
        assert "LexerError(3)" in stderr
        assert stderr.count("LexerError") == 1

def test_float_values_are_rounded_to_f32(self):
    tokens = self.valid("0.1 16777217.0 0.0")
    assert [t.val for t in tokens[:-1]] == [0.10000000149011612, 16777216.0, 0.0]

def test_large_float_is_not_treated_as_integer_overflow(self):
    tokens = self.valid("18446744073709551616.0")
    assert tokens[0].type == T.FLOAT
    assert tokens[0].val == float(2**64)

def test_float_overflow_recovers(self):
    for number in ("3402823466385288598117041834845169254400.0", "9" * 5000 + ".0"):
        tokens, stderr = self.scan(number + " 2")
        assert [t.type for t in tokens] == [T.ERROR, T.INTEGER, T.EOF]
        assert tokens[1].val == 2
        assert "LexerError(6)" in stderr

def test_float_underflow_rounds_to_zero(self):
    tokens = self.valid("0." + "0" * 60 + "1")
    assert tokens[0].val == 0.0

def test_largest_finite_f32(self):
    tokens = self.valid("340282346638528859811704183484516925440.0")
    assert tokens[0].val == 3.4028234663852886e38

def test_numeric_separators_and_exponents_are_not_consumed(self):
    tokens = self.valid("1,000 1_000 1e3")
    assert [(t.type, t.lexeme) for t in tokens[:-1]] == [
        (T.INTEGER, "1"), (T.COMMA, ","), (T.INTEGER, "000"),
        (T.INTEGER, "1"), (T.IDENT, "_000"), (T.INTEGER, "1"), (T.IDENT, "e3"),
    ]

def test_character_values(self):
    cases = {"'A'": 65, "' '": 32, "'~'": 126, "'\"'": 34,
                r"'\n'": 10, r"'\0'": 0, r"'\\'": 92, r"'\''": 39}
    for source, expected in cases.items():
        token = self.valid(source)[0]
        assert token.type == T.CHAR
        assert token.val == expected
        assert token.lexeme == source

def test_all_common_escapes_in_both_literal_types(self):
    escapes = {"n": 10, "t": 9, "b": 8, "r": 13, "a": 7,
                "f": 12, "v": 11, "0": 0, "\\": 92}
    for escape, code in escapes.items():
        for quote in ("'", '"'):
            token = self.valid(quote + "\\" + escape + quote)[0]
            assert token.val == (code if quote == "'" else chr(code))

def test_strings_preserve_lexemes_and_decode_values(self):
    source = r'"hello\n\"mid\"\\\0"'
    token = self.valid(source)[0]
    assert token.type == T.STRING
    assert token.lexeme == source
    assert token.val == 'hello\n"mid"\\\0'
    assert self.valid('""')[0].val == ""

def test_escaped_newlines_do_not_change_source_line_positions(self):
    source = r'"a\nb" next'
    tokens = self.valid(source)
    assert tokens[0].val == "a\nb"
    assert tokens[1].pos == Pos(7, 1, 8)

def test_comment_markers_inside_strings_are_text(self):
    tokens = self.valid('"// not a comment /* either */"')
    assert tokens[0].val == "// not a comment /* either */"

def test_invalid_characters_emit_errors_and_continue(self):
    tokens, stderr = self.scan("@|\0é١ x")
    assert [t.type for t in tokens] == [T.ERROR] * 5 + [T.IDENT, T.EOF]
    assert stderr.count("LexerError(1)") == 5
    assert "line:1, col:4" in stderr
    assert tokens[-2].lexeme == "x"

def test_invalid_character_literals_recover_at_closing_quote(self):
    for literal in ("''", "'ab'", "'é'", "'\x7f'", "'\t'"):
        tokens, stderr = self.scan(literal + "; x")
        assert [t.type for t in tokens] == [T.ERROR, T.SEMICOLON, T.IDENT, T.EOF]
        assert tokens[0].lexeme == literal
        assert "LexerError(4)" in stderr

def test_invalid_escapes_recover_at_unescaped_quote(self):
    for literal in (r"'\q'", r'"bad\q\"still bad"'):
        tokens, stderr = self.scan(literal + "; next")
        assert [t.type for t in tokens] == [T.ERROR, T.SEMICOLON, T.IDENT, T.EOF]
        assert tokens[0].lexeme == literal
        assert "LexerError(5)" in stderr
        assert stderr.count("LexerError") == 1

def test_non_ascii_and_raw_control_characters_in_strings(self):
    for literal in ('"café"', '"a\tb"', '"\x00"', '"\x7f"'):
        tokens, stderr = self.scan(literal + " 1")
        assert [t.type for t in tokens] == [T.ERROR, T.INTEGER, T.EOF]
        assert "LexerError(1)" in stderr

def test_unterminated_literals_do_not_swallow_next_line(self):
    for literal in ('"bad', '"bad\\', "'a", "'\\"):
        for newline in ("\n", "\r\n"):
            tokens, stderr = self.scan(literal + newline + "next := 2;")
            assert [t.type for t in tokens] == [T.ERROR, T.IDENT, T.COLON_EQUAL, T.INTEGER, T.SEMICOLON, T.EOF]
            assert tokens[0].lexeme == literal
            assert tokens[1].pos.line == 2
            assert tokens[1].pos.col == 1
            code = 2 if literal.startswith('"') else 4
            assert f"LexerError({code})" in stderr

def test_unterminated_literals_at_eof(self):
    for literal in ('"bad', '"bad\\', "'a", "'\\"):
        tokens, stderr = self.scan(literal)
        assert [t.type for t in tokens] == [T.ERROR, T.EOF]
        assert tokens[0].lexeme == literal
        assert stderr
        assert tokens[-1].pos.idx == len(literal)

def test_multiple_calls_have_independent_state(self):
    self.valid("\n\nfn")
    tokens = self.valid("x")
    assert tokens[0].pos == Pos(0, 1, 1)
    assert tokens[-1].pos == Pos(1, 1, 2)

def test_diagnostics_only_go_to_stderr(self):
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        tokens, stderr = self.scan("\n @")
    assert stdout.getvalue() == ""
    assert tokens[0].pos == Pos(2, 2, 2)
    assert "line:2, col:2" in stderr
