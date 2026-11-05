"""Complete LLVM IR Code Generation Test Suite (Steps 1, 2, and 3):
- Step 1: Core Module, Types, Declarations, Globals, Functions, and Primitives
- Step 2: Control Flow (if/else, loop/break/continue), Booleans, Short-Circuit Logic, Comparisons (NaN), Assignments, and Casts
- Step 3: Arrays, Slices, String Literals, Pointer Operations, Stdlib Runtime C ABI, and End-to-End Examples
"""

import ctypes
from dataclasses import dataclass
from pathlib import Path

import llvmlite.binding as llvm
import pytest
from llvmlite import ir

from mid.backend.codegen import DATA_LAYOUT, TARGET_TRIPLE, codegen, ir_type
from mid.frontend.analyzer import analyzer
from mid.frontend.lexer import lexer
from mid.frontend.parser import parser
from mid.types.ast import (
    AST,
    ASTNode,
    Block,
    ErrorNode,
    Expr,
    FnDecl,
    Int,
    Program,
    Type,
    UnaryExpr,
    VarDecl,
)
from mid.types.symbol_table import Symbol, SymbolKind, SymbolTable
from mid.types.sem_type import (
    BOOL,
    ERROR,
    F32,
    I32,
    U8,
    U32,
    USIZE,
    VOID,
    Array,
    Pointer,
    SemType,
    Slice,
)
from mid.types.util import Pos, Span

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "examples"

llvm.initialize_native_target()
llvm.initialize_native_asmprinter()


# ----------------------------------------------------------------------
# Standard Library I/O runtime context for test assertions
# ----------------------------------------------------------------------

import io
from mid.backend.runner import (
    JITRunner,
    StreamContext,
    bind_runtime_symbols,
    get_current_context,
    set_current_context,
)

_test_in = io.BytesIO()
_test_out = io.BytesIO()


def reset_stdio(input_bytes: bytes = b"") -> None:
    global _test_in, _test_out
    _test_in = io.BytesIO(input_bytes)
    _test_out = io.BytesIO()
    bind_runtime_symbols()
    set_current_context(StreamContext(_test_in, _test_out))


def get_written_bytes() -> bytes:
    return _test_out.getvalue()


# Initialize test I/O context
reset_stdio()


# ----------------------------------------------------------------------
# Compilation and MCJIT Execution Helpers
# ----------------------------------------------------------------------


def compile_ir(source: str) -> llvm.ModuleRef:
    """Lex, parse, analyze, and generate LLVM IR module for valid Mid source."""
    tokens, lex_errors = lexer(source)
    assert lex_errors == [], f"Lexer errors: {lex_errors}"
    tree, parse_errors = parser(tokens)
    assert parse_errors == [], f"Parser errors: {parse_errors}"
    tree, st, sem_errors = analyzer(tree)
    assert sem_errors == [], f"Analyzer errors: {sem_errors}"
    return codegen(tree, st)


def jit_compile(source: str) -> tuple[llvm.ModuleRef, JITRunner]:
    mod = compile_ir(source)
    return mod, JITRunner(mod)


# ======================================================================
# STEP 1: Core Module, Types, Declarations, and Primitives
# ======================================================================


def test_module_target_triple_and_data_layout():
    mod = compile_ir("fn main() {}")
    assert mod.triple == TARGET_TRIPLE
    assert mod.data_layout == DATA_LAYOUT


