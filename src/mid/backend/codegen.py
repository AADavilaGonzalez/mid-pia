"""LLVM IR code generator for Mid (docs/stages/codegen.md)."""

from typing import Any

from llvmlite import ir

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
    ReturnStmt,
    SliceExpr,
    Stmt,
    String,
    UnaryExpr,
    VarDecl,
)
from mid.types.sem_type import (
    BOOL,
    ERROR,
    F32,
    I32,
    INTEGER_TYPES,
    U8,
    U32,
    USIZE,
    VOID,
    Array,
    SemType,
)
from mid.types.symbol_table import Symbol, SymbolKind, SymbolTable

TARGET_TRIPLE = "x86_64-pc-none-elf"
DATA_LAYOUT = (
    "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
)

ASSIGN_TO_BIN_OP = {
    AssignStmt.Op.ADD: BinaryExpr.Op.ADD,
    AssignStmt.Op.SUB: BinaryExpr.Op.SUB,
    AssignStmt.Op.MULT: BinaryExpr.Op.MULT,
    AssignStmt.Op.DIV: BinaryExpr.Op.DIV,
    AssignStmt.Op.MOD: BinaryExpr.Op.MOD,
}

CMP_OP_STR = {
    BinaryExpr.Op.EQUAL: "==",
    BinaryExpr.Op.NOT_EQUAL: "!=",
    BinaryExpr.Op.LESSER: "<",
    BinaryExpr.Op.LESSER_EQUAL: "<=",
    BinaryExpr.Op.GREATER: ">",
    BinaryExpr.Op.GREATER_EQUAL: ">=",
}


def ir_type(ty: SemType | None) -> ir.Type:
    """Translate a Mid SemType recursively into an llvmlite.ir.Type."""
    if ty is None or ty == ERROR:
        raise AssertionError(f"Invalid semantic type in codegen: {ty!r}")

    if ty.is_pointer:
        return ir.PointerType(ir_type(ty.inner()))

    if ty.is_array:
        qual = ty.qual[0]
        assert isinstance(qual, Array)
        return ir.ArrayType(ir_type(ty.inner()), qual.size)

    if ty.is_slice:
        elem_ptr_ty = ir.PointerType(ir_type(ty.inner()))
        return ir.LiteralStructType([elem_ptr_ty, ir.IntType(64)])

    if ty in (U8, BOOL):
        return ir.IntType(8)
    if ty in (I32, U32):
        return ir.IntType(32)
    if ty == F32:
        return ir.FloatType()
    if ty == USIZE:
        return ir.IntType(64)
    if ty == VOID:
        return ir.VoidType()

    raise AssertionError(f"Unhandled SemType in ir_type: {ty!r}")


def _unwrap_parens(expr: Expr) -> Expr:
    """Unwrap any synthetic ParenExpr wrapper nodes if present."""
    curr = expr
    while type(curr).__name__ == "ParenExpr":
        inner = getattr(curr, "value", getattr(curr, "expr", None))
        if inner is None:
            break
        curr = inner
    return curr


def _has_side_effects(expr: Expr | None) -> bool:
    """True if expression could cause runtime side effects (e.g. contains CallExpr)."""
    if expr is None:
        return False
    curr = _unwrap_parens(expr)
    if isinstance(curr, CallExpr):
        return True
    if isinstance(curr, (UnaryExpr, DereferenceExpr)):
        val = getattr(curr, "value", None)
        return _has_side_effects(val)
    if isinstance(curr, BinaryExpr):
        return _has_side_effects(curr.left) or _has_side_effects(curr.right)
    if isinstance(curr, CastExpr):
        return _has_side_effects(curr.value)
    if isinstance(curr, IndexExpr):
        return _has_side_effects(curr.target) or _has_side_effects(curr.index)
    if isinstance(curr, SliceExpr):
        return (
            _has_side_effects(curr.target)
            or _has_side_effects(curr.low)
            or _has_side_effects(curr.high)
        )
    if isinstance(curr, FieldExpr):
        return _has_side_effects(curr.target)
    return False


