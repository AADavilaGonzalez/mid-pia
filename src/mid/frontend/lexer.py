import math
import struct
import sys

from mid.types.token import Token, TokenType
from mid.types.util import Pos


_KEYWORDS = {
    "fn": TokenType.FUNCTION,
    "as": TokenType.AS,
    "return": TokenType.RETURN,
    "loop": TokenType.LOOP,
    "break": TokenType.BREAK,
    "continue": TokenType.CONTINUE,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
}

_OPERATORS = {
    "(": TokenType.LPAREN,
    ")": TokenType.RPAREN,
    "{": TokenType.LBRACE,
    "}": TokenType.RBRACE,
    "[": TokenType.LBRACKET,
    "]": TokenType.RBRACKET,
    ",": TokenType.COMMA,
    ";": TokenType.SEMICOLON,
    "^": TokenType.CARET,
    ":": TokenType.COLON,
    ":=": TokenType.COLON_EQUAL,
    "+": TokenType.PLUS,
    "+=": TokenType.PLUS_EQUAL,
    "-": TokenType.MINUS,
    "-=": TokenType.MINUS_EQUAL,
    "->": TokenType.ARROW,
    "*": TokenType.STAR,
    "*=": TokenType.STAR_EQUAL,
    "/": TokenType.SLASH,
    "/=": TokenType.SLASH_EQUAL,
    "%": TokenType.PERCENT,
    "%=": TokenType.PERCENT_EQUAL,
    ">": TokenType.GREATER,
    ">=": TokenType.GREATER_EQUAL,
    "<": TokenType.LESSER,
    "<=": TokenType.LESSER_EQUAL,
    "!": TokenType.BANG,
    "!=": TokenType.BANG_EQUAL,
    "&": TokenType.AMP,
    "&&": TokenType.AMPAMP,
    "||": TokenType.BARBAR,
    "=": TokenType.EQUAL,
    "==": TokenType.EQUAL_EQUAL,
    ".": TokenType.DOT,
    "..": TokenType.DOTDOT,
}

_ESCAPES = {
    "n": "\n", "t": "\t", "b": "\b", "r": "\r",
    "a": "\a", "f": "\f", "v": "\v", "0": "\0", "\\": "\\",
}
_MAX_INTEGER = str(2**64 - 1)


def _is_digit(char: str) -> bool:
    return "0" <= char <= "9"


def _is_alpha(char: str) -> bool:
    return "a" <= char <= "z" or "A" <= char <= "Z" or char == "_"