def test_ir_type_primitives_and_aggregates():
    assert ir_type(U8) == ir.IntType(8)
    assert ir_type(BOOL) == ir.IntType(8)
    assert ir_type(I32) == ir.IntType(32)
    assert ir_type(U32) == ir.IntType(32)
    assert ir_type(F32) == ir.FloatType()
    assert ir_type(USIZE) == ir.IntType(64)
    assert ir_type(VOID) == ir.VoidType()

    # Pointers
    assert ir_type(I32.pointer()) == ir.PointerType(ir.IntType(32))
    assert ir_type(BOOL.pointer().pointer()) == ir.PointerType(
        ir.PointerType(ir.IntType(8))
    )

    # Arrays
    arr_u8 = SemType("u8", (Array(4),))
    assert ir_type(arr_u8) == ir.ArrayType(ir.IntType(8), 4)
    arr_2d = SemType("i32", (Array(2), Array(3)))
    assert ir_type(arr_2d) == ir.ArrayType(ir.ArrayType(ir.IntType(32), 3), 2)

    # Slices
    assert ir_type(U8.slice()) == ir.LiteralStructType(
        [ir.PointerType(ir.IntType(8)), ir.IntType(64)]
    )

    # Nested qualifiers: ^[3][]u8
    complex_ty = SemType("u8", (Pointer(), Array(3), Slice()))
    expected_slice = ir.LiteralStructType(
        [ir.PointerType(ir.IntType(8)), ir.IntType(64)]
    )
    assert ir_type(complex_ty) == ir.PointerType(ir.ArrayType(expected_slice, 3))

    with pytest.raises(AssertionError):
        ir_type(ERROR)
    with pytest.raises(AssertionError):
        ir_type(None)


def test_minimal_main_returns_zero():
    mod, jit = jit_compile("fn main() {}")
    ir_text = str(mod)
    assert "define i32 @main()" in ir_text
    assert "__mid_init_globals" not in ir_text
    assert jit.call_main() == 0


def test_explicit_return_in_main_and_void_fn():
    source = """
    called: i32 = 0;
    fn do_work() {
        called = 10;
        return;
        called = 99;
    }
    fn main() {
        do_work();
        return;
    }
    """
    _, jit = jit_compile(source)
    assert jit.call_main() == 0
    assert jit.get_global("called", ctypes.c_int32) == 10


def test_helper_function_add_and_linkage():
    source = """
    result: i32;
    fn add(a: i32, b: i32) -> i32 {
        return a + b;
    }
    fn main() {
        result = add(20, 22);
    }
    """
    mod, jit = jit_compile(source)
    ir_text = str(mod)
    assert "define internal i32 @add" in ir_text
    assert "@result = internal global i32 0" in ir_text
    assert jit.call_main() == 0
    assert jit.get_global("result", ctypes.c_int32) == 42
    assert jit.call("add", ctypes.c_int32, (ctypes.c_int32, 20), (ctypes.c_int32, 22)) == 42


def test_alloca_hoisting_and_parameter_mutability():
    source = """
    fn compute(x: i32, y: i32) -> i32 {
        a: i32;
        x += 5;
        b := x * 2;
        y = b - a;
        return y;
    }
    fn main() {}
    """
    mod, jit = jit_compile(source)
    compute_fn = next(f for f in mod.functions if f.name == "compute")
    entry_instrs = list(next(iter(compute_fn.blocks)).instructions)
    allocas = [i for i in entry_instrs if i.opcode == "alloca"]
    assert len(allocas) == 4
    assert entry_instrs[:4] == allocas

    res = jit.call("compute", ctypes.c_int32, (ctypes.c_int32, 10), (ctypes.c_int32, 99))
    assert res == 30


def test_forward_references_and_dynamic_globals():
    source = """
    a: i32 = 10;
    b: i32 = c + get_twenty();
    c: i32 = 5;

    fn main() {
        a = a + b + c;
    }

    fn get_twenty() -> i32 {
        return 20;
    }
    """
    mod, jit = jit_compile(source)
    ir_text = str(mod)
    assert "@a = internal global i32 10" in ir_text
    assert "@b = internal global i32 0" in ir_text
    assert "@c = internal global i32 0" in ir_text
    assert "define internal void @__mid_init_globals()" in ir_text

    assert jit.call_main() == 0
    assert jit.get_global("b", ctypes.c_int32) == 20
    assert jit.get_global("c", ctypes.c_int32) == 5
    assert jit.get_global("a", ctypes.c_int32) == 35


def test_minimum_negative_integer_boundary():
    source = """
    g_min: i32 = -(2147483648);
    fn get_min() -> i32 {
        x: i32 = -((2147483648));
        return x;
    }
    fn main() {}
    """
    mod, jit = jit_compile(source)
    ir_text = str(mod)
    assert "-2147483648" in ir_text
    assert jit.get_global("g_min", ctypes.c_int32) == -2147483648
    assert jit.call("get_min", ctypes.c_int32) == -2147483648


