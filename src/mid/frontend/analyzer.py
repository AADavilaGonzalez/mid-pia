"""Semantic analyzer for Mid (docs/stages/semantics.md).

Input: AST produced by the parser (it may contain ``ErrorNode`` nodes).
Output: ``(ast, symbol_table, errors)``.

The same AST is returned, annotated in place:

- ``node.ty`` (a ``SemType``) on every expression, on every ``VarDecl`` and
  ``Param`` (the variable's type) and on every ``Type`` node (the resolved
  type). Expressions whose analysis failed get ``ERROR``.
- ``node.symbol`` on every ``Identifier`` (the symbol it refers to, including
  the callee of a call) and on every ``VarDecl``, ``Param`` and ``FnDecl``
  that was declared successfully. ``symbol.is_global`` tells globals apart
  from locals.

A unary ``-`` applied directly to an ``Int`` node is a single negative literal:
both nodes get the literal's type, and ``Int.val`` keeps the absolute value
(``-2147483648`` is ``UnaryExpr(NEGATE, Int(2147483648))`` typed ``i32``).

Errors are collected as ``AnalyzerError`` objects; nothing is printed.
"""

from copy import copy

from mid.types.ast import (
    AST,
    AssignStmt,
    BinaryExpr,
    Block,
    Bool,
    BreakStmt,
    CallExpr,
    CastExpr,
    Char,
    ContinueStmt,
    DereferenceExpr,
    ErrorNode,
    Expr,
    ExprStmt,
    FieldExpr,
    Float,
    FnDecl,
    Identifier,
    IfStmt,
    IndexExpr,
    Int,
    LoopStmt,
    Program,
    ReturnStmt,
    SliceExpr,
    Stmt,
    String,
    Type,
    UnaryExpr,
    VarDecl,
)
from mid.types.errors import AnalyzerError
from mid.types.sem_type import (
    BOOL,
    ERROR,
    F32,
    I32,
    INTEGER_RANGES,
    INTEGER_TYPES,
    U8,
    USIZE,
    VOID,
    Array,
    Pointer,
    SemType,
    Slice,
)
from mid.types.symbol_table import ScopeKind, Symbol, SymbolKind, SymbolTable
from mid.types.util import Span

E_UNDECLARED = 1
E_DUPLICATE = 2
E_TYPE_NAME = 3
E_MISMATCH = 4
E_OPERANDS = 5
E_ASSIGN = 6
E_CALL = 7
E_CAST = 8
E_ACCESS = 9
E_CONTROL = 10
E_MAIN = 11

Op = BinaryExpr.Op

ARITHMETIC_OPS = {Op.ADD, Op.SUB, Op.MULT, Op.DIV, Op.MOD}
ORDER_OPS = {Op.GREATER, Op.LESSER, Op.GREATER_EQUAL, Op.LESSER_EQUAL}
EQUALITY_OPS = {Op.EQUAL, Op.NOT_EQUAL}
LOGIC_OPS = {Op.OR, Op.AND}

OP_TEXT = {
    Op.OR: "||", Op.AND: "&&", Op.EQUAL: "==", Op.NOT_EQUAL: "!=",
    Op.GREATER: ">", Op.LESSER: "<", Op.GREATER_EQUAL: ">=", Op.LESSER_EQUAL: "<=",
    Op.ADD: "+", Op.SUB: "-", Op.MULT: "*", Op.DIV: "/", Op.MOD: "%",
}

COMPOUND_OPS = {
    AssignStmt.Op.ADD: Op.ADD,
    AssignStmt.Op.SUB: Op.SUB,
    AssignStmt.Op.MULT: Op.MULT,
    AssignStmt.Op.DIV: Op.DIV,
    AssignStmt.Op.MOD: Op.MOD,
}


# ----------------------------------------------------------------------
# Type rules that do not depend on analyzer state
# ----------------------------------------------------------------------

def compatible(actual: SemType, expected: SemType) -> bool:
    """Exact type compatibility. ERROR is compatible with everything."""
    return actual == expected or ERROR in (actual, expected)


