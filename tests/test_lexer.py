"""Run from the repository root: PYTHONPATH=src python3 -m unittest discover -s tests -v."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from mid.frontend.lexer import lexer
from mid.types.token import TokenType as T
from mid.types.util import Pos


class LexerTests(unittest.TestCase):
    def scan(self, source):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            tokens = lexer(source)
        self.assertEqual(tokens[-1].type, T.EOF)
        self.assertEqual(sum(token.type == T.EOF for token in tokens), 1)
        self.assertEqual(tokens[-1].lexeme, "")
        self.assertIsNone(tokens[-1].val)
        # Check source offsets without relying on the shared Token.end() helper.
        for token in tokens:
            self.assertEqual(
                source[token.pos.idx:token.pos.idx + len(token.lexeme)], token.lexeme
            )
        return tokens, stderr.getvalue()

    def valid(self, source):
        tokens, stderr = self.scan(source)
        self.assertEqual(stderr, "")
        self.assertNotIn(T.ERROR, [token.type for token in tokens])
        return tokens

    def test_basic_program(self):
        source = "fn main() { x := 2 + 3; return x; }"
        tokens = self.valid(source)
        self.assertEqual([token.type for token in tokens], [
            T.FUNCTION, T.IDENT, T.LPAREN, T.RPAREN, T.LBRACE,
            T.IDENT, T.COLON_EQUAL, T.INTEGER, T.PLUS, T.INTEGER,
            T.SEMICOLON, T.RETURN, T.IDENT, T.SEMICOLON, T.RBRACE, T.EOF,
        ])
        self.assertEqual([token.val for token in tokens if token.type == T.INTEGER], [2, 3])
        self.assertEqual(tokens[1].lexeme, "main")
        self.assertIsNone(tokens[1].val)

    def test_all_operators(self):
        operators = [
            ("(", T.LPAREN), (")", T.RPAREN), ("{", T.LBRACE), ("}", T.RBRACE),
            ("[", T.LBRACKET), ("]", T.RBRACKET), (",", T.COMMA), (";", T.SEMICOLON),
            ("^", T.CARET), (":", T.COLON), (":=", T.COLON_EQUAL),
            ("+", T.PLUS), ("+=", T.PLUS_EQUAL), ("-", T.MINUS), ("-=", T.MINUS_EQUAL),
            ("->", T.ARROW), ("*", T.STAR), ("*=", T.STAR_EQUAL),
            ("/", T.SLASH), ("/=", T.SLASH_EQUAL), ("%", T.PERCENT), ("%=", T.PERCENT_EQUAL),
            (">", T.GREATER), (">=", T.GREATER_EQUAL), ("<", T.LESSER), ("<=", T.LESSER_EQUAL),
            ("!", T.BANG), ("!=", T.BANG_EQUAL), ("&", T.AMP), ("&&", T.AMPAMP),
            ("||", T.BARBAR), ("=", T.EQUAL), ("==", T.EQUAL_EQUAL),
            (".", T.DOT), ("..", T.DOTDOT),
        ]
        tokens = self.valid(" ".join(lexeme for lexeme, _ in operators))
        self.assertEqual([(t.lexeme, t.type) for t in tokens[:-1]], operators)
        self.assertTrue(all(t.val is None for t in tokens))

    def test_longest_operator_match_without_spaces(self):
        tokens = self.valid("===!==&&&...->-:=:")
        self.assertEqual([t.lexeme for t in tokens[:-1]],
                         ["==", "=", "!=", "=", "&&", "&", "..", ".", "->", "-", ":=", ":"])

    def test_keywords_and_booleans(self):
        tokens = self.valid("fn as return loop break continue if else true false")
        self.assertEqual([t.type for t in tokens[:-1]], [
            T.FUNCTION, T.AS, T.RETURN, T.LOOP, T.BREAK,
            T.CONTINUE, T.IF, T.ELSE, T.TRUE, T.FALSE,
        ])
        self.assertEqual([t.val for t in tokens[-3:-1]], [1, 0])

    def test_identifiers_are_ascii_and_case_sensitive(self):
        tokens = self.valid("_ _x x2 Fn TRUE true_value i32 u8 for while switch")
        self.assertTrue(all(t.type == T.IDENT for t in tokens[:-1]))

    def test_comments_whitespace_and_positions(self):
        source = " \tfn main() { // ignored ' \" @\n\tx := 1;\r\n}\n// end"
        tokens = self.valid(source)
        expected = [
            ("fn", 1, 3), ("main", 1, 6), ("(", 1, 10), (")", 1, 11),
            ("{", 1, 13), ("x", 2, 2), (":=", 2, 4), ("1", 2, 7),
            (";", 2, 8), ("}", 3, 1), ("", 4, 7),
        ]
        self.assertEqual([(t.lexeme, t.pos.line, t.pos.col) for t in tokens], expected)
        for token in tokens[:-1]:
            self.assertEqual(token.pos.idx, source.index(token.lexeme))
        self.assertEqual(tokens[-1].pos.idx, len(source))

    def test_comment_does_not_emit_tokens(self):
        self.assertEqual(len(self.valid("// comment without newline")), 1)
        tokens = self.valid("1//comment\n2")
        self.assertEqual([t.val for t in tokens[:-1]], [1, 2])
        self.assertEqual(tokens[1].pos, Pos(11, 2, 1))

    def test_block_comments_are_not_supported(self):
        tokens = self.valid("/* text */")
        self.assertEqual([t.type for t in tokens],
                         [T.SLASH, T.STAR, T.IDENT, T.STAR, T.SLASH, T.EOF])

    def test_empty_and_whitespace_only_input(self):
        for source, pos in [("", Pos(0, 1, 1)), (" \t\n\r\n", Pos(5, 3, 1))]:
            with self.subTest(source=source):
                tokens = self.valid(source)
                self.assertEqual(len(tokens), 1)
                self.assertEqual(tokens[0].pos, pos)

    def test_decimal_and_dot_disambiguation(self):
        cases = {
            "3.14": [(T.FLOAT, "3.14")],
            ".5": [(T.FLOAT, ".5")],
            "1.": [(T.INTEGER, "1"), (T.DOT, ".")],
            "1..": [(T.INTEGER, "1"), (T.DOTDOT, "..")],
            "1..5": [(T.INTEGER, "1"), (T.DOTDOT, ".."), (T.INTEGER, "5")],
            "buff.len": [(T.IDENT, "buff"), (T.DOT, "."), (T.IDENT, "len")],
            "buff[1..]": [(T.IDENT, "buff"), (T.LBRACKET, "["),
                           (T.INTEGER, "1"), (T.DOTDOT, ".."), (T.RBRACKET, "]")],
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual([(t.type, t.lexeme) for t in self.valid(source)[:-1]], expected)

    def test_integer_values_and_signs(self):
        tokens = self.valid("0 00042 18446744073709551615 -128 +2")
        self.assertEqual([t.val for t in tokens if t.type == T.INTEGER],
                         [0, 42, 2**64 - 1, 128, 2])
        self.assertEqual([t.type for t in tokens[3:5]], [T.MINUS, T.INTEGER])

    def test_leading_zeroes_do_not_trigger_python_integer_limit(self):
        tokens = self.valid("0" * 5000 + "42")
        self.assertEqual(tokens[0].val, 42)

    def test_integer_overflow_recovers_after_digits(self):
        for digits in (str(2**64), "9" * 5000):
            with self.subTest(length=len(digits)):
                tokens, stderr = self.scan(digits + "; next")
                self.assertEqual([t.type for t in tokens], [T.ERROR, T.SEMICOLON, T.IDENT, T.EOF])
                self.assertEqual(tokens[0].lexeme, digits)
                self.assertIsNone(tokens[0].val)
                self.assertIn("LexerError(3)", stderr)
                self.assertEqual(stderr.count("LexerError"), 1)

    def test_float_values_are_rounded_to_f32(self):
        tokens = self.valid("0.1 .5 16777217.0 0.0")
        self.assertEqual([t.val for t in tokens[:-1]],
                         [0.10000000149011612, 0.5, 16777216.0, 0.0])

    def test_large_float_is_not_treated_as_integer_overflow(self):
        tokens = self.valid("18446744073709551616.0")
        self.assertEqual(tokens[0].type, T.FLOAT)
        self.assertEqual(tokens[0].val, float(2**64))

    def test_float_overflow_recovers(self):
        for number in ("3402823466385288598117041834845169254400.0", "9" * 5000 + ".0"):
            with self.subTest(length=len(number)):
                tokens, stderr = self.scan(number + " 2")
                self.assertEqual([t.type for t in tokens], [T.ERROR, T.INTEGER, T.EOF])
                self.assertEqual(tokens[1].val, 2)
                self.assertIn("LexerError(6)", stderr)

    def test_float_underflow_rounds_to_zero(self):
        tokens = self.valid("0." + "0" * 60 + "1")
        self.assertEqual(tokens[0].val, 0.0)

    def test_largest_finite_f32(self):
        tokens = self.valid("340282346638528859811704183484516925440.0")
        self.assertEqual(tokens[0].val, 3.4028234663852886e38)

    def test_numeric_separators_and_exponents_are_not_consumed(self):
        tokens = self.valid("1,000 1_000 1e3")
        self.assertEqual([(t.type, t.lexeme) for t in tokens[:-1]], [
            (T.INTEGER, "1"), (T.COMMA, ","), (T.INTEGER, "000"),
            (T.INTEGER, "1"), (T.IDENT, "_000"), (T.INTEGER, "1"), (T.IDENT, "e3"),
        ])

    def test_character_values(self):
        cases = {"'A'": 65, "' '": 32, "'~'": 126, "'\"'": 34,
                 r"'\n'": 10, r"'\0'": 0, r"'\\'": 92, r"'\''": 39}
        for source, expected in cases.items():
            with self.subTest(source=source):
                token = self.valid(source)[0]
                self.assertEqual(token.type, T.CHAR)
                self.assertEqual(token.val, expected)
                self.assertEqual(token.lexeme, source)

    def test_all_common_escapes_in_both_literal_types(self):
        escapes = {"n": 10, "t": 9, "b": 8, "r": 13, "a": 7,
                   "f": 12, "v": 11, "0": 0, "\\": 92}
        for escape, code in escapes.items():
            for quote in ("'", '"'):
                with self.subTest(escape=escape, quote=quote):
                    token = self.valid(quote + "\\" + escape + quote)[0]
                    self.assertEqual(token.val, code if quote == "'" else chr(code))

    def test_strings_preserve_lexemes_and_decode_values(self):
        source = r'"hello\n\"mid\"\\\0"'
        token = self.valid(source)[0]
        self.assertEqual(token.type, T.STRING)
        self.assertEqual(token.lexeme, source)
        self.assertEqual(token.val, 'hello\n"mid"\\\0')
        self.assertEqual(self.valid('""')[0].val, "")

    def test_escaped_newlines_do_not_change_source_line_positions(self):
        source = r'"a\nb" next'
        tokens = self.valid(source)
        self.assertEqual(tokens[0].val, "a\nb")
        self.assertEqual(tokens[1].pos, Pos(7, 1, 8))

    def test_comment_markers_inside_strings_are_text(self):
        tokens = self.valid('"// not a comment /* either */"')
        self.assertEqual(tokens[0].val, "// not a comment /* either */")

    def test_invalid_characters_emit_errors_and_continue(self):
        tokens, stderr = self.scan("@|\0é١ x")
        self.assertEqual([t.type for t in tokens], [T.ERROR] * 5 + [T.IDENT, T.EOF])
        self.assertEqual(stderr.count("LexerError(1)"), 5)
        self.assertIn("line:1, col:4", stderr)
        self.assertEqual(tokens[-2].lexeme, "x")

    def test_invalid_character_literals_recover_at_closing_quote(self):
        for literal in ("''", "'ab'", "'é'", "'\x7f'", "'\t'"):
            with self.subTest(literal=literal):
                tokens, stderr = self.scan(literal + "; x")
                self.assertEqual([t.type for t in tokens], [T.ERROR, T.SEMICOLON, T.IDENT, T.EOF])
                self.assertEqual(tokens[0].lexeme, literal)
                self.assertIn("LexerError(4)", stderr)

    def test_invalid_escapes_recover_at_unescaped_quote(self):
        for literal in (r"'\q'", r'"bad\q\"still bad"'):
            with self.subTest(literal=literal):
                tokens, stderr = self.scan(literal + "; next")
                self.assertEqual([t.type for t in tokens], [T.ERROR, T.SEMICOLON, T.IDENT, T.EOF])
                self.assertEqual(tokens[0].lexeme, literal)
                self.assertIn("LexerError(5)", stderr)
                self.assertEqual(stderr.count("LexerError"), 1)

    def test_non_ascii_and_raw_control_characters_in_strings(self):
        for literal in ('"café"', '"a\tb"', '"\x00"', '"\x7f"'):
            with self.subTest(literal=literal):
                tokens, stderr = self.scan(literal + " 1")
                self.assertEqual([t.type for t in tokens], [T.ERROR, T.INTEGER, T.EOF])
                self.assertIn("LexerError(1)", stderr)

    def test_unterminated_literals_do_not_swallow_next_line(self):
        for literal in ('"bad', '"bad\\', "'a", "'\\"):
            for newline in ("\n", "\r\n"):
                with self.subTest(literal=literal, newline=newline):
                    tokens, stderr = self.scan(literal + newline + "next := 2;")
                    self.assertEqual([t.type for t in tokens],
                                     [T.ERROR, T.IDENT, T.COLON_EQUAL, T.INTEGER, T.SEMICOLON, T.EOF])
                    self.assertEqual(tokens[0].lexeme, literal)
                    self.assertEqual(tokens[1].pos.line, 2)
                    self.assertEqual(tokens[1].pos.col, 1)
                    code = 2 if literal.startswith('"') else 4
                    self.assertIn(f"LexerError({code})", stderr)

    def test_unterminated_literals_at_eof(self):
        for literal in ('"bad', '"bad\\', "'a", "'\\"):
            with self.subTest(literal=literal):
                tokens, stderr = self.scan(literal)
                self.assertEqual([t.type for t in tokens], [T.ERROR, T.EOF])
                self.assertEqual(tokens[0].lexeme, literal)
                self.assertTrue(stderr)
                self.assertEqual(tokens[-1].pos.idx, len(literal))

    def test_multiple_calls_have_independent_state(self):
        self.valid("\n\nfn")
        tokens = self.valid("x")
        self.assertEqual(tokens[0].pos, Pos(0, 1, 1))
        self.assertEqual(tokens[-1].pos, Pos(1, 1, 2))

    def test_diagnostics_only_go_to_stderr(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            tokens, stderr = self.scan("\n @")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(tokens[0].pos, Pos(2, 2, 2))
        self.assertIn("line:2, col:2", stderr)


if __name__ == "__main__":
    unittest.main()
