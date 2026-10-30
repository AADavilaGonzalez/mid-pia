import string
from dataclasses import replace

from mid.types.errors import LexerError
from mid.types.token import Token, TokenType
from mid.types.util import Span, Pos

whitespace = string.whitespace

KEYWORDS = {
   "i32": TokenType.TYPE_I32,
   "print": TokenType.PRINT
}

SYMBOLS = {
    "=": TokenType.EQUAL,
    ":": TokenType.COLON,
    ";": TokenType.SEMICOLON,
    "(": TokenType.LPAREN,
    ")": TokenType.RPAREN,
    "+": TokenType.PLUS,
    "-": TokenType.MINUS,
    "*": TokenType.STAR,
    "/": TokenType.SLASH,
}

def is_digit(char: str) -> bool:
    return "0" <= char <= "9"

def is_alpha(char: str) -> bool:
    return "a" <= char <= "z" or "A" <= char <= "Z" or char == "_"

def is_alphanum(char: str) -> bool:
    return is_alpha(char) or is_digit(char)

def lex(source: str) -> tuple[list[Token], list[LexerError]]:
# Context
    errors: list[LexerError] = []
    tokens: list[Token] = []
    span = Span(start=Pos(0,1,1), end=Pos(0,1,1))

# API
    def lexeme() -> str:
        return source[span.start.idx:span.end.idx]

    def peek(offset: int = 0) -> str:
        idx = span.end.idx + offset
        return source[idx] if idx < len(source) else ""

    def advance() -> str:
        nonlocal span
        if span.end.idx >= len(source):
            return ""
        char = source[span.end.idx]
        span.end.idx += 1
        if char == "\n":
            span.end.line += 1
            span.end.col = 1
        else:
            span.end.col += 1
        return char

    def emit(type: TokenType):
        tokens.append(Token(lexeme(), type, span.start))

# Implementation
    def identifier():
        while is_alphanum(peek()):
            advance()
        emit(KEYWORDS.get(lexeme(), TokenType.IDENT))

    def number():
        while is_digit(peek()):
            advance()
        emit(TokenType.NUMBER)

    def error(msg: str):
        errors.append(LexerError(msg, span.start))

    while span.end.idx < len(source):
        span.start = replace(span.end)
        char = advance()
        if char in whitespace   : continue
        elif char in SYMBOLS    : emit(SYMBOLS[char])
        elif is_alpha(char)     : identifier()
        elif is_digit(char)     : number()
        else: error(f"Unexpected character: {char!r}")

    emit(TokenType.EOF)
    return tokens, errors