def test_unary_negation_unwraps_synthetic_paren_expr():
    @dataclass
    class ParenExpr(ASTNode):
        value: Expr

    tokens, _ = lexer("fn f() -> i32 { return -1; } fn main() {}")
    tree, _ = parser(tokens)
    tree, st, errors = analyzer(tree)
    assert errors == []

    fn_f = tree.program.decl[0]
    ret_stmt = fn_f.block.stmts[0]
    unary = ret_stmt.value
    assert isinstance(unary, UnaryExpr)
    span = Span(Pos(0, 1, 1), Pos(0, 1, 1))
    inner_int = Int(span, 2147483648, ty=I32)
    unary.value = ParenExpr(span, ParenExpr(span, inner_int, ty=I32), ty=I32)

    mod = codegen(tree, st)
    jit = JITRunner(mod)
    assert jit.call("f", ctypes.c_int32) == -2147483648


def test_signed_vs_unsigned_division_and_modulo():
    source = """
    fn sdiv_test(a: i32, b: i32) -> i32 { return a / b; }
    fn srem_test(a: i32, b: i32) -> i32 { return a % b; }
    fn udiv_test(a: u32, b: u32) -> u32 { return a / b; }
    fn urem_test(a: u32, b: u32) -> u32 { return a % b; }
    fn u8_div(a: u8, b: u8) -> u8 { return a / b; }
    fn usize_mod(a: usize, b: usize) -> usize { return a % b; }
    fn main() {}
    """
    mod, jit = jit_compile(source)
    ir_text = str(mod)
    assert "sdiv i32" in ir_text
    assert "srem i32" in ir_text
    assert "udiv i32" in ir_text
    assert "urem i32" in ir_text
    assert "udiv i8" in ir_text
    assert "urem i64" in ir_text

    assert jit.call("sdiv_test", ctypes.c_int32, (ctypes.c_int32, -7), (ctypes.c_int32, 2)) == -3
    assert jit.call("srem_test", ctypes.c_int32, (ctypes.c_int32, -7), (ctypes.c_int32, 2)) == -1

    u_val = 0xFFFFFFF9
    assert jit.call("udiv_test", ctypes.c_uint32, (ctypes.c_uint32, u_val), (ctypes.c_uint32, 2)) == u_val // 2
    assert jit.call("urem_test", ctypes.c_uint32, (ctypes.c_uint32, u_val), (ctypes.c_uint32, 10)) == u_val % 10
    assert jit.call("u8_div", ctypes.c_uint8, (ctypes.c_uint8, 250), (ctypes.c_uint8, 10)) == 25
    assert jit.call("usize_mod", ctypes.c_uint64, (ctypes.c_uint64, 1000), (ctypes.c_uint64, 300)) == 100


def test_float_bool_and_char_primitives():
    source = """
    fn float_ops(a: f32, b: f32) -> f32 {
        c := -(a + b) * 2.0 / 4.0;
        return c - 0.5;
    }
    fn bool_not(b: bool) -> bool {
        t := true;
        f := false;
        return !b;
    }
    fn char_add(c: u8) -> u8 {
        return 'A' + c;
    }
    fn main() {}
    """
    _, jit = jit_compile(source)
    res_f = jit.call("float_ops", ctypes.c_float, (ctypes.c_float, 1.5), (ctypes.c_float, 2.5))
    assert pytest.approx(res_f) == -2.5
    assert jit.call("bool_not", ctypes.c_uint8, (ctypes.c_uint8, 1)) == 0
    assert jit.call("bool_not", ctypes.c_uint8, (ctypes.c_uint8, 0)) == 1
    assert jit.call("char_add", ctypes.c_uint8, (ctypes.c_uint8, 2)) == ord("C")


# ======================================================================
# STEP 2: Control Flow, Booleans, Logic, Comparisons, and Casts
# ======================================================================


