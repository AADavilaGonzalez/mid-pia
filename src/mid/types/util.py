from dataclasses import dataclass

@dataclass
class Pos:
    idx: int
    line: int
    col: int

@dataclass
class Span:
    start: Pos
    end: Pos