class _Lexer:
    def __init__(self, source: str):
        self.source = source
        self.current = 0
        self.line = 1
        self.col = 1
        self.start = Pos(0, 1, 1)
        self.tokens: list[Token] = []

    def _peek(self, offset: int = 0) -> str:
        index = self.current + offset
        return self.source[index] if index < len(self.source) else ""

    def _advance(self) -> str:
        char = self.source[self.current]
        self.current += 1
        if char == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return char

    def _emit(self, token_type: TokenType, value: None | int | float | str = None):
        lexeme = self.source[self.start.idx:self.current]
        self.tokens.append(Token(lexeme, token_type, self.start, value))

    def _error(self, code: int, message: str):
        print(
            f"LexerError({code}) [line:{self.start.line}, col:{self.start.col}]: {message}",
            file=sys.stderr,
        )
        self._emit(TokenType.ERROR)

    def _identifier(self):
        while _is_alpha(self._peek()) or _is_digit(self._peek()):
            self._advance()
        lexeme = self.source[self.start.idx:self.current]
        token_type = _KEYWORDS.get(lexeme, TokenType.IDENT)
        value = None
        if token_type in (TokenType.TRUE, TokenType.FALSE):
            value = int(token_type == TokenType.TRUE)
        self._emit(token_type, value)

    def _number(self, has_dot: bool):
        while _is_digit(self._peek()):
            self._advance()
        # A decimal point requires a following digit; never consume the '..' slice operator.
        if not has_dot and self._peek() == "." and _is_digit(self._peek(1)):
            has_dot = True
            self._advance()
            while _is_digit(self._peek()):
                self._advance()

        lexeme = self.source[self.start.idx:self.current]
        if has_dot:
            try:
                value = struct.unpack("!f", struct.pack("!f", float(lexeme)))[0]
            except (OverflowError, ValueError):
                value = math.inf
            if not math.isfinite(value):
                self._error(6, "Float literal is too large for f32")
            else:
                self._emit(TokenType.FLOAT, value)
            return

        # Check before int() so arbitrarily long input cannot exceed Python's digit limit.
        digits = lexeme.lstrip("0") or "0"
        if len(digits) > len(_MAX_INTEGER) or (
            len(digits) == len(_MAX_INTEGER) and digits > _MAX_INTEGER
        ):
            self._error(3, "Integer literal is too large for u64")
        else:
            self._emit(TokenType.INTEGER, int(digits))

    def _quoted(self, quote: str):
        value: list[str] = []
        error: tuple[int, str] | None = None
        while self._peek() and self._peek() not in ("\n", "\r"):
            char = self._advance()
            if char == quote:
                if error is not None:
                    self._error(*error)
                elif quote == "'" and len(value) != 1:
                    self._error(4, "Char literal must contain exactly one ASCII character")
                elif quote == "'":
                    self._emit(TokenType.CHAR, ord(value[0]))
                else:
                    self._emit(TokenType.STRING, "".join(value))
                return

            if char == "\\":
                if not self._peek() or self._peek() in ("\n", "\r"):
                    break
                escaped = self._advance()
                if escaped == quote:
                    value.append(quote)
                elif escaped in _ESCAPES:
                    value.append(_ESCAPES[escaped])
                elif error is None:
                    error = (5, f"Invalid escape sequence {('\\' + escaped)!r}")
            elif " " <= char <= "~":
                value.append(char)
            elif error is None:
                code = 4 if quote == "'" else 1
                error = (code, "Literal contains a non-printable or non-ASCII character")

        # Leave the line break for scan(); recovery must not swallow the next line.
        if quote == "'":
            self._error(4, "Unterminated char literal")
        else:
            self._error(2, "Unterminated string literal")

    def scan(self) -> list[Token]:
        while self.current < len(self.source):
            self.start = Pos(self.current, self.line, self.col)
            char = self._advance()
            if char in " \t\r\n":
                continue
            if char == "/" and self._peek() == "/":
                while self._peek() and self._peek() != "\n":
                    self._advance()
                continue
            if _is_alpha(char):
                self._identifier()
            elif _is_digit(char) or (char == "." and _is_digit(self._peek())):
                self._number(has_dot=char == ".")
            elif char in ("'", '"'):
                self._quoted(char)
            else:
                operator = char + self._peek()
                if len(operator) == 2 and operator in _OPERATORS:
                    self._advance()
                    self._emit(_OPERATORS[operator])
                elif char in _OPERATORS:
                    self._emit(_OPERATORS[char])
                else:
                    self._error(1, f"Unexpected character {char!r}")

        self.start = Pos(self.current, self.line, self.col)
        self._emit(TokenType.EOF)
        return self.tokens


def lexer(source: str) -> list[Token]:
    """Tokenize mid source, reporting recoverable errors to stderr.

    Positions use a zero-based source index and one-based lines/columns. Literal
    values are u64-range Python ints, f32-rounded floats, ASCII character codes,
    decoded ASCII strings, and 0/1 for booleans. Other tokens have no value.

    Agreed refinements to the draft specification: decimal points require a
    following digit, signs are separate tokens, and quoted literals are limited
    to printable ASCII plus supported escapes. Float overflow uses LexerError(6).
    """
    return _Lexer(source).scan()