def test_if_else_if_else_and_merge_reuse():
    source = """
    fn classify(x: i32) -> i32 {
        res: i32 = 0;
        if x < 0 {
            res = -1;
        } else if x == 0 {
            res = 0;
        } else if x < 10 {
            res = 1;
        } else {
            res = 2;
        }
        return res;
    }

    fn if_without_else(x: i32) -> i32 {
        y := 10;
        if x > 5 {
            y = 20;
        }
        return y;
    }

    fn all_branches_return(x: i32) -> i32 {
        if x >= 0 {
            return 100;
        } else {
            return -100;
        }
    }

    fn main() {}
    """
    mod, jit = jit_compile(source)

    all_ret_fn = next(f for f in mod.functions if f.name == "all_branches_return")
    block_names = [b.name for b in all_ret_fn.blocks]
    assert "if.merge" not in block_names

    no_else_fn = next(f for f in mod.functions if f.name == "if_without_else")
    no_else_blocks = [b.name for b in no_else_fn.blocks]
    assert "if.merge" in no_else_blocks
    assert not any(name.startswith("if.next") for name in no_else_blocks)

    assert jit.call("classify", ctypes.c_int32, (ctypes.c_int32, -5)) == -1
    assert jit.call("classify", ctypes.c_int32, (ctypes.c_int32, 0)) == 0
    assert jit.call("classify", ctypes.c_int32, (ctypes.c_int32, 7)) == 1
    assert jit.call("classify", ctypes.c_int32, (ctypes.c_int32, 42)) == 2

    assert jit.call("if_without_else", ctypes.c_int32, (ctypes.c_int32, 3)) == 10
    assert jit.call("if_without_else", ctypes.c_int32, (ctypes.c_int32, 8)) == 20

    assert jit.call("all_branches_return", ctypes.c_int32, (ctypes.c_int32, 5)) == 100
    assert jit.call("all_branches_return", ctypes.c_int32, (ctypes.c_int32, -1)) == -100


def test_loops_break_continue_and_nested_loops():
    source = """
    fn count_to_ten() -> i32 {
        i := 0;
        loop {
            if i == 10 {
                break;
            }
            i += 1;
        }
        return i;
    }

    fn sum_evens(limit: i32) -> i32 {
        i := 0;
        sum := 0;
        loop {
            i += 1;
            if i > limit {
                break;
            }
            if i % 2 != 0 {
                continue;
            }
            sum += i;
        }
        return sum;
    }

    fn nested_loops() -> i32 {
        total := 0;
        i := 0;
        loop {
            if i >= 3 {
                break;
            }
            j := 0;
            loop {
                j += 1;
                if j == 2 {
                    continue;
                }
                if j > 3 {
                    break;
                }
                total += 10;
            }
            i += 1;
        }
        return total;
    }

    fn loop_without_break(x: i32) -> i32 {
        loop {
            return x + 1;
        }
    }

    fn main() {}
    """
    mod, jit = jit_compile(source)

    no_break_fn = next(f for f in mod.functions if f.name == "loop_without_break")
    assert "loop.exit" not in [b.name for b in no_break_fn.blocks]

    assert jit.call("count_to_ten", ctypes.c_int32) == 10
    assert jit.call("sum_evens", ctypes.c_int32, (ctypes.c_int32, 10)) == 30
    assert jit.call("nested_loops", ctypes.c_int32) == 60
    assert jit.call("loop_without_break", ctypes.c_int32, (ctypes.c_int32, 41)) == 42


def test_uninitialized_local_in_loop_resets_every_iteration():
    source = """
    fn loop_zero_init() -> i32 {
        i := 0;
        acc := 0;
        loop {
            if i >= 4 {
                break;
            }
            x: i32;
            acc += x;
            x = 99;
            i += 1;
        }
        return acc;
    }
    fn main() {}
    """
    mod, jit = jit_compile(source)
    fn = next(f for f in mod.functions if f.name == "loop_zero_init")
    entry_allocas = [
        ins for ins in next(iter(fn.blocks)).instructions if ins.opcode == "alloca"
    ]
    assert len(entry_allocas) == 3
    assert jit.call("loop_zero_init", ctypes.c_int32) == 0


