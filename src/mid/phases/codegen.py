from typing import cast

from llvmlite import ir
ir.types.ir_layer_typed_pointers_enabled = False

from mid.types.ast import * # pyright: ignore[reportWildcardImportFromLibrary]

i32 = ir.IntType(32)

def declare_builtin_symbols(module: ir.Module) -> dict[str, ir.Function]:
    return {
        "print_i32": ir.Function(module, ir.FunctionType(ir.VoidType(), [i32]), name="__builtin_print_i32")
    }


def generate_ir(ast: AST) -> str:
    active_scope: dict[str, ir.Instruction] = {}

    module = ir.Module(name="main")
    builtins = declare_builtin_symbols(module)

    function = ir.Function(module, ir.FunctionType(i32, []), name="main")
    entry = function.append_basic_block(name="entry")
    builder = ir.IRBuilder(entry)

    def generate_program(program: Program):
        for stmt in program.stmts:
            match stmt:
                case Decl() as decl:
                    generate_decl(decl)
                case Assign() as assign:
                    generate_assign(assign)
                case Print() as print:
                    generate_print(print)

    def generate_decl(decl: Decl):
        var = builder.alloca(i32, name=decl.name)
        active_scope[decl.name] = var

    def generate_assign(assign: Assign):
        var = active_scope[assign.target]
        temp = generate_expr(assign.value)
        builder.store(temp, var)

    def generate_print(print: Print):
        expr = generate_expr(print.expr)
        builder.call(builtins["print_i32"], [expr])

    def generate_expr(expr: Expr) -> ir.Instruction | ir.Constant:
        match expr:
            case Ident() as ident:
                var = active_scope[ident.name]
                return builder.load(var)
            case Number() as num:
                return ir.Constant(i32, num.val)
            case BinaryExpr() as expr:
                return generate_binary_expr(expr)

    def generate_binary_expr(expr: BinaryExpr) -> ir.Instruction:
        left = generate_expr(expr.left)
        right = generate_expr(expr.right)
        match expr.op:
            case BinaryExpr.Op.ADD:
                op = builder.add
            case BinaryExpr.Op.SUB:
                op = builder.sub
            case BinaryExpr.Op.MULT:
                op = builder.mul
            case BinaryExpr.Op.DIV:
                op = builder.sdiv
        var = cast(ir.Instruction, op(left, right))
        return var

    generate_program(ast.program)
    builder.ret(ir.Constant(i32, 0))
    return str(module)
