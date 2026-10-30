from dataclasses import dataclass

from mid.types.util import Pos

@dataclass
class LexerError(Exception):
    msg: str
    pos: Pos

    def __post_init__(self):
        super().__init__(self.msg)

    def __str__(self) -> str:
        line = self.pos.line
        col = self.pos.col
        return f"LexerError[line: {line}, col: {col}]: {self.msg}"

@dataclass
class ParserError(Exception):
    msg: str
    pos: Pos

    def __post_init__(self):
        super().__init__(self.msg)

    def __str__(self) -> str:
        line = self.pos.line
        col = self.pos.col
        return f"ParserError[line: {line}, col: {col}]: {self.msg}"

@dataclass
class AnalyzerError(Exception):
    msg: str
    pos: Pos

    def __post_init__(self):
        super().__init__(self.msg)

    def __str__(self) -> str:
        line = self.pos.line
        col = self.pos.col
        return f"AnalyzerError[line: {line}, col: {col}]: {self.msg}"

Error = LexerError | ParserError | AnalyzerError