class CodeGenerator:
    """Translates an annotated Mid AST and SymbolTable into an LLVM IR Module."""

    def __init__(self, ast: AST, st: SymbolTable):
        self.ast = ast
        self.st = st
        self.module = ir.Module(name="mid")
        self.module.triple = TARGET_TRIPLE
        self.module.data_layout = DATA_LAYOUT

        self.env: dict[Symbol, ir.Value] = {}
        self.runtime_fns: dict[str, ir.Function] = {}
        self.builder: ir.IRBuilder | None = None
        self.alloca_builder: ir.IRBuilder | None = None
        self.current_fn_decl: FnDecl | None = None
        self.init_globals_fn: ir.Function | None = None
        self.loop_stack: list[dict[str, Any]] = []
        self.str_counter: int = 0

    def generate(self) -> ir.Module:
        program = self.ast.program
        if isinstance(program, ErrorNode):
            raise AssertionError("ErrorNode encountered at program root")

        # Pass 1: Declare standard-library runtime externs, globals, and function prototypes
        self._declare_stdlib()
        for decl in program.decl:
            if isinstance(decl, ErrorNode):
                raise AssertionError("ErrorNode encountered in top-level declarations")
            elif isinstance(decl, VarDecl):
                self._declare_global(decl)
            elif isinstance(decl, FnDecl):
                self._declare_function(decl)
            else:
                raise AssertionError(f"Unexpected top-level declaration: {decl!r}")

        # Pass 2: Emit global initializers and function bodies
        self._emit_global_initializers(program.decl)
        for decl in program.decl:
            if isinstance(decl, FnDecl):
                self._emit_function_body(decl)

        return self.module

    # ------------------------------------------------------------------
    # Helpers: Booleans, Indices, Addressability, Runtime Declarations
    # ------------------------------------------------------------------

    def _to_i1(self, val: ir.Value) -> ir.Value:
        """Convert canonical i8 boolean R-Value into i1 branch condition."""
        assert self.builder is not None
        if val.type == ir.IntType(1):
            return val
        return self.builder.icmp_unsigned("!=", val, ir.Constant(ir.IntType(8), 0))

    def _to_i8(self, val_i1: ir.Value) -> ir.Value:
        """Zero-extend i1 comparison/branch result into canonical i8 boolean."""
        assert self.builder is not None
        if val_i1.type == ir.IntType(8):
            return val_i1
        return self.builder.zext(val_i1, ir.IntType(8))

    def _to_i64(self, expr: Expr) -> ir.Value:
        """Evaluate an integer index or slice bound and coerce to i64."""
        assert self.builder is not None
        val = self._gen_rvalue(expr)
        ty = expr.ty
        if ty == USIZE:
            return val
        if ty == I32:
            return self.builder.sext(val, ir.IntType(64))
        if ty in (U8, U32):
            return self.builder.zext(val, ir.IntType(64))
        raise AssertionError(f"Unexpected index type in _to_i64: {ty!r}")

    def _is_addressable(self, expr: Expr) -> bool:
        """True if expr can be evaluated in L-Value context."""
        expr = _unwrap_parens(expr)
        if isinstance(expr, Identifier):
            return expr.symbol is not None and expr.symbol.kind in (
                SymbolKind.VARIABLE,
                SymbolKind.PARAMETER,
            )
        if isinstance(expr, DereferenceExpr):
            return True
        if isinstance(expr, IndexExpr):
            target_ty = expr.target.ty
            if target_ty is None or target_ty == ERROR:
                return False
            return target_ty.is_slice or (
                target_ty.is_array and self._is_addressable(expr.target)
            )
        return False

    def _make_slice(self, slice_ty: ir.Type, ptr: ir.Value, length: ir.Value) -> ir.Value:
        """Construct a { T*, i64 } slice struct from base pointer and i64 length."""
        assert self.builder is not None
        sl = ir.Constant(slice_ty, ir.Undefined)
        sl = self.builder.insert_value(sl, ptr, 0)
        sl = self.builder.insert_value(sl, length, 1)
        return sl

    def _get_runtime_fn(self, name: str) -> ir.Function:
        """Declare on demand and return the prefixed C runtime function for a stdlib symbol."""
        if name in self.runtime_fns:
            return self.runtime_fns[name]

        i8_ty = ir.IntType(8)
        i8_ptr_ty = ir.PointerType(i8_ty)
        i64_ty = ir.IntType(64)

        if name == "eof":
            fn_ty = ir.FunctionType(i8_ty, [])
            sym_name = "mid_eof"
        elif name == "getline":
            fn_ty = ir.FunctionType(i64_ty, [i8_ptr_ty, i64_ty, i8_ptr_ty])
            sym_name = "mid_getline"
        elif name == "read":
            fn_ty = ir.FunctionType(i64_ty, [i8_ptr_ty, i64_ty])
            sym_name = "mid_read"
        elif name == "write":
            fn_ty = ir.FunctionType(ir.VoidType(), [i8_ptr_ty, i64_ty])
            sym_name = "mid_write"
        else:
            raise AssertionError(f"Unknown built-in function: {name!r}")

        fn = ir.Function(self.module, fn_ty, name=sym_name)
        self.runtime_fns[name] = fn
        return fn

    def _declare_stdlib(self) -> None:
        """Eagerly declare all standard-library runtime prototypes in Pass 1."""
        for name in ("eof", "getline", "read", "write"):
            self._get_runtime_fn(name)

    # ------------------------------------------------------------------
    # Pass 1: Declarations
    # ------------------------------------------------------------------

    def _declare_global(self, decl: VarDecl) -> None:
        assert decl.symbol is not None and decl.ty is not None
        ty = ir_type(decl.ty)
        gv = ir.GlobalVariable(self.module, ty, name=decl.name)
        gv.linkage = "internal"
        gv.initializer = ir.Constant(ty, None)
        self.env[decl.symbol] = gv

    def _declare_function(self, decl: FnDecl) -> None:
        assert decl.symbol is not None
        if decl.name == "main":
            ret_ty = ir.IntType(32)
        elif decl.ret_type is None:
            ret_ty = ir.VoidType()
        else:
            ret_ty = ir_type(decl.ret_type.ty)

        param_tys = [ir_type(p.ty) for p in decl.params]
        fn_ty = ir.FunctionType(ret_ty, param_tys)
        func = ir.Function(self.module, fn_ty, name=decl.name)
        if decl.name != "main":
            func.linkage = "internal"

        for arg, param in zip(func.args, decl.params):
            arg.name = param.name

        self.env[decl.symbol] = func

    # ------------------------------------------------------------------
    # Pass 2: Globals & Function Bodies
    # ------------------------------------------------------------------

    def _try_const_literal(self, expr: Expr) -> ir.Constant | None:
        expr = _unwrap_parens(expr)
        if isinstance(expr, Int):
            return ir.Constant(ir_type(expr.ty), expr.val)
        if isinstance(expr, Float):
            return ir.Constant(ir.FloatType(), float(expr.val))
        if isinstance(expr, Bool):
            return ir.Constant(ir.IntType(8), 1 if expr.val else 0)
        if isinstance(expr, Char):
            return ir.Constant(ir.IntType(8), expr.val)
        if isinstance(expr, UnaryExpr) and expr.op == UnaryExpr.Op.NEGATE:
            inner = _unwrap_parens(expr.value)
            if isinstance(inner, Int):
                return ir.Constant(ir_type(expr.ty), -inner.val)
            if isinstance(inner, Float):
                return ir.Constant(ir.FloatType(), -float(inner.val))
        return None

    def _emit_global_initializers(self, decls: list) -> None:
        dynamic_globals: list[VarDecl] = []
        seen_dynamic = False

        for decl in decls:
            if isinstance(decl, ErrorNode):
                raise AssertionError("ErrorNode encountered in global initializers")
            if not isinstance(decl, VarDecl):
                continue
            if decl.init is None:
                continue
            if not seen_dynamic:
                const_val = self._try_const_literal(decl.init)
                if const_val is not None:
                    gv = self.env[decl.symbol]
                    assert isinstance(gv, ir.GlobalVariable)
                    gv.initializer = const_val
                    continue
            seen_dynamic = True
            dynamic_globals.append(decl)

        if not dynamic_globals:
            return

        fn_ty = ir.FunctionType(ir.VoidType(), [])
        init_fn = ir.Function(self.module, fn_ty, name="__mid_init_globals")
        init_fn.linkage = "internal"
        self.init_globals_fn = init_fn

        entry_bb = init_fn.append_basic_block(name="entry")
        self.alloca_builder = ir.IRBuilder(entry_bb)
        self.builder = ir.IRBuilder(entry_bb)
        self.current_fn_decl = None

        for decl in dynamic_globals:
            assert decl.init is not None and decl.symbol is not None
            val = self._gen_rvalue(decl.init)
            gv = self.env[decl.symbol]
            self.builder.store(val, gv)

        self.builder.ret_void()
        self.builder = None
        self.alloca_builder = None

    def _alloca(self, ty: ir.Type, name: str = "") -> ir.AllocaInstr:
        assert self.alloca_builder is not None and self.builder is not None
        ptr = self.alloca_builder.alloca(ty, name=name)
        if self.builder.block is self.alloca_builder.block:
            self.builder.position_at_end(self.builder.block)
        return ptr

    def _emit_function_body(self, decl: FnDecl) -> None:
        assert decl.symbol is not None
        func = self.env[decl.symbol]
        assert isinstance(func, ir.Function)

        self.current_fn_decl = decl
        self.loop_stack.clear()
        entry_bb = func.append_basic_block(name="entry")
        self.alloca_builder = ir.IRBuilder(entry_bb)
        self.builder = ir.IRBuilder(entry_bb)

        if decl.name == "main" and self.init_globals_fn is not None:
            self.builder.call(self.init_globals_fn, [])

        # Allocate stack slots for parameters to support mutability
        for param, arg in zip(decl.params, func.args):
            assert param.symbol is not None and param.ty is not None
            param_ty = ir_type(param.ty)
            param_ptr = self._alloca(param_ty, name=param.name)
            self.builder.store(arg, param_ptr)
            self.env[param.symbol] = param_ptr

        self._gen_block(decl.block)

        if not self.builder.block.is_terminated:
            if decl.name == "main":
                self.builder.ret(ir.Constant(ir.IntType(32), 0))
            elif decl.ret_type is None:
                self.builder.ret_void()
            else:
                raise AssertionError(
                    f"Function '{decl.name}' with return type '{decl.ret_type}' reached end of body without terminator"
                )

        self.current_fn_decl = None
        self.builder = None
        self.alloca_builder = None

    # ------------------------------------------------------------------
    # Statements and Control Flow
    # ------------------------------------------------------------------

    def _gen_block(self, block: Block) -> None:
        assert self.builder is not None
        for stmt in block.stmts:
            if self.builder.block.is_terminated:
                break
            self._gen_stmt(stmt)

    def _gen_stmt(self, stmt: Stmt) -> None:
        assert self.builder is not None
        if isinstance(stmt, ErrorNode):
            raise AssertionError("ErrorNode encountered in statement")
        if isinstance(stmt, VarDecl):
            self._gen_local_var_decl(stmt)
        elif isinstance(stmt, ReturnStmt):
            self._gen_return_stmt(stmt)
        elif isinstance(stmt, ExprStmt):
            self._gen_rvalue(stmt.expr)
        elif isinstance(stmt, AssignStmt):
            self._gen_assign_stmt(stmt)
        elif isinstance(stmt, IfStmt):
            self._gen_if_stmt(stmt)
        elif isinstance(stmt, LoopStmt):
            self._gen_loop_stmt(stmt)
        elif isinstance(stmt, BreakStmt):
            self._gen_break_stmt(stmt)
        elif isinstance(stmt, ContinueStmt):
            self._gen_continue_stmt(stmt)
        else:
            raise AssertionError(f"Unhandled statement type: {type(stmt).__name__}")

    def _gen_local_var_decl(self, decl: VarDecl) -> None:
        assert self.builder is not None
        assert decl.symbol is not None and decl.ty is not None
        ty = ir_type(decl.ty)
        ptr = self._alloca(ty, name=decl.name)
        self.env[decl.symbol] = ptr

        if decl.init is not None:
            val = self._gen_rvalue(decl.init)
            self.builder.store(val, ptr)
        else:
            self.builder.store(ir.Constant(ty, None), ptr)

    def _gen_return_stmt(self, stmt: ReturnStmt) -> None:
        assert self.builder is not None and self.current_fn_decl is not None
        if self.current_fn_decl.name == "main":
            self.builder.ret(ir.Constant(ir.IntType(32), 0))
        elif self.current_fn_decl.ret_type is None:
            self.builder.ret_void()
        else:
            assert stmt.value is not None
            val = self._gen_rvalue(stmt.value)
            if stmt.value.ty == BOOL:
                val = self._to_i8(val)
            self.builder.ret(val)

    def _gen_assign_stmt(self, stmt: AssignStmt) -> None:
        assert self.builder is not None
        target_ptr = self._gen_lvalue(stmt.target)
        if stmt.op == AssignStmt.Op.DIRECT:
            rhs_val = self._gen_rvalue(stmt.val)
            self.builder.store(rhs_val, target_ptr)
        else:
            curr_val = self.builder.load(target_ptr)
            rhs_val = self._gen_rvalue(stmt.val)
            bin_op = ASSIGN_TO_BIN_OP[stmt.op]
            res_val = self._emit_arith_op(bin_op, stmt.target.ty, curr_val, rhs_val)
            self.builder.store(res_val, target_ptr)

    def _gen_if_stmt(self, stmt: IfStmt) -> None:
        assert self.builder is not None
        func = self.builder.function
        merge_bb = ir.Block(func, "if.merge")
        merge_reachable = False

        num_branches = len(stmt.branches)
        for i, branch in enumerate(stmt.branches):
            cond_val = self._gen_rvalue(branch.cond)
            cond_i1 = self._to_i1(cond_val)

            then_bb = self.builder.append_basic_block(f"if.then.{i}")
            is_last = i == num_branches - 1
            if is_last and stmt.else_body is None:
                next_bb = merge_bb
            else:
                next_bb = self.builder.append_basic_block(f"if.next.{i}")

            self.builder.cbranch(cond_i1, then_bb, next_bb)

            self.builder.position_at_end(then_bb)
            self._gen_block(branch.body)
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_bb)
                merge_reachable = True

            if next_bb is not merge_bb:
                self.builder.position_at_end(next_bb)

        if stmt.else_body is not None:
            self._gen_block(stmt.else_body)
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_bb)
                merge_reachable = True
        else:
            merge_reachable = True

        if merge_reachable:
            if merge_bb not in func.basic_blocks:
                func.basic_blocks.append(merge_bb)
            self.builder.position_at_end(merge_bb)

    def _gen_loop_stmt(self, stmt: LoopStmt) -> None:
        assert self.builder is not None
        func = self.builder.function
        loop_head_bb = self.builder.append_basic_block("loop.head")
        loop_exit_bb = ir.Block(func, "loop.exit")
        loop_ctx = {
            "head": loop_head_bb,
            "exit": loop_exit_bb,
            "exit_reachable": False,
        }

        self.builder.branch(loop_head_bb)
        self.loop_stack.append(loop_ctx)

        self.builder.position_at_end(loop_head_bb)
        self._gen_block(stmt.body)
        if not self.builder.block.is_terminated:
            self.builder.branch(loop_head_bb)

        ctx = self.loop_stack.pop()
        if ctx["exit_reachable"]:
            func.basic_blocks.append(loop_exit_bb)
            self.builder.position_at_end(loop_exit_bb)

    def _gen_break_stmt(self, _stmt: BreakStmt) -> None:
        assert self.builder is not None and self.loop_stack
        ctx = self.loop_stack[-1]
        ctx["exit_reachable"] = True
        self.builder.branch(ctx["exit"])

    def _gen_continue_stmt(self, _stmt: ContinueStmt) -> None:
        assert self.builder is not None and self.loop_stack
        ctx = self.loop_stack[-1]
        self.builder.branch(ctx["head"])

    # ------------------------------------------------------------------
    # Expressions
    # ------------------------------------------------------------------

    def _gen_array_ptr(self, target: Expr) -> ir.Value:
        """Obtain a pointer [N x T]* to an array expression (allocating a stack temporary if needed)."""
        assert self.builder is not None and target.ty is not None
        if self._is_addressable(target):
            return self._gen_lvalue(target)
        arr_val = self._gen_rvalue(target)
        temp_ptr = self._alloca(ir_type(target.ty), name="arr.tmp")
        self.builder.store(arr_val, temp_ptr)
        return temp_ptr

    def _gen_index_ptr(self, expr: IndexExpr) -> ir.Value:
        """Compute the element pointer T* for an IndexExpr on an array or slice."""
        assert self.builder is not None
        target_ty = expr.target.ty
        assert target_ty is not None

        if target_ty.is_array:
            arr_ptr = self._gen_array_ptr(expr.target)
            idx_i64 = self._to_i64(expr.index)
            zero_i64 = ir.Constant(ir.IntType(64), 0)
            return self.builder.gep(arr_ptr, [zero_i64, idx_i64])

        if target_ty.is_slice:
            slice_val = self._gen_rvalue(expr.target)
            idx_i64 = self._to_i64(expr.index)
            base_ptr = self.builder.extract_value(slice_val, 0)
            return self.builder.gep(base_ptr, [idx_i64])

        raise AssertionError(f"Cannot index type: {target_ty!r}")

    def _gen_lvalue(self, expr: Expr) -> ir.Value:
        expr = _unwrap_parens(expr)
        if isinstance(expr, ErrorNode):
            raise AssertionError("ErrorNode encountered in L-Value")
        if isinstance(expr, Identifier):
            assert expr.symbol is not None
            return self.env[expr.symbol]
        if isinstance(expr, DereferenceExpr):
            return self._gen_rvalue(expr.value)
        if isinstance(expr, IndexExpr):
            return self._gen_index_ptr(expr)
        raise AssertionError(f"Expression is not an L-Value: {type(expr).__name__}")

    def _gen_rvalue(self, expr: Expr) -> ir.Value:
        assert self.builder is not None
        expr = _unwrap_parens(expr)

        if isinstance(expr, ErrorNode):
            raise AssertionError("ErrorNode encountered in expression")

        if isinstance(expr, Int):
            return ir.Constant(ir_type(expr.ty), expr.val)

        if isinstance(expr, Float):
            return ir.Constant(ir.FloatType(), float(expr.val))

        if isinstance(expr, Bool):
            return ir.Constant(ir.IntType(8), 1 if expr.val else 0)

        if isinstance(expr, Char):
            return ir.Constant(ir.IntType(8), expr.val)

        if isinstance(expr, String):
            return self._gen_string_literal(expr)

        if isinstance(expr, Identifier):
            ptr = self._gen_lvalue(expr)
            return self.builder.load(ptr, name=expr.name)

        if isinstance(expr, UnaryExpr):
            return self._gen_unary_expr(expr)

        if isinstance(expr, BinaryExpr):
            return self._gen_binary_expr(expr)

        if isinstance(expr, CastExpr):
            return self._gen_cast_expr(expr)

        if isinstance(expr, DereferenceExpr):
            ptr = self._gen_rvalue(expr.value)
            return self.builder.load(ptr)

        if isinstance(expr, IndexExpr):
            elem_ptr = self._gen_index_ptr(expr)
            return self.builder.load(elem_ptr)

        if isinstance(expr, SliceExpr):
            return self._gen_slice_expr(expr)

        if isinstance(expr, FieldExpr):
            return self._gen_field_expr(expr)

        if isinstance(expr, CallExpr):
            return self._gen_call_expr(expr)

        raise AssertionError(f"Unhandled expression type: {type(expr).__name__}")

    def _gen_string_literal(self, expr: String) -> ir.Value:
        assert self.builder is not None
        raw_bytes = expr.val.encode("latin-1")
        n = len(raw_bytes)
        arr_ty = ir.ArrayType(ir.IntType(8), n + 1)

        gv = ir.GlobalVariable(self.module, arr_ty, name=f".str.{self.str_counter}")
        self.str_counter += 1
        gv.linkage = "private"
        gv.global_constant = False
        gv.initializer = ir.Constant(arr_ty, bytearray(raw_bytes + b"\x00"))

        zero_i64 = ir.Constant(ir.IntType(64), 0)
        ptr = self.builder.gep(gv, [zero_i64, zero_i64])
        length = ir.Constant(ir.IntType(64), n)
        return self._make_slice(ir_type(U8.slice()), ptr, length)

    def _gen_slice_expr(self, expr: SliceExpr) -> ir.Value:
        assert self.builder is not None
        target_ty = expr.target.ty
        assert target_ty is not None and expr.ty is not None
        zero_i64 = ir.Constant(ir.IntType(64), 0)

        if target_ty.is_array:
            arr_ptr = self._gen_array_ptr(expr.target)
            low_i64 = self._to_i64(expr.low) if expr.low is not None else zero_i64
            qual = target_ty.qual[0]
            assert isinstance(qual, Array)
            high_i64 = (
                self._to_i64(expr.high)
                if expr.high is not None
                else ir.Constant(ir.IntType(64), qual.size)
            )
            new_ptr = self.builder.gep(arr_ptr, [zero_i64, low_i64])
        elif target_ty.is_slice:
            slice_val = self._gen_rvalue(expr.target)
            low_i64 = self._to_i64(expr.low) if expr.low is not None else zero_i64
            high_i64 = (
                self._to_i64(expr.high)
                if expr.high is not None
                else self.builder.extract_value(slice_val, 1)
            )
            base_ptr = self.builder.extract_value(slice_val, 0)
            new_ptr = self.builder.gep(base_ptr, [low_i64])
        else:
            raise AssertionError(f"Cannot slice type: {target_ty!r}")

        new_len = self.builder.sub(high_i64, low_i64)
        return self._make_slice(ir_type(expr.ty), new_ptr, new_len)

    def _gen_field_expr(self, expr: FieldExpr) -> ir.Value:
        assert self.builder is not None
        assert expr.name == "len"
        target_ty = expr.target.ty
        assert target_ty is not None

        if target_ty.is_array:
            # Preserve side effects only if the target contains function calls/side effects,
            # avoiding unnecessary heavy loads of large arrays into SSA values.
            if _has_side_effects(expr.target):
                self._gen_rvalue(expr.target)
            qual = target_ty.qual[0]
            assert isinstance(qual, Array)
            return ir.Constant(ir.IntType(64), qual.size)

        if target_ty.is_slice:
            slice_val = self._gen_rvalue(expr.target)
            return self.builder.extract_value(slice_val, 1)

        raise AssertionError(f"Cannot access .len on type: {target_ty!r}")

    def _gen_unary_expr(self, expr: UnaryExpr) -> ir.Value:
        assert self.builder is not None
        if expr.op == UnaryExpr.Op.NEGATE:
            inner = _unwrap_parens(expr.value)
            if isinstance(inner, Int):
                return ir.Constant(ir_type(expr.ty), -inner.val)
            if isinstance(inner, Float):
                return ir.Constant(ir.FloatType(), -float(inner.val))
            val = self._gen_rvalue(expr.value)
            if expr.ty == F32:
                return self.builder.fneg(val)
            return self.builder.neg(val)

        if expr.op == UnaryExpr.Op.NOT:
            val = self._gen_rvalue(expr.value)
            return self.builder.xor(val, ir.Constant(ir.IntType(8), 1))

        if expr.op == UnaryExpr.Op.ADDRESS:
            return self._gen_lvalue(expr.value)

        raise AssertionError(f"Unhandled unary operator: {expr.op}")

    def _emit_arith_op(
        self, op: BinaryExpr.Op, ty: SemType | None, left: ir.Value, right: ir.Value
    ) -> ir.Value:
        assert self.builder is not None and ty is not None
        if op == BinaryExpr.Op.ADD:
            return self.builder.fadd(left, right) if ty == F32 else self.builder.add(left, right)
        if op == BinaryExpr.Op.SUB:
            return self.builder.fsub(left, right) if ty == F32 else self.builder.sub(left, right)
        if op == BinaryExpr.Op.MULT:
            return self.builder.fmul(left, right) if ty == F32 else self.builder.mul(left, right)
        if op == BinaryExpr.Op.DIV:
            if ty == F32:
                return self.builder.fdiv(left, right)
            if ty == I32:
                return self.builder.sdiv(left, right)
            return self.builder.udiv(left, right)
        if op == BinaryExpr.Op.MOD:
            if ty == I32:
                return self.builder.srem(left, right)
            return self.builder.urem(left, right)
        raise AssertionError(f"Unhandled arithmetic operator: {op}")

    def _gen_short_circuit(self, expr: BinaryExpr) -> ir.Value:
        assert self.builder is not None
        func = self.builder.function
        is_and = expr.op == BinaryExpr.Op.AND
        prefix = "and" if is_and else "or"

        a_val = self._gen_rvalue(expr.left)
        a_i1 = self._to_i1(a_val)
        lhs_block = self.builder.block

        rhs_bb = self.builder.append_basic_block(f"{prefix}.rhs")
        merge_bb = ir.Block(func, f"{prefix}.merge")

        if is_and:
            self.builder.cbranch(a_i1, rhs_bb, merge_bb)
        else:
            self.builder.cbranch(a_i1, merge_bb, rhs_bb)

        self.builder.position_at_end(rhs_bb)
        b_val = self._gen_rvalue(expr.right)
        b_i1 = self._to_i1(b_val)
        rhs_block = self.builder.block
        self.builder.branch(merge_bb)

        func.basic_blocks.append(merge_bb)
        self.builder.position_at_end(merge_bb)
        phi = self.builder.phi(ir.IntType(1), name=f"{prefix}.res")
        short_circuit_const = ir.Constant(ir.IntType(1), 0 if is_and else 1)
        phi.add_incoming(short_circuit_const, lhs_block)
        phi.add_incoming(b_i1, rhs_block)
        return self._to_i8(phi)

    def _gen_binary_expr(self, expr: BinaryExpr) -> ir.Value:
        assert self.builder is not None
        if expr.op in (BinaryExpr.Op.AND, BinaryExpr.Op.OR):
            return self._gen_short_circuit(expr)

        left = self._gen_rvalue(expr.left)
        right = self._gen_rvalue(expr.right)

        if expr.op in CMP_OP_STR:
            op_str = CMP_OP_STR[expr.op]
            operand_ty = expr.left.ty
            if operand_ty == F32:
                if expr.op == BinaryExpr.Op.NOT_EQUAL:
                    cmp_i1 = self.builder.fcmp_unordered("!=", left, right)
                else:
                    cmp_i1 = self.builder.fcmp_ordered(op_str, left, right)
            elif operand_ty == I32:
                cmp_i1 = self.builder.icmp_signed(op_str, left, right)
            else:
                cmp_i1 = self.builder.icmp_unsigned(op_str, left, right)
            return self._to_i8(cmp_i1)

        return self._emit_arith_op(expr.op, expr.ty, left, right)

    def _gen_cast_expr(self, expr: CastExpr) -> ir.Value:
        assert self.builder is not None
        src_ty = expr.value.ty
        dst_ty = expr.ty
        assert src_ty is not None and dst_ty is not None

        val = self._gen_rvalue(expr.value)
        target_ir_ty = ir_type(dst_ty)

        # Identity or same bit-width / representation no-ops
        if src_ty == dst_ty:
            return val
        if src_ty in (I32, U32) and dst_ty in (I32, U32):
            return val
        if src_ty == BOOL and dst_ty == U8:
            return val

        # Integer -> bool
        if dst_ty == BOOL and src_ty in INTEGER_TYPES:
            cmp_i1 = self.builder.icmp_unsigned("!=", val, ir.Constant(val.type, 0))
            return self._to_i8(cmp_i1)

        # bool -> wider integer (i32, u32, usize)
        if src_ty == BOOL and dst_ty in INTEGER_TYPES:
            return self.builder.zext(val, target_ir_ty)

        # Integer -> Integer
        if src_ty in INTEGER_TYPES and dst_ty in INTEGER_TYPES:
            assert isinstance(val.type, ir.IntType) and isinstance(target_ir_ty, ir.IntType)
            if target_ir_ty.width < val.type.width:
                return self.builder.trunc(val, target_ir_ty)
            if target_ir_ty.width > val.type.width:
                if src_ty == I32:
                    return self.builder.sext(val, target_ir_ty)
                return self.builder.zext(val, target_ir_ty)
            return val

        # Integer -> f32
        if src_ty in INTEGER_TYPES and dst_ty == F32:
            if src_ty == I32:
                return self.builder.sitofp(val, ir.FloatType())
            return self.builder.uitofp(val, ir.FloatType())

        # f32 -> Integer
        if src_ty == F32 and dst_ty in INTEGER_TYPES:
            if dst_ty == I32:
                return self.builder.fptosi(val, target_ir_ty)
            return self.builder.fptoui(val, target_ir_ty)

        # ^T -> ^u8 or ^u8 -> ^T
        if src_ty.is_pointer and dst_ty.is_pointer:
            return self.builder.bitcast(val, target_ir_ty)

        raise AssertionError(f"Unhandled cast from {src_ty!r} to {dst_ty!r}")

    def _gen_builtin_call(self, sym: Symbol, expr: CallExpr) -> ir.Value:
        assert self.builder is not None
        fn = self._get_runtime_fn(sym.name)
        slice_ty = ir_type(U8.slice())

        if sym.name == "eof":
            return self.builder.call(fn, [])

        if sym.name == "write":
            buff_val = self._gen_rvalue(expr.args[0])
            ptr = self.builder.extract_value(buff_val, 0)
            length = self.builder.extract_value(buff_val, 1)
            return self.builder.call(fn, [ptr, length])

        if sym.name == "read":
            buff_val = self._gen_rvalue(expr.args[0])
            ptr = self.builder.extract_value(buff_val, 0)
            length = self.builder.extract_value(buff_val, 1)
            ret_len = self.builder.call(fn, [ptr, length])
            return self._make_slice(slice_ty, ptr, ret_len)

        if sym.name == "getline":
            buff_val = self._gen_rvalue(expr.args[0])
            flag_ptr = self._gen_rvalue(expr.args[1])
            ptr = self.builder.extract_value(buff_val, 0)
            length = self.builder.extract_value(buff_val, 1)
            ret_len = self.builder.call(fn, [ptr, length, flag_ptr])
            return self._make_slice(slice_ty, ptr, ret_len)

        raise AssertionError(f"Unhandled built-in function call: {sym.name!r}")

    def _gen_call_expr(self, expr: CallExpr) -> ir.Value:
        assert self.builder is not None
        assert isinstance(expr.callee, Identifier) and expr.callee.symbol is not None
        sym = expr.callee.symbol

        if sym.kind == SymbolKind.BUILTIN_FUNCTION:
            return self._gen_builtin_call(sym, expr)

        fn_val = self.env[sym]
        arg_vals = [
            self._to_i8(self._gen_rvalue(arg)) if arg.ty == BOOL else self._gen_rvalue(arg)
            for arg in expr.args
        ]
        return self.builder.call(fn_val, arg_vals)


def codegen(ast: AST, st: SymbolTable) -> ir.Module:
    """Translate an annotated AST and populated SymbolTable into an LLVM Module."""
    return CodeGenerator(ast, st).generate()


__all__ = ["codegen", "ir_type", "CodeGenerator", "TARGET_TRIPLE", "DATA_LAYOUT"]
