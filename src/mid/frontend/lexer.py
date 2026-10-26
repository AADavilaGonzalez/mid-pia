import math
import struct
import sys

from mid.types.token import Token, TokenType
from mid.types.util import Pos


KEYWORDS = {
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

OPERATORS = {
    "(": TokenType.LPAREN,      ")": TokenType.RPAREN,      "{": TokenType.LBRACE,
    "}": TokenType.RBRACE,      "[": TokenType.LBRACKET,    "]": TokenType.RBRACKET,
    ",": TokenType.COMMA,       ";": TokenType.SEMICOLON,   "^": TokenType.CARET,
    ":": TokenType.COLON,       ":=": TokenType.COLON_EQUAL, "+": TokenType.PLUS,
    "+=": TokenType.PLUS_EQUAL, "-": TokenType.MINUS,       "-=": TokenType.MINUS_EQUAL,
    "->": TokenType.ARROW,      "*": TokenType.STAR,        "*=": TokenType.STAR_EQUAL,
    "/": TokenType.SLASH,       "/=": TokenType.SLASH_EQUAL, "%": TokenType.PERCENT,
    "%=": TokenType.PERCENT_EQUAL, ">": TokenType.GREATER,  ">=": TokenType.GREATER_EQUAL,
    "<": TokenType.LESSER,      "<=": TokenType.LESSER_EQUAL, "!": TokenType.BANG,
    "!=": TokenType.BANG_EQUAL, "&": TokenType.AMP,         "&&": TokenType.AMP_AMP,
    "||": TokenType.BAR_BAR,    "=": TokenType.EQUAL,       "==": TokenType.EQUAL_EQUAL,
    ".": TokenType.DOT,         "..": TokenType.DOT_DOT,
}

ESCAPES = {
    "n": "\n", "t": "\t", "b": "\b", "r": "\r",
    "a": "\a", "f": "\f", "v": "\v", "0": "\0", "\\": "\\",
}
MAX_INTEGER = str(2**64 - 1)


def is_digit(char: str) -> bool:
    return "0" <= char <= "9"


def is_alpha(char: str) -> bool:
    return "a" <= char <= "z" or "A" <= char <= "Z" or char == "_"


class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.current = 0
        self.line = 1
        self.col = 1
        self.start = Pos(0, 1, 1)
        self.tokens: list[Token] = []

    def peek(self, offset: int = 0) -> str:
        index = self.current + offset
        return self.source[index] if index < len(self.source) else ""

    def advance(self) -> str:
        char = self.source[self.current]
        self.current += 1
        if char == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return char

    def emit(self, token_type: TokenType, value: None | int | float | str = None):
        lexeme = self.source[self.start.idx:self.current]
        self.tokens.append(Token(lexeme, token_type, self.start, value))

    def error(self, code: int, message: str):
        print(
            f"LexerError({code}) [line:{self.start.line}, col:{self.start.col}]: {message}",
            file=sys.stderr,
        )
        self.emit(TokenType.ERROR)

    def identifier(self):
        while is_alpha(self.peek()) or is_digit(self.peek()):
            self.advance()
        lexeme = self.source[self.start.idx:self.current]
        token_type = KEYWORDS.get(lexeme, TokenType.IDENT)
        value = None
        if token_type in (TokenType.TRUE, TokenType.FALSE):
            value = int(token_type == TokenType.TRUE)
        self.emit(token_type, value)

    def number(self):
        has_dot = False
        while is_digit(self.peek()):
            self.advance()
        # A decimal point requires a following digit; never consume the '..' slice operator.
        if not has_dot and self.peek() == "." and is_digit(self.peek(1)):
            has_dot = True
            self.advance()
            while is_digit(self.peek()):
                self.advance()

        lexeme = self.source[self.start.idx:self.current]
        if has_dot:
            try:
                value = struct.unpack("!f", struct.pack("!f", float(lexeme)))[0]
            except (OverflowError, ValueError):
                value = math.inf
            if not math.isfinite(value):
                self.error(6, "Float literal is too large for f32")
            else:
                self.emit(TokenType.FLOAT, value)
            return

        # Check before int() so arbitrarily long input cannot exceed Python's digit limit.
        digits = lexeme.lstrip("0") or "0"
        if len(digits) > len(MAX_INTEGER) or (
            len(digits) == len(MAX_INTEGER) and digits > MAX_INTEGER
        ):
            self.error(3, "Integer literal is too large for u64")
        else:
            self.emit(TokenType.INTEGER, int(digits))

    def quoted(self, quote: str):
        value: list[str] = []
        error: tuple[int, str] | None = None
        while self.peek() and self.peek() not in ("\n", "\r"):
            char = self.advance()
            if char == quote:
                if error is not None:
                    self.error(*error)
                elif quote == "'" and len(value) != 1:
                    self.error(4, "Char literal must contain exactly one ASCII character")
                elif quote == "'":
                    self.emit(TokenType.CHAR, ord(value[0]))
                else:
                    self.emit(TokenType.STRING, "".join(value))
                return

            if char == "\\":
                if not self.peek() or self.peek() in ("\n", "\r"):
                    break
                escaped = self.advance()
                if escaped == quote:
                    value.append(quote)
                elif escaped in ESCAPES:
                    value.append(ESCAPES[escaped])
                elif error is None:
                    error = (5, f"Invalid escape sequence {('\\' + escaped)!r}")
            elif " " <= char <= "~":
                value.append(char)
            elif error is None:
                code = 4 if quote == "'" else 1
                error = (code, "Literal contains a non-printable or non-ASCII character")

        # Leave the line break for scan(); recovery must not swallow the next line.
        if quote == "'":
            self.error(4, "Unterminated char literal")
        else:
            self.error(2, "Unterminated string literal")

    def scan(self) -> list[Token]:
        while self.current < len(self.source):
            self.start = Pos(self.current, self.line, self.col)
            char = self.advance()
            if char in " \t\r\n":
                continue
            if char == "/" and self.peek() == "/":
                while self.peek() and self.peek() != "\n":
                    self.advance()
                continue
            if is_alpha(char):
                self.identifier()
            elif is_digit(char):
                self.number()
            elif char in ("'", '"'):
                self.quoted(char)
            else:
                operator = char + self.peek()
                if len(operator) == 2 and operator in OPERATORS:
                    self.advance()
                    self.emit(OPERATORS[operator])
                elif char in OPERATORS:
                    self.emit(OPERATORS[char])
                else:
                    self.error(1, f"Unexpected character {char!r}")

        self.start = Pos(self.current, self.line, self.col)
        self.emit(TokenType.EOF)
        return self.tokens


def lexer(source: str) -> list[Token]:
    """Tokenize mid source, reporting recoverable errors to stderr.

    Positions use a zero-based source index and one-based lines/columns. Literal
    values are u64-range Python ints, f32-rounded floats, ASCII character codes,
    decoded ASCII strings, and 0/1 for booleans. Other tokens have no value.

    Agreed refinements to the draft specification: decimal points require
    digits on both sides, signs are separate tokens, and quoted literals are
    limited to printable ASCII plus supported escapes. Float overflow uses
    LexerError(6).
    """
    return Lexer(source).scan()

__all__ = ["lexer"]