def valid_cast(src: SemType, dst: SemType) -> bool:
    """Cast table from docs/stages/semantics.md."""
    if ERROR in (src, dst) or src == dst:
        return True
    if src in INTEGER_TYPES:
        return dst in INTEGER_TYPES or dst in (F32, BOOL)
    if src == F32:
        return dst in INTEGER_TYPES
    if src == BOOL:
        return dst in INTEGER_TYPES
    if src.is_pointer and dst.is_pointer:
        return src == U8.pointer() or dst == U8.pointer()
    return False


def binary_operands_ok(op: Op, left: SemType, right: SemType) -> bool:
    if left != right:
        return False
    if op in LOGIC_OPS:
        return left == BOOL
    if op in EQUALITY_OPS:
        return left.is_numeric or left == BOOL
    if op == Op.MOD:
        return left.is_integer
    return left.is_numeric  # + - * / and ordering


def is_flexible(expr: Expr) -> bool:
    """True for expressions whose type comes from their context: integer
    literals and arithmetic made only of integer literals."""
    if isinstance(expr, Int):
        return True
    if isinstance(expr, UnaryExpr) and expr.op == UnaryExpr.Op.NEGATE:
        return is_flexible(expr.value)
    if isinstance(expr, BinaryExpr) and expr.op in ARITHMETIC_OPS:
        return is_flexible(expr.left) and is_flexible(expr.right)
    return False


def block_returns(block: Block) -> bool:
    return any(stmt_returns(stmt) for stmt in block.stmts)


def stmt_returns(stmt: Stmt) -> bool:
    """Conservative "always returns" rules from docs/stages/semantics.md."""
    if isinstance(stmt, ReturnStmt):
        return True
    if isinstance(stmt, IfStmt):
        return (
            stmt.else_body is not None
            and all(block_returns(branch.body) for branch in stmt.branches)
            and block_returns(stmt.else_body)
        )
    if isinstance(stmt, LoopStmt):
        return not has_break(stmt.body)
    return False


def has_break(block: Block) -> bool:
    """True if ``block`` contains a break that exits the enclosing loop
    (breaks inside nested loops do not count)."""
    for stmt in block.stmts:
        if isinstance(stmt, BreakStmt):
            return True
        if isinstance(stmt, IfStmt):
            bodies = [branch.body for branch in stmt.branches]
            if stmt.else_body is not None:
                bodies.append(stmt.else_body)
            if any(has_break(body) for body in bodies):
                return True
    return False


# ----------------------------------------------------------------------
# Analyzer
# ----------------------------------------------------------------------

