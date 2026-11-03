from dataclasses import dataclass

from mid.types.util import Span


@dataclass
class CompilerError:
    code: int
    span: Span
    message: str
    stage: str

    def __str__(self) -> str:
        start = self.span.start
        return (
            f"{self.stage}Error({self.code}) "
            f"[line:{start.line}, col:{start.col}]: {self.message}"
        )


class LexerError(CompilerError):
    def __init__(self, code: int, span: Span, message: str):
        super().__init__(code, span, message, "Lexer")


class ParserError(CompilerError):
    def __init__(self, code: int, span: Span, message: str):
        super().__init__(code, span, message, "Parser")


class AnalyzerError(CompilerError):
    def __init__(self, code: int, span: Span, message: str):
        super().__init__(code, span, message, "Analyzer")


Error = LexerError | ParserError | AnalyzerError

__all__ = [
    "CompilerError",
    "LexerError",
    "ParserError",
    "AnalyzerError",
    "Error",
]