def test_floating_point_and_nan_comparisons():
    source = """
    fn is_nan_neq(x: f32) -> bool {
        return x != x;
    }
    fn is_nan_eq(x: f32) -> bool {
        return x == x;
    }
    fn nan_ordered_checks(nan_val: f32) -> bool {
        return (nan_val < 1.0) || (nan_val <= 1.0) || (nan_val > 1.0) || (nan_val >= 1.0);
    }
    fn main() {}
    """
    mod, jit = jit_compile(source)
    ir_text = str(mod)
    assert "fcmp une float" in ir_text
    assert "fcmp oeq float" in ir_text

    nan = float("nan")
    assert jit.call("is_nan_neq", ctypes.c_uint8, (ctypes.c_float, nan)) == 1
    assert jit.call("is_nan_eq", ctypes.c_uint8, (ctypes.c_float, nan)) == 0
    assert jit.call("nan_ordered_checks", ctypes.c_uint8, (ctypes.c_float, nan)) == 0

    assert jit.call("is_nan_neq", ctypes.c_uint8, (ctypes.c_float, 3.5)) == 0
    assert jit.call("is_nan_eq", ctypes.c_uint8, (ctypes.c_float, 3.5)) == 1


def test_signed_vs_unsigned_comparisons():
    source = """
    fn s_lt(a: i32, b: i32) -> bool { return a < b; }
    fn u_lt(a: u32, b: u32) -> bool { return a < b; }
    fn main() {}
    """
    _, jit = jit_compile(source)
    assert jit.call("s_lt", ctypes.c_uint8, (ctypes.c_int32, -1), (ctypes.c_int32, 1)) == 1
    assert jit.call("u_lt", ctypes.c_uint8, (ctypes.c_uint32, 0xFFFFFFFF), (ctypes.c_uint32, 1)) == 0


def test_short_circuit_and_or_evaluation():
    source = """
    side_effects: i32 = 0;

    fn bump() -> bool {
        side_effects += 1;
        return true;
    }

    fn test_and(lhs: bool) -> bool {
        return lhs && bump();
    }

    fn test_or(lhs: bool) -> bool {
        return lhs || bump();
    }

    fn main() {}
    """
    _, jit = jit_compile(source)

    assert jit.call("test_and", ctypes.c_uint8, (ctypes.c_uint8, 0)) == 0
    assert jit.get_global("side_effects", ctypes.c_int32) == 0

    assert jit.call("test_and", ctypes.c_uint8, (ctypes.c_uint8, 1)) == 1
    assert jit.get_global("side_effects", ctypes.c_int32) == 1

    assert jit.call("test_or", ctypes.c_uint8, (ctypes.c_uint8, 1)) == 1
    assert jit.get_global("side_effects", ctypes.c_int32) == 1

    assert jit.call("test_or", ctypes.c_uint8, (ctypes.c_uint8, 0)) == 1
    assert jit.get_global("side_effects", ctypes.c_int32) == 2


