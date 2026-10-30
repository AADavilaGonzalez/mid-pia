from enum import Enum, auto
from dataclasses import dataclass

from mid.types.util import Span

@dataclass
class Ident:
    name: str
    span: Span

@dataclass
class Number:
    val: int
    span: Span

@dataclass
class BinaryExpr:
    class Op(Enum):
        ADD = auto()
        SUB = auto()
        MULT = auto()
        DIV = auto()
    left: Expr
    op: Op
    right: Expr

Expr = BinaryExpr | Ident | Number

@dataclass
class Decl:
    name: str
    span: Span

@dataclass
class Assign:
    target: str
    value: Expr
    span: Span

@dataclass
class Print:
    expr: Expr
    span: Span

Stmt = Decl | Assign | Print

@dataclass
class Program:
    stmts: list[Stmt]

@dataclass
class AST:
    program: Program
