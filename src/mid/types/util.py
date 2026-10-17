from dataclasses import dataclass

@dataclass(slots=True)
class Pos:
    idx: int
    line: int
    col: int

@dataclass(slots=True)
class Span:
    start: Pos
    end: Pos