class Analyzer:
    def __init__(self):
        self.table = SymbolTable()
        self.errors: list[AnalyzerError] = []
        self.return_type: SemType = VOID  # of the function being analyzed
        self.loop_depth = 0

    def error(self, code: int, span: Span, message: str):
        self.errors.append(AnalyzerError(code, span, message))

    def declare(self, symbol: Symbol, span: Span) -> bool:
        """Define ``symbol`` in the current scope, reporting conflicts."""
        existing = self.table.define(symbol)
        if existing is None:
            return True
        where = ""
        if existing.span is not None:
            where = f" (line {existing.span.start.line})"
        self.error(
            E_DUPLICATE, span,
            f"'{symbol.name}' is already declared as a {existing.describe()}{where}",
        )
        return False

    # ------------------------------------------------------------------
    # Program
    # ------------------------------------------------------------------

    def analyze(self, ast: AST) -> tuple[AST, SymbolTable, list[AnalyzerError]]:
        program = ast.program
        # 1. Predeclare every global function and variable.
        for decl in program.decl:
            if isinstance(decl, FnDecl):
                self.declare_function(decl)
            elif isinstance(decl, VarDecl):
                self.declare_global(decl)
        # 2. Global initializers, in source order.
        for decl in program.decl:
            if isinstance(decl, VarDecl):
                self.global_initializer(decl)
        # 3. main
        self.check_main(program)
        # 4. Function bodies.
        for decl in program.decl:
            if isinstance(decl, FnDecl):
                self.function_body(decl)
        return ast, self.table, self.errors

    def declare_function(self, decl: FnDecl):
        params = [self.resolve_type(param.type) for param in decl.params]
        for param, type_ in zip(decl.params, params):
            param.ty = type_
        ret = VOID if decl.ret_type is None else self.resolve_type(decl.ret_type)
        if not decl.name:  # the parser already reported the missing name
            return
        symbol = Symbol(
            decl.name, SymbolKind.FUNCTION,
            parameters=params, return_type=ret, span=decl.span,
        )
        if self.declare(symbol, decl.span):
            decl.symbol = symbol

    def declare_global(self, decl: VarDecl):
        # A ':=' global has no type until its initializer is analyzed.
        type_ = None if decl.type is None else self.resolve_type(decl.type)
        decl.ty = type_
        symbol = Symbol(decl.name, SymbolKind.VARIABLE, type=type_, span=decl.span, mutable=True)
        if self.declare(symbol, decl.span):
            decl.symbol = symbol

    def global_initializer(self, decl: VarDecl):
        if decl.init is None:
            return
        if decl.type is None:
            type_ = self.expr(decl.init)
            decl.ty = type_
            if decl.symbol is not None:
                decl.symbol.type = type_
        else:
            self.check_value(decl.init, decl.ty, f"in the initialization of '{decl.name}'")

    def check_main(self, program: Program):
        symbol = self.table.global_scope.lookup_local("main")
        if symbol is None:
            start = program.span.start
            self.error(E_MAIN, Span(start, copy(start)), "The program must define 'fn main()'")
        elif symbol.kind != SymbolKind.FUNCTION:
            self.error(E_MAIN, symbol.span, "'main' must be a function declared as 'fn main()'")
        elif symbol.parameters or symbol.return_type != VOID:
            self.error(
                E_MAIN, symbol.span,
                "'main' must take no parameters and have no return type: 'fn main()'",
            )

    def function_body(self, decl: FnDecl):
        ret = VOID
        if decl.ret_type is not None and decl.ret_type.ty is not None:
            ret = decl.ret_type.ty
        self.return_type = ret
        self.loop_depth = 0
        self.table.enter_scope(ScopeKind.FUNCTION)
        for param in decl.params:
            symbol = Symbol(
                param.name, SymbolKind.PARAMETER, type=param.ty, span=param.span, mutable=True,
            )
            if self.declare(symbol, param.span):
                param.symbol = symbol
        # The body's statements live directly in the function scope.
        for stmt in decl.block.stmts:
            self.statement(stmt)
        self.table.exit_scope()
        if ret not in (VOID, ERROR) and not block_returns(decl.block):
            self.error(
                E_CONTROL, decl.span,
                f"Function '{decl.name}' must return a value of type '{ret}' on every path",
            )

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    def resolve_type(self, node: Type) -> SemType:
        symbol = self.table.lookup(node.name)
        result = ERROR
        if symbol is None:
            self.error(E_TYPE_NAME, node.span, f"Unknown type '{node.name}'")
        elif symbol.kind != SymbolKind.TYPE:
            self.error(E_TYPE_NAME, node.span, f"'{node.name}' is a {symbol.describe()}, not a type")
        else:
            qualifiers = []
            valid = True
            for qualifier in node.qual:
                if isinstance(qualifier, Type.Pointer):
                    qualifiers.append(Pointer())
                elif isinstance(qualifier, Type.Array):
                    if qualifier.size < 1:
                        self.error(E_TYPE_NAME, node.span, "Array size must be greater than zero")
                        valid = False
                    qualifiers.append(Array(qualifier.size))
                else:
                    qualifiers.append(Slice())
            if valid:
                result = SemType(node.name, tuple(qualifiers))
        node.ty = result
        return result

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------

    def statement(self, stmt: Stmt):
        if isinstance(stmt, VarDecl):
            self.local_var_decl(stmt)
        elif isinstance(stmt, ExprStmt):
            self.expr(stmt.expr, void_ok=True)
        elif isinstance(stmt, AssignStmt):
            self.assign_stmt(stmt)
        elif isinstance(stmt, IfStmt):
            for branch in stmt.branches:
                self.condition(branch.cond)
                self.block(branch.body)
            if stmt.else_body is not None:
                self.block(stmt.else_body)
        elif isinstance(stmt, LoopStmt):
            self.loop_depth += 1
            self.block(stmt.body)
            self.loop_depth -= 1
        elif isinstance(stmt, ReturnStmt):
            self.return_stmt(stmt)
        elif isinstance(stmt, (BreakStmt, ContinueStmt)):
            if self.loop_depth == 0:
                word = "break" if isinstance(stmt, BreakStmt) else "continue"
                self.error(E_CONTROL, stmt.span, f"'{word}' outside of a loop")
        # ErrorNode: already reported by the parser.

    def block(self, block: Block):
        self.table.enter_scope(ScopeKind.BLOCK)
        for stmt in block.stmts:
            self.statement(stmt)
        self.table.exit_scope()

    def local_var_decl(self, decl: VarDecl):
        # The initializer is checked before the name becomes visible.
        if decl.type is not None:
            type_ = self.resolve_type(decl.type)
            if decl.init is not None:
                self.check_value(decl.init, type_, f"in the initialization of '{decl.name}'")
        else:
            type_ = self.expr(decl.init) if decl.init is not None else ERROR
        decl.ty = type_
        symbol = Symbol(decl.name, SymbolKind.VARIABLE, type=type_, span=decl.span, mutable=True)
        if self.declare(symbol, decl.span):
            decl.symbol = symbol

    def condition(self, cond: Expr):
        type_ = self.expr(cond, BOOL)
        if not compatible(type_, BOOL):
            self.error(E_MISMATCH, cond.span, f"Condition must be 'bool', found '{type_}'")

    def return_stmt(self, stmt: ReturnStmt):
        ret = self.return_type
        if stmt.value is None:
            if ret not in (VOID, ERROR):
                self.error(E_CONTROL, stmt.span, f"Missing return value of type '{ret}'")
        elif ret == VOID:
            self.expr(stmt.value, void_ok=True)
            self.error(E_CONTROL, stmt.span, "A function without return type cannot return a value")
        else:
            self.check_value(stmt.value, ret, "in the return value")

    def assign_stmt(self, stmt: AssignStmt):
        target = stmt.target
        # Functions, built-ins and types are protected symbols.
        if isinstance(target, Identifier):
            symbol = self.table.lookup(target.name)
            if symbol is not None and symbol.kind not in (SymbolKind.VARIABLE, SymbolKind.PARAMETER):
                target.symbol = symbol
                target.ty = ERROR
                self.error(E_ASSIGN, target.span, f"Cannot assign to {symbol.describe()} '{target.name}'")
                self.expr(stmt.val)
                return

        target_type = self.expr(target)
        if target_type != ERROR and not self.addressable(target):
            self.error(E_ASSIGN, target.span, "Invalid assignment target")

        if stmt.op == AssignStmt.Op.DIRECT:
            self.check_value(stmt.val, target_type, "in the assignment")
            return
        op = COMPOUND_OPS[stmt.op]
        value_type = self.expr(stmt.val, target_type)
        if ERROR not in (target_type, value_type) and not binary_operands_ok(op, target_type, value_type):
            self.error(
                E_OPERANDS, stmt.span,
                f"Operator '{OP_TEXT[op]}=' cannot be applied to '{target_type}' and '{value_type}'",
            )

    def check_value(self, expr: Expr, expected: SemType, context: str) -> SemType:
        actual = self.expr(expr, expected)
        if not compatible(actual, expected):
            self.error(E_MISMATCH, expr.span, f"Expected '{expected}' but found '{actual}' {context}")
        return actual

    # ------------------------------------------------------------------
    # Expressions
    # ------------------------------------------------------------------

    def expr(self, expr: Expr, expected: SemType | None = None, void_ok: bool = False) -> SemType:
        """Type ``expr`` (and annotate it). ``expected`` is the type its
        context wants; it only decides the type of integer literals."""
        if expected == ERROR:
            expected = None
        type_ = self._expr(expr, expected)
        if type_ == VOID and not void_ok:
            self.error(E_CALL, expr.span, "This call returns no value and cannot be used as a value")
            type_ = ERROR
        expr.ty = type_
        return type_

    def _expr(self, expr: Expr, expected: SemType | None) -> SemType:
        match expr:
            case Int():
                return self.int_literal(expr, expr.val, expected)
            case Float():
                return F32
            case Char():
                return U8
            case Bool():
                return BOOL
            case String():
                return U8.slice()
            case Identifier():
                return self.identifier(expr)
            case BinaryExpr():
                return self.binary(expr, expected)
            case UnaryExpr():
                return self.unary(expr, expected)
            case CastExpr():
                return self.cast(expr)
            case CallExpr():
                return self.call(expr)
            case IndexExpr():
                return self.index(expr)
            case SliceExpr():
                return self.slice(expr)
            case FieldExpr():
                return self.field(expr)
            case DereferenceExpr():
                return self.dereference(expr)
        return ERROR  # ErrorNode: already reported by the parser

    def int_literal(self, node: Expr, value: int, expected: SemType | None) -> SemType:
        type_ = expected if expected in INTEGER_RANGES else I32
        low, high = INTEGER_RANGES[type_]
        if not low <= value <= high:
            self.error(E_MISMATCH, node.span, f"Integer literal {value} does not fit in type '{type_}'")
        return type_

    def identifier(self, expr: Identifier) -> SemType:
        symbol = self.table.lookup(expr.name)
        if symbol is None:
            self.error(E_UNDECLARED, expr.span, f"Name '{expr.name}' is not declared")
            return ERROR
        expr.symbol = symbol
        if symbol.kind == SymbolKind.TYPE:
            self.error(E_MISMATCH, expr.span, f"'{expr.name}' is a type, not a value")
            return ERROR
        if symbol.is_function:
            self.error(E_CALL, expr.span, f"Function '{expr.name}' cannot be used as a value")
            return ERROR
        if symbol.type is None:
            self.error(
                E_UNDECLARED, expr.span,
                f"Global '{expr.name}' is used before its declaration "
                "(its type comes from its initializer)",
            )
            return ERROR
        return symbol.type

    def binary(self, expr: BinaryExpr, expected: SemType | None) -> SemType:
        op = expr.op
        left_flexible, right_flexible = is_flexible(expr.left), is_flexible(expr.right)
        if left_flexible and right_flexible:
            context = expected if op in ARITHMETIC_OPS else None
            left = self.expr(expr.left, context)
            right = self.expr(expr.right, context)
        elif left_flexible:
            right = self.expr(expr.right)
            left = self.expr(expr.left, right)
        elif right_flexible:
            left = self.expr(expr.left)
            right = self.expr(expr.right, left)
        else:
            left = self.expr(expr.left)
            right = self.expr(expr.right)

        result_on_error = ERROR if op in ARITHMETIC_OPS else BOOL
        if ERROR in (left, right):
            return result_on_error
        if binary_operands_ok(op, left, right):
            return left if op in ARITHMETIC_OPS else BOOL
        if left != right:
            message = (
                f"Operator '{OP_TEXT[op]}' requires operands of the same type, "
                f"found '{left}' and '{right}'"
            )
        else:
            message = f"Operator '{OP_TEXT[op]}' cannot be applied to '{left}'"
        self.error(E_OPERANDS, expr.span, message)
        return result_on_error

    def unary(self, expr: UnaryExpr, expected: SemType | None) -> SemType:
        if expr.op == UnaryExpr.Op.NEGATE:
            if isinstance(expr.value, Int):  # negative literal
                type_ = self.int_literal(expr, -expr.value.val, expected)
                expr.value.ty = type_
                return type_
            type_ = self.expr(expr.value, expected if is_flexible(expr.value) else None)
            if type_ == ERROR or type_ in (I32, F32):
                return type_
            self.error(E_OPERANDS, expr.span, f"Unary '-' cannot be applied to '{type_}'")
            return ERROR

        if expr.op == UnaryExpr.Op.NOT:
            type_ = self.expr(expr.value)
            if not compatible(type_, BOOL):
                self.error(E_OPERANDS, expr.span, f"Operator '!' requires 'bool', found '{type_}'")
            return BOOL

        # ADDRESS
        type_ = self.expr(expr.value)
        if type_ == ERROR:
            return ERROR
        if not self.addressable(expr.value):
            self.error(E_ACCESS, expr.span, "Cannot take the address of this expression")
            return ERROR
        return type_.pointer()

    def addressable(self, expr: Expr) -> bool:
        """Variables, parameters, dereferences, and indexing into a slice or
        into an addressable array. Requires ``expr`` to be typed already."""
        if isinstance(expr, Identifier):
            return expr.symbol is not None and expr.symbol.kind in (
                SymbolKind.VARIABLE, SymbolKind.PARAMETER,
            )
        if isinstance(expr, IndexExpr):
            target = expr.target.ty
            if target is None or target == ERROR:
                return False
            return target.is_slice or (target.is_array and self.addressable(expr.target))
        return isinstance(expr, DereferenceExpr)

    def cast(self, expr: CastExpr) -> SemType:
        source = self.expr(expr.value)
        target = self.resolve_type(expr.type)
        if not valid_cast(source, target):
            self.error(E_CAST, expr.span, f"Cannot cast '{source}' to '{target}'")
        return target

    def call(self, expr: CallExpr) -> SemType:
        callee = expr.callee
        symbol = None
        if isinstance(callee, Identifier):
            found = self.table.lookup(callee.name)
            callee.symbol = found
            if found is None:
                self.error(E_UNDECLARED, callee.span, f"Function '{callee.name}' is not declared")
            elif not found.is_function:
                self.error(E_CALL, callee.span, f"'{callee.name}' is a {found.describe()}, not a function")
            else:
                symbol = found
        else:
            self.expr(callee)
            self.error(E_CALL, callee.span, "Only named functions can be called")

        if symbol is None:
            for arg in expr.args:
                self.expr(arg)
            return ERROR

        params = symbol.parameters or []
        if len(expr.args) != len(params):
            self.error(
                E_CALL, expr.span,
                f"Function '{symbol.name}' expects {len(params)} argument(s) "
                f"but {len(expr.args)} were given",
            )
        for i, arg in enumerate(expr.args):
            if i >= len(params):
                self.expr(arg)
                continue
            arg_type = self.expr(arg, params[i])
            if not compatible(arg_type, params[i]):
                self.error(
                    E_CALL, arg.span,
                    f"Argument {i + 1} of '{symbol.name}' must be '{params[i]}', found '{arg_type}'",
                )
        return symbol.return_type

    def index(self, expr: IndexExpr) -> SemType:
        target = self.expr(expr.target)
        index = self.expr(expr.index)
        if index != ERROR and not index.is_integer:
            self.error(E_ACCESS, expr.index.span, f"Index must be an integer, found '{index}'")
        if target == ERROR:
            return ERROR
        if not (target.is_array or target.is_slice):
            self.error(E_ACCESS, expr.span, f"Type '{target}' cannot be indexed")
            return ERROR
        return target.inner()

    def slice(self, expr: SliceExpr) -> SemType:
        target = self.expr(expr.target)
        for bound in (expr.low, expr.high):
            if bound is None:
                continue
            bound_type = self.expr(bound)
            if bound_type != ERROR and not bound_type.is_integer:
                self.error(E_ACCESS, bound.span, f"Range bound must be an integer, found '{bound_type}'")
        if target == ERROR:
            return ERROR
        if target.is_slice:
            return target
        if target.is_array:
            if not self.addressable(expr.target):
                self.error(E_ACCESS, expr.span, "Only arrays stored in variables can be sliced")
            return target.inner().slice()
        self.error(E_ACCESS, expr.span, f"Type '{target}' cannot be sliced")
        return ERROR

    def field(self, expr: FieldExpr) -> SemType:
        target = self.expr(expr.target)
        if target == ERROR:
            return ERROR
        if expr.name != "len":
            self.error(E_ACCESS, expr.span, f"Type '{target}' has no field '{expr.name}'")
            return ERROR
        if target.is_array or target.is_slice:
            return USIZE
        self.error(E_ACCESS, expr.span, f"'.len' requires an array or a slice, found '{target}'")
        return ERROR

    def dereference(self, expr: DereferenceExpr) -> SemType:
        type_ = self.expr(expr.value)
        if type_ == ERROR:
            return ERROR
        if not type_.is_pointer:
            self.error(E_ACCESS, expr.span, f"Cannot dereference non-pointer type '{type_}'")
            return ERROR
        return type_.inner()


def analyzer(ast: AST) -> tuple[AST, SymbolTable, list[AnalyzerError]]:
    """Analyze and annotate ``ast`` in place. Returns (ast, symbol table, errors)."""
    return Analyzer().analyze(ast)


__all__ = ["analyzer", "Analyzer", "valid_cast", "compatible"]