def test_cast_matrix_and_pointer_deref_compound_assign():
    source = """
    target_val: i32 = 10;
    addr_calls: i32 = 0;

    fn get_target_ptr() -> ^i32 {
        addr_calls += 1;
        return &target_val;
    }

    fn compound_deref() -> i32 {
        get_target_ptr()^ += 25;
        return target_val;
    }

    fn trunc_i32_to_u8(x: i32) -> u8 {
        return x as u8;
    }

    fn sext_i32_to_usize(x: i32) -> usize {
        return x as usize;
    }

    fn zext_u8_to_i32(x: u8) -> i32 {
        return x as i32;
    }

    fn f32_to_i32(x: f32) -> i32 {
        return x as i32;
    }

    fn i32_to_f32(x: i32) -> f32 {
        return x as f32;
    }

    fn int_to_bool(x: i32) -> bool {
        return x as bool;
    }

    fn bool_to_usize(b: bool) -> usize {
        return b as usize;
    }

    fn ptr_roundtrip(x: i32) -> i32 {
        v := x;
        p: ^i32 = &v;
        raw: ^u8 = p as ^u8;
        p2: ^i32 = raw as ^i32;
        p2^ += 7;
        return v;
    }

    fn main() {}
    """
    _, jit = jit_compile(source)

    assert jit.call("compound_deref", ctypes.c_int32) == 35
    assert jit.get_global("addr_calls", ctypes.c_int32) == 1

    assert jit.call("trunc_i32_to_u8", ctypes.c_uint8, (ctypes.c_int32, 300)) == 44
    assert (
        jit.call("sext_i32_to_usize", ctypes.c_uint64, (ctypes.c_int32, -5))
        == 0xFFFFFFFFFFFFFFFB
    )
    assert jit.call("zext_u8_to_i32", ctypes.c_int32, (ctypes.c_uint8, 250)) == 250
    assert jit.call("f32_to_i32", ctypes.c_int32, (ctypes.c_float, -3.9)) == -3
    assert pytest.approx(jit.call("i32_to_f32", ctypes.c_float, (ctypes.c_int32, -42))) == -42.0
    assert jit.call("int_to_bool", ctypes.c_uint8, (ctypes.c_int32, 0)) == 0
    assert jit.call("int_to_bool", ctypes.c_uint8, (ctypes.c_int32, -99)) == 1
    assert jit.call("bool_to_usize", ctypes.c_uint64, (ctypes.c_uint8, 1)) == 1
    assert jit.call("ptr_roundtrip", ctypes.c_int32, (ctypes.c_int32, 35)) == 42


# ======================================================================
# STEP 3: Arrays, Slices, String Literals, and Stdlib Runtime Linkage
# ======================================================================


def test_arrays_indexing_temporaries_and_len_side_effects():
    source = """
    arr_calls: i32 = 0;

    fn make_arr() -> [4]i32 {
        arr_calls += 1;
        a: [4]i32;
        a[0] = 10;
        a[1] = 20;
        a[2] = 30;
        a[3] = 40;
        return a;
    }

    fn test_array_ops() -> i32 {
        // 1. Indexing a non-addressable temporary returned by a function
        v := make_arr()[2];
        // 2. .len on a function call returning an array must still execute side effects!
        n := make_arr().len as i32;
        // 3. 2D array indexing
        mat: [2][3]i32;
        idx_u8: u8 = 1;
        idx_usize: usize = 2;
        mat[idx_u8][idx_usize] = 100;
        return v + n + mat[1][2];
    }

    fn main() {}
    """
    _, jit = jit_compile(source)
    assert jit.call("test_array_ops", ctypes.c_int32) == 134  # 30 + 4 + 100
    assert jit.get_global("arr_calls", ctypes.c_int32) == 2


def test_slices_sub_slicing_mutation_and_len():
    source = """
    fn sum_and_bump_first(s: []i32) -> i32 {
        total := 0;
        i: usize = 0;
        loop {
            if i >= s.len {
                break;
            }
            total += s[i];
            i += 1;
        }
        if s.len > 0 {
            s[0] += 1000;
        }
        return total;
    }

    fn test_slices() -> i32 {
        arr: [5]i32;
        arr[0] = 1;
        arr[1] = 2;
        arr[2] = 3;
        arr[3] = 4;
        arr[4] = 5;

        full := arr[..];
        mid_slice := full[1..4];   // [2, 3, 4], len 3
        tail := mid_slice[1..];    // [3, 4], len 2
        head := full[..2];         // [1, 2], len 2

        s1 := sum_and_bump_first(tail); // sums 3 + 4 = 7, sets arr[2] = 1003
        return s1 + head.len as i32 + arr[2];
    }

    fn main() {}
    """
    _, jit = jit_compile(source)
    # 7 + 2 + 1003 = 1012
    assert jit.call("test_slices", ctypes.c_int32) == 1012


