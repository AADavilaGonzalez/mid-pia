from dataclasses import dataclass, replace
from enum import Enum

from mid.types.util import Pos, Span

class TokenType(Enum):
    IDENT = "identifier"
    NUMBER = "number"
    TYPE_I32 = "i32"

    EQUAL = "="
    COLON = ":"
    SEMICOLON = ";"
    LPAREN = "("
    RPAREN = ")"

    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"

    PRINT = "print"

    EOF = "EOF"

@dataclass
class Token:
    lexeme: str
    type: TokenType
    start: Pos

    @property
    def end(self) -> Pos:
        start = self.start
        return replace(start,
            idx=start.idx+len(self.lexeme),
            col=start.col+len(self.lexeme)
        )

    @property
    def span(self) -> Span:
        return Span(self.start, self.end)
