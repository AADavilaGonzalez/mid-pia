from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from mid.types.util import Span


@dataclass
class AST:
    program: Program


@dataclass
class ASTNode:
    span: Span


@dataclass
class Program(ASTNode):
    decl: list[TopLevelDecl]


@dataclass
class FnDecl(ASTNode):
    name: str
    params: list[Param]
    ret_type: Type | None
    block: Block


@dataclass
class VarDecl(ASTNode):
    name: str
    type: Type | None
    init: Expr | None


TopLevelDecl = FnDecl | VarDecl


@dataclass
class Type(ASTNode):
    class Pointer:
        pass

    @dataclass
    class Array:
        size: int

    class Slice:
        pass

    Qualifier = Pointer | Array | Slice

    qual: list[Qualifier]
    name: str


@dataclass
class Char(ASTNode):
    val: int


@dataclass
class Bool(ASTNode):
    val: bool


@dataclass
class Int(ASTNode):
    val: int


@dataclass
class Float(ASTNode):
    val: float


@dataclass
class String(ASTNode):
    val: str


@dataclass
class Identifier(ASTNode):
    name: str




@dataclass
class BinaryExpr(ASTNode):
    class Op(Enum):
        OR = auto()
        AND = auto()
        EQUAL = auto()
        NOT_EQUAL = auto()
        GREATER = auto()
        LESSER = auto()
        GREATER_EQUAL = auto()
        LESSER_EQUAL = auto()
        ADD = auto()
        SUB = auto()
        MULT = auto()
        DIV = auto()
        MOD = auto()
    left: Expr
    op: Op
    right: Expr




@dataclass
class UnaryExpr(ASTNode):
    class Op(Enum):
        NOT = auto()
        NEGATE = auto()
        ADDRESS = auto()
    op: Op
    value: Expr


@dataclass
class CastExpr(ASTNode):
    value: Expr
    type: Type


@dataclass
class CallExpr(ASTNode):
    callee: Expr
    args: list[Expr]


@dataclass
class IndexExpr(ASTNode):
    target: Expr
    index: Expr


@dataclass
class DereferenceExpr(ASTNode):
    value: Expr


# PostfixExpr remains a useful common type for expression nodes produced by
# postfix parsing, even though each postfix operation has its own node.
PostfixExpr = CallExpr | IndexExpr | DereferenceExpr

Expr = (
    Identifier
    | Char
    | Bool
    | Int
    | Float
    | String
    | BinaryExpr
    | UnaryExpr
    | CastExpr
    | CallExpr
    | IndexExpr
    | DereferenceExpr
)


@dataclass
class ExprStmt(ASTNode):
    expr: Expr


@dataclass
class AssignStmt(ASTNode):
    class Op(Enum):
        DIRECT = auto()
        ADD = auto()
        SUB = auto()
        MULT = auto()
        DIV = auto()
        MOD = auto()

    target: Expr
    op: Op
    val: Expr


@dataclass
class IfStmt(ASTNode):
    @dataclass
    class Branch(ASTNode):
        cond: Expr
        body: Block

    branches: list[Branch]
    else_body: Block | None


@dataclass
class LoopStmt(ASTNode):
    body: Block


@dataclass
class ReturnStmt(ASTNode):
    value: Expr | None


@dataclass
class ContinueStmt(ASTNode):
    pass


@dataclass
class BreakStmt(ASTNode):
    pass


Stmt = (
    VarDecl
    | ExprStmt
    | AssignStmt
    | IfStmt
    | LoopStmt
    | ReturnStmt
    | ContinueStmt
    | BreakStmt
)


@dataclass
class Block(ASTNode):
    stmts: list[Stmt]


@dataclass
class Param(ASTNode):
    name: str
    type: Type