def test_string_literals_mutable_and_lengths():
    source = """
    fn test_strings() -> usize {
        empty := "";
        s := "hello";
        // Mutating a character inside a string literal slice must not trap
        s[0] = 'H';
        if s[0] == 'H' && empty.len == 0 {
            return s.len;
        }
        return 0;
    }
    fn main() {}
    """
    mod, jit = jit_compile(source)
    ir_text = str(mod)
    # String literals must be emitted as private mutable globals (not constant)
    assert "private global [6 x i8]" in ir_text
    assert "private global [1 x i8]" in ir_text
    assert jit.call("test_strings", ctypes.c_uint64) == 5


def test_stdlib_runtime_io_linkage():
    source = """
    fn main() {
        buf: [16]u8;
        full: bool = false;
        line := getline(buf[..], &full);
        if full {
            write(line);
            write("!");
        }
        rest := read(buf[..4]);
        write(rest);
        if eof() {
            write("#");
        }
    }
    """
    reset_stdio(b"Mid\nABCD")
    mod, jit = jit_compile(source)
    ir_text = str(mod)
    assert "declare i64 @mid_getline(ptr, i64, ptr)" in ir_text
    assert "declare i64 @mid_read(ptr, i64)" in ir_text
    assert "declare void @mid_write(ptr, i64)" in ir_text
    assert "declare i8 @mid_eof()" in ir_text

    assert jit.call_main() == 0
    assert get_written_bytes() == b"Mid!ABCD#"


def test_examples_compile_and_execute():
    # 1. simple/assignment.mid
    assign_src = (EXAMPLES / "simple" / "assignment.mid").read_text()
    _, assign_jit = jit_compile(assign_src)
    assert assign_jit.call_main() == 0

    # 2. complex/stringify.mid
    stringify_src = (EXAMPLES / "complex" / "stringify.mid").read_text()
    reset_stdio()
    _, stringify_jit = jit_compile(stringify_src)
    assert stringify_jit.call_main() == 0
    assert get_written_bytes() == b"2 + 2 is: 4\n"

    # 3. complex/algorithms.mid
    algorithms_src = (EXAMPLES / "complex" / "algorithms.mid").read_text()
    reset_stdio()
    _, algorithms_jit = jit_compile(algorithms_src)
    assert algorithms_jit.call_main() == 0
    expected_output = (
        b"=== Mid Algorithms Suite ===\n"
        b"Before sort: [42, 17, -5, 99, 0, -23, 8, 31]\n"
        b"After sort:  [-23, -5, 0, 8, 17, 31, 42, 99]\n"
        b"Sorted verification: PASS\n"
        b"Binary search for 42 found at index: 6\n"
        b"Binary search for 100 result: -1\n"
        b"GCD(252, 105) = 21\n"
        b"Collatz steps for 27: 111\n"
        b"Fibonacci(10) = 55\n"
        b"Average rounded down: 21\n"
        b"Suite completed successfully!\n"
    )
    assert get_written_bytes() == expected_output

    # 4. complex/interactive.mid
    interactive_src = (EXAMPLES / "complex" / "interactive.mid").read_text()
    sim_input = b"echo Hello World\nrev 12345\nwords test phrase\ncalc 7 * 6\nquit\n"
    reset_stdio(sim_input)
    _, interactive_jit = jit_compile(interactive_src)
    assert interactive_jit.call_main() == 0
    written = get_written_bytes()
    assert b"Echo: Hello World\n" in written
    assert b"Reversed: 54321\n" in written
    assert b"Word count: 2 (characters: 11)\n" in written
    assert b"Result: 42\n" in written
    assert b"Total commands executed: 5\n" in written


