from mid.types.ast import * # pyright: ignore[reportWildcardImportFromLibrary]
from mid.types.errors import AnalyzerError
from mid.types.util import Pos

def analyze(ast: AST) -> tuple[AST, list[AnalyzerError]]:
    errors: list[AnalyzerError] = []
    active_scope: set[str] = set()

    def error(msg: str, pos: Pos):
        errors.append(AnalyzerError(msg, pos))

    def declare(name: str, pos: Pos):
        if name in active_scope:
            error("Variable redeclaration not allowed", pos)
        active_scope.add(name)

    def ensure_declared(name: str, pos: Pos):
        if name not in active_scope:
            error("Variable used before declaration", pos)

    def analyze_program(program: Program):
        for stmt in program.stmts:
            match stmt:
                case Decl() as decl:
                    declare(decl.name, decl.span.start)
                case Assign() as assign:
                    ensure_declared(assign.target, assign.span.start)
                    analyze_expr(assign.value)
                case Print() as print:
                    analyze_expr(print.expr)

    def analyze_expr(expr: Expr):
        match expr:
            case Ident() as ident:
                ensure_declared(ident.name, ident.span.start)
            case Number() as num:
                if num.val >= 1 << 31:
                    error("Literal exceeds i32 limit", num.span.start)
            case BinaryExpr() as expr:
                analyze_expr(expr.left)
                analyze_expr(expr.right)

    analyze_program(ast.program)
    return ast, errors