def test_codegen_adversarial_audit_remediation_suite():
    """Adversarial Compiler Audit Remediation Test:
    1. Eager Pass 1 stdlib extern declarations in all modules.
    2. Zero-cost array .len on large identifiers (no load [N x T]) vs side-effecting calls.
    3. Complex nested short-circuit conditions in if/else control flow without block inversion.
    4. Unterminated non-void function AST raises AssertionError instead of emitting unreachable.
    5. ErrorNode handling raises AssertionError across all contexts.
    6. String literal isolation and in-place mutability without hardware trap.
    """
    # 1. Eager Pass 1 stdlib extern declarations in every module
    min_mod = compile_ir("fn main() {}")
    ir_min = str(min_mod)
    assert "declare i8 @mid_eof()" in ir_min
    assert "declare i64 @mid_getline(ptr, i64, ptr)" in ir_min
    assert "declare i64 @mid_read(ptr, i64)" in ir_min
    assert "declare void @mid_write(ptr, i64)" in ir_min

    # 2 & 3. Zero-cost .len on identifiers, side-effect evaluation on calls, and complex nested short-circuit if/else
    complex_src = """
    side_effects: i32 = 0;
    fn make_arr() -> [5]i32 {
        side_effects += 1;
        a: [5]i32;
        a[0] = 100;
        return a;
    }

    fn complex_cfg(a: bool, b: bool, c: bool, d: bool) -> i32 {
        large: [1000]i32;
        large_len := large.len; // Must NOT emit load [1000 x i32]

        call_len := make_arr().len; // MUST evaluate make_arr() and bump side_effects

        res := 0;
        if (a && b) || (c && d) {
            res = 10;
        } else if (!a && c) || (!b && d) {
            res = 20;
        } else {
            res = 30;
        }

        return res + (large_len as i32) + (call_len as i32);
    }

    fn test_string_isolation() -> bool {
        s1 := "alpha";
        s2 := "alpha";
        s1[0] = 'A';
        // s1 modified to "Alpha", s2 must remain "alpha"
        return s1[0] == 'A' && s2[0] == 'a';
    }

    fn main() {}
    """
    mod, jit = jit_compile(complex_src)
    ir_text = str(mod)

    # Verify no load instruction of [1000 x i32] was emitted
    assert "load [1000 x i32]" not in ir_text

    # Verify call to make_arr in make_arr().len was emitted
    assert "call [5 x i32] @make_arr()" in ir_text

    # Verify JIT execution
    # Case 1: (true && true) -> res = 10; + 1000 + 5 = 1015
    res1 = jit.call(
        "complex_cfg",
        ctypes.c_int32,
        (ctypes.c_uint8, 1),
        (ctypes.c_uint8, 1),
        (ctypes.c_uint8, 0),
        (ctypes.c_uint8, 0),
    )
    assert res1 == 1015
    assert jit.get_global("side_effects", ctypes.c_int32) == 1

    # Case 2: (!a && c) -> res = 20; + 1000 + 5 = 1025
    res2 = jit.call(
        "complex_cfg",
        ctypes.c_int32,
        (ctypes.c_uint8, 0),
        (ctypes.c_uint8, 1),
        (ctypes.c_uint8, 1),
        (ctypes.c_uint8, 0),
    )
    assert res2 == 1025
    assert jit.get_global("side_effects", ctypes.c_int32) == 2

    # Case 3: else -> res = 30; + 1000 + 5 = 1035
    res3 = jit.call(
        "complex_cfg",
        ctypes.c_int32,
        (ctypes.c_uint8, 0),
        (ctypes.c_uint8, 0),
        (ctypes.c_uint8, 0),
        (ctypes.c_uint8, 0),
    )
    assert res3 == 1035
    assert jit.get_global("side_effects", ctypes.c_int32) == 3

    # Verify string literal isolation
    assert jit.call("test_string_isolation", ctypes.c_uint8) == 1

    # 4. Invariant violation: Unterminated non-void function AST raises AssertionError
    span = Span(Pos(0, 1, 1), Pos(0, 1, 1))
    st = SymbolTable()
    bad_fn = FnDecl(
        span,
        "bad_fn",
        [],
        Type(span, [], "i32", ty=I32),
        Block(span, []),
        symbol=Symbol("bad_fn", SymbolKind.FUNCTION, return_type=I32),
    )
    bad_ast = AST(Program(span, [bad_fn]))
    with pytest.raises(AssertionError, match="reached end of body without terminator"):
        codegen(bad_ast, st)

    # 5. Invariant violation: ErrorNode in top-level and global initializers raises AssertionError
    error_node = ErrorNode(span)
    err_ast = AST(Program(span, [error_node]))
    with pytest.raises(AssertionError, match="ErrorNode"):
        codegen(err_ast, st)
