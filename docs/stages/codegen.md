# Code Generation

The code generation stage translates an annotated Abstract Syntax Tree (AST)
and a populated symbol table into LLVM Intermediate Representation (LLVM IR)
using `llvmlite`. It is the final compiler stage and executes only after the
program has passed semantic analysis with zero errors.

This document specifies the code generation contract, runtime representation,
memory model, control flow translation, and standard-library linkage for all
Mid language constructs.

## Code generator interface

The code generator receives the annotated AST and populated symbol table:

```text
codegen(ast, symbol_table) -> ir.Module
```

- `ast`: an `AST` object whose root `Program` contains decorated `TopLevelDecl`
  nodes (`ast.ty` and `ast.symbol` populated by semantic analysis).
- `symbol_table`: a `SymbolTable` containing all resolved scopes, symbols, and
  standard-library bindings.
- Output: an `ir.Module` instance from `llvmlite.ir`. Calling `str(module)`
  produces textual LLVM IR compliant with LLVM 15+ (`llvmlite >= 0.50.0`).

Semantic analysis guarantees that the input AST is structurally valid and
free of semantic errors. If an internal error or unexpected `ErrorNode` is
encountered during code generation, the compiler raises a compiler defect.

## Code generation responsibilities

The code generator performs these translations:

- LLVM module initialization with 64-bit target data layout and target triple;
- multi-pass module generation: declaring all global variables and function
  prototypes in Pass 1 before emitting bodies and initializers in Pass 2 to
  resolve forward references;
- mapping of Mid semantic types (`SemType`) to concrete `llvmlite.ir` types;
- canonical boolean handling (`i8` memory and R-Value representation, `i1` for
  branching conditions, zero-extension of comparison results);
- identity-based symbol-to-storage mapping (`dict[Symbol, ir.Value]`);
- stack allocation hoisting to the beginning of function entry blocks via a
  dedicated alloca builder for all local variables, parameters, and temporary
  array copies;
- parameter mutability via function prologue stack copies;
- global variable declaration with explicit initializers (`gv.initializer`),
  zero-initialization, compile-time literal constant globals, and source-order
  dynamic global initialization in `__mid_init_globals`;
- symbol visibility and linkage control: emitting user functions and globals
  with `internal` linkage to prevent symbol collisions with the C library;
- emission of the runtime entry point `define i32 @main()`;
- standard-library external runtime declarations with prefixed symbols (`mid_eof`,
  `mid_getline`, `mid_read`, `mid_write`) and scalar `(ptr, len)` ABI signatures
  to ensure cross-platform compatibility across Windows x64 and System V x86-64;
- statement translation (`VarDecl`, `ExprStmt`, `AssignStmt`, `IfStmt`,
  `LoopStmt`, `BreakStmt`, `ContinueStmt`, `ReturnStmt`);
- zero-initialization of uninitialized local variables on every pass of execution;
- dead-code elimination after terminating instructions in basic blocks;
- expression evaluation in L-Value (address) and R-Value (loaded value) contexts;
- temporary stack allocation for indexing non-addressable array R-Values (`f()[i]`);
- side-effect evaluation without unnecessary loads for array `.len` access (`f().len`);
- short-circuit evaluation of logical operators (`&&`, `||`) using basic blocks
  and phi nodes;
- unary negation folding of negative literals looking through parentheses in
  `UnaryExpr` (such as `-(2147483648)`);
- floating-point comparisons respecting IEEE 754 NaN semantics (`fcmp_unordered`
  for `!=`);
- string literal emission as private global arrays `[(N + 1) x i8]` with slice
  `{ i8*, i64 }` projections;
- documented undefined behaviour for division by zero and signed overflow.

## Target machine and data layout

The target machine is a 64-bit little-endian architecture:

- **Target triple**: `x86_64-pc-none-elf` (or platform host target);
- **Data layout**: `e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128`;
- **Word size**: 64 bits (`usize` and memory pointers are 64-bit integers `i64`).

Pinning a standard 64-bit data layout and decomposing aggregate slice parameters
into scalar arguments across C boundaries guarantees consistent code generation
and uniform ABI behaviour across Windows x64 and Linux/POSIX systems.

## Types and LLVM representation

Each semantic type (`SemType`) is translated recursively to an `llvmlite.ir.Type`:

| Mid Type (`SemType`) | LLVM IR Type (`ir.Type`) | Memory Representation & Invariants |
| --- | --- | --- |
| `u8` | `ir.IntType(8)` (`i8`) | 8-bit unsigned integer. |
| `bool` | `ir.IntType(8)` (`i8`) storage & R-Values; `ir.IntType(1)` (`i1`) for branches | Canonical storage and R-Value representation is `i8` (`0` for `false`, `1` for `true`). Coerced to `i1` via `to_i1` (`icmp ne i8 %val, 0`) at branch conditions (`if`, `&&`, `||`). Comparisons and logical ops produce `i1` and are immediately zero-extended back to `i8` via `to_i8` (`zext i1 %val to i8`). |
| `i32` | `ir.IntType(32)` (`i32`) | 32-bit signed integer (emitted with signed instructions `sdiv`, `srem`, `icmp_signed`). |
| `u32` | `ir.IntType(32)` (`i32`) | 32-bit unsigned integer (signless in LLVM; emitted with unsigned instructions `udiv`, `urem`, `icmp_unsigned`). |
| `f32` | `ir.FloatType()` (`float`) | 32-bit IEEE 754 single-precision float (`fadd`, `fsub`, `fmul`, `fdiv`, `fcmp_ordered`, `fcmp_unordered`). |
| `usize` | `ir.IntType(64)` (`i64`) | 64-bit unsigned integer (pointer-sized unsigned integer). |
| `void` | `ir.VoidType()` (`void`) | Return type for functions without an explicit return type. |
| `^T` | `ir.PointerType(ir_type(T))` (`T*`) | Pointer to target type `T` (resolved recursively via `sem_type.inner()`). |
| `[N]T` | `ir.ArrayType(ir_type(T), N)` (`[N x T]`) | Sequential contiguous array of `N` elements of type `T`. |
| `[]T` | `ir.LiteralStructType([ir.PointerType(ir_type(T)), ir.IntType(64)])` | Fat-pointer slice struct: `{ ptr: T*, len: i64 }`. |

### Integer signedness in LLVM

LLVM integer types (`i8`, `i32`, `i64`) are signless bit vectors. The semantic distinction between signed (`i32`) and unsigned (`u8`, `u32`, `usize`) types in Mid is maintained by the choice of LLVM instruction during code generation:

- **Division**: `sdiv` for `i32`, `udiv` for `u8`, `u32`, `usize`.
- **Remainder**: `srem` for `i32`, `urem` for `u8`, `u32`, `usize`.
- **Comparisons**: `icmp_signed` for `i32`, `icmp_unsigned` for `u8`, `u32`, `usize`.
- **Extensions**: `sext` for widening signed `i32`, `zext` for widening unsigned `u8`, `u32`, `usize`.
- **Floating conversions**: `sitofp` for `i32`, `uitofp` for `u8`, `u32`, `usize`.

### Boolean representation and conversions

To avoid mixing `i1` and `i8` throughout expression trees and memory allocations:

1. **Storage and variables**: all local `alloca`, global variables, array elements `[N]bool`, pointees `^bool`, and function parameters/returns use `ir.IntType(8)`.
2. **Expression evaluation**: all expressions producing `bool` (comparisons, literals, logical operators) yield an `i8` R-Value (`0` or `1`).
3. **Condition coercion (`to_i1`)**: when an `i8` boolean is used as an `if` condition or in short-circuit branching, it is converted to `i1` via `builder.icmp_unsigned('!=', val, ir.Constant(ir.IntType(8), 0))`.
4. **Comparison extension (`to_i8`)**: LLVM's `icmp` and `fcmp` instructions return `i1`. The generator immediately zero-extends the result: `builder.zext(val_i1, ir.IntType(8))`.

## Symbol visibility, linkage, and collision prevention

When the compiled LLVM module is linked against libc and the C runtime startup code, name clashes with libc symbols (e.g. `read`, `write`, `getline`, `exit`, `malloc`, `free`) must be strictly avoided:

1. **Standard-library runtime symbols**:
   The runtime functions implementing Mid's standard library are prefixed with `mid_`:
   - `eof` maps to external symbol `@mid_eof`
   - `getline` maps to external symbol `@mid_getline`
   - `read` maps to external symbol `@mid_read`
   - `write` maps to external symbol `@mid_write`
2. **User functions and global variables**:
   Except for `main`, all user-defined functions and global variables are emitted with LLVM `internal` linkage (`func.linkage = 'internal'`, `gv.linkage = 'internal'`). Internal linkage confines the symbols to module scope, preventing any collision with external C library functions or other compilation units at link time.
3. **Synthetic helper functions**:
   The synthetic initialization function `__mid_init_globals` is declared with `internal` linkage. Because all user functions are also internal or prefixed, no collision with external libraries occurs.
4. **The `main` function**:
   The runtime entry point `main` has external linkage (`define i32 @main()`), satisfying the standard C runtime startup requirement.

## Multi-pass compilation and forward references

In Mid, functions may call functions defined later in the source text, and global variables may reference other global variables declared later.

To resolve forward references without circular dependency issues, module code generation is structured in two passes over the root AST declarations:

### Pass 1: Declarations and prototypes

During the first pass, every top-level declaration is declared in the module without emitting implementation code:

1. **Global variables**:
   For each top-level `VarDecl`, an `ir.GlobalVariable` is created:
   ```python
   gv = ir.GlobalVariable(module, ir_type(decl.ty), name=decl.name)
   gv.linkage = 'internal'
   # Explicitly initialize to avoid emission as an external declaration:
   gv.initializer = ir.Constant(ir_type(decl.ty), None)
   env[decl.symbol] = gv
   ```
2. **Functions**:
   For each `FnDecl`, an `ir.Function` prototype is declared:
   ```python
   ret_ty = ir.IntType(32) if decl.name == "main" else ir_type(decl.ret_type)
   param_tys = [ir_type(p.ty) for p in decl.params]
   fn_ty = ir.FunctionType(ret_ty, param_tys)
   func = ir.Function(module, fn_ty, name=decl.name)
   if decl.name != "main":
       func.linkage = 'internal'
   env[decl.symbol] = func
   ```

### Pass 2: Definitions and code generation

During the second pass, bodies and initializers are emitted:

1. **Global initializers**:
   - For globals initialized with compile-time constant literals (where no preceding global in source order requires dynamic initialization), `gv.initializer` is updated directly to the constant value.
   - For globals requiring dynamic initialization, assignments are emitted in source order inside `__mid_init_globals`.
2. **Function bodies**:
   - For each `FnDecl`, the entry block, stack allocations, parameter copies, and statement bodies are emitted.

## Memory model and storage

### Symbol identification

Mid permits sibling blocks within the same function or across different functions to reuse variable names without violating the no-shadowing rule. Therefore, runtime storage addresses must not be looked up by string name. Storage is tracked using a dictionary keyed by `Symbol` object identity:

```python
env: dict[Symbol, ir.Value]
```

### Stack allocation hoisting and alloca positioning

Every local variable (`VarDecl`), function parameter, and compiler-generated temporary array copy is allocated a stack slot using `alloca`.

To guarantee that all `alloca` instructions precede any executable instructions and are cleanly promoted to SSA registers by LLVM's `mem2reg` pass:
- A dedicated `alloca_builder` is positioned at the start of the function's `entry` basic block (`alloca_builder = ir.IRBuilder(entry_bb)`).
- When a new stack slot is needed:
  ```python
  ptr = alloca_builder.alloca(ir_type, name=symbol.name)
  ```
- Executable instructions are emitted using the primary `builder`, positioned after the hoisted allocas. This prevents allocas from being placed after non-alloca instructions in `llvmlite`.

### Local variable lifecycle and zero-initialization

When execution traverses a `VarDecl`:
1. The stack pointer `ptr` is allocated via `alloca_builder`.
2. The symbol is mapped in `env`: `env[node.symbol] = ptr`.
3. If an initializer is present (`node.init is not None`):
   - Evaluate `node.init` in R-Value context -> `val`.
   - Emit `builder.store(val, ptr)`.
4. If no initializer is present (`node.init is None`):
   - Zero-initialize the stack slot: `builder.store(ir.Constant(ir_type, None), ptr)`.

> [!IMPORTANT]
> **Zero-initialization in loops**: When a local variable without an initializer is declared inside a loop body (`loop { x: i32; ... }`), the stack allocation `ptr` is hoisted to the entry block once. However, the store instruction `builder.store(zero, ptr)` is emitted at the `VarDecl` location and executes on **every iteration** of the loop, ensuring that local variables always begin each iteration zeroed as defined by their block scope.

### Parameter mutability

In Mid, function parameters are mutable variables. In LLVM IR, function arguments are immutable SSA values.

To implement mutable parameters:
1. In the function prologue, an `alloca` is created in the entry block for each parameter via `alloca_builder`.
2. The incoming argument SSA value is stored into the allocated stack slot:
   ```python
   builder.store(arg, param_ptr)
   ```
3. The symbol table environment maps the parameter `Symbol` to `param_ptr`.
4. Subsequent reads and writes to the parameter operate on `param_ptr` like any local variable.

### Global variables

Global variables are declared at module scope:

```python
gv = ir.GlobalVariable(module, ir_type, name=symbol.name)
gv.linkage = 'internal'
```

In `llvmlite`, every defined `ir.GlobalVariable` must have its `.initializer` explicitly assigned; omitting it causes `llvmlite` to emit an external declaration (`external global`).

Per `docs/stages/semantics.md`:
1. Storage for all global variables exists from program start with zero-initialized contents (`ir.Constant(ir_type, None)`).
2. Global initializers run once in source order before `main`.
3. Globals may reference other globals declared later in the source; reading an uninitialized global observes its zero-initialized state.

To satisfy these rules:
- **Compile-time constant literals**: If a global variable has a compile-time constant initializer (a primitive literal `Int`, `Float`, `Bool`, `Char`, or `UnaryExpr(NEGATE, ...)` over a literal) and no preceding global in source order has a dynamic initializer, its `gv.initializer` is set directly to the constant value:
  ```llvm
  @x = internal global i32 42
  ```
- **Dynamic initializers**: If a global variable has an initializer that is not a compile-time constant (or appears after any dynamically initialized global), its LLVM definition is explicitly zero-initialized:
  ```python
  gv.initializer = ir.Constant(ir_type, None)
  ```
  Its initialization assignment is emitted in source order inside `__mid_init_globals`.
- `__mid_init_globals` is defined with internal linkage:
  ```llvm
  define internal void @__mid_init_globals()
  ```
  It is called as the first instruction in `main()` whenever dynamic initialization is needed. If all globals are compile-time constants (or none exist), `__mid_init_globals` is omitted.
- **Uninitialized globals**: Global variables declared without an initializer (`x: type;`) have `gv.initializer = ir.Constant(ir_type, None)` and receive no runtime assignment in `__mid_init_globals`.

## Declarations and functions

### User-defined functions

Functions declared with `FnDecl` are emitted as LLVM functions:

```python
fn_ty = ir.FunctionType(ret_type, [param_type, ...])
func = ir.Function(module, fn_ty, name=decl.name)
func.linkage = 'internal'
```

- Parameter types are converted via `ir_type(param.ty)`.
- If the function has no return type (`decl.ret_type is None`), the return type is `ir.VoidType()`.
- The function body begins with an `entry` basic block:
  ```python
  entry_bb = func.append_basic_block(name="entry")
  alloca_builder = ir.IRBuilder(entry_bb)
  builder.position_at_end(entry_bb)
  ```
- After allocating stack slots and storing parameters, the statements of `decl.block` are emitted.
- If the function is void and the trailing basic block does not terminate with an explicit `return;`, the generator appends `builder.ret_void()`.
- If the function has a declared return type, `docs/stages/semantics.md` guarantees that all execution paths return. If the final basic block has no terminator instruction, the code generator raises an assertion error indicating an internal compiler invariant violation.

### The `main` function

Mid requires `main` to have signature `fn main()`. To integrate with the OS runtime startup (`crt0` / libc), `main` is emitted with external linkage and return type `i32`:

```llvm
define i32 @main() {
entry:
    call void @__mid_init_globals() ; if dynamic globals exist
    ; ... statements ...
    ret i32 0
}
```

- Any explicit `return;` inside `main` emits `ret i32 0`.
- If execution falls off the end of `main` without an explicit `return`, `ret i32 0` is emitted.

## Standard-library linkage and C ABI

The standard library functions defined in `docs/stdlib.md` are external runtime routines linked into the final executable.

### Cross-platform C ABI calling convention

Mid fat-pointer slices (`[]u8`) are represented in LLVM IR as `{ i8*, i64 }`.
Passing aggregate structs by value differs across host operating systems:
- Under System V AMD64 (Linux/macOS), a 16-byte struct is passed in two registers (`rdi`, `rsi`).
- Under Windows x64 (MSVC ABI), structs larger than 8 bytes are passed indirectly by pointer, and returned structs are passed via a hidden pointer in `rcx`.

To eliminate calling-convention disparities and guarantee consistent cross-platform linking on Windows and Linux, the runtime C interface decomposes slices into separate scalar arguments:
- Pointer base: `uint8_t *ptr` (`i8*`)
- Length: `int64_t len` (`i64`)
- Slice returns: functions that return a slice (`getline`, `read`) return the byte length read (`int64_t`). The code generator automatically wraps the base pointer and returned length into Mid's `{ i8*, i64 }` slice struct.

### LLVM IR declarations and C prototypes

During Pass 1 module initialization, the code generator eagerly declares the external runtime symbols prefixed with `mid_`:

```llvm
declare i8 @mid_eof()
declare i64 @mid_getline(i8*, i64, i8*)
declare i64 @mid_read(i8*, i64)
declare void @mid_write(i8*, i64)
```

1. **`eof`**:
   - Signature: `fn eof() -> bool`
   - LLVM: `declare i8 @mid_eof()`
   - C prototype: `uint8_t mid_eof(void);`
   - Returns: `i8` (`1` if EOF reached on stdin, `0` otherwise).
2. **`getline`**:
   - Signature: `fn getline(buff: []u8, read_full_line: ^bool) -> []u8`
   - LLVM: `declare i64 @mid_getline(i8*, i64, i8*)`
   - C prototype: `int64_t mid_getline(uint8_t *ptr, int64_t len, uint8_t *read_full_line);`
   - Call generation: extracts `ptr` and `len` from `buff`, passes `read_full_line`, calls `@mid_getline`, and packages `{ ptr, ret_len }` into the returned slice struct.
3. **`read`**:
   - Signature: `fn read(buff: []u8) -> []u8`
   - LLVM: `declare i64 @mid_read(i8*, i64)`
   - C prototype: `int64_t mid_read(uint8_t *ptr, int64_t len);`
   - Call generation: extracts `ptr` and `len` from `buff`, calls `@mid_read`, and packages `{ ptr, ret_len }` into the returned slice struct.
4. **`write`**:
   - Signature: `fn write(buff: []u8)`
   - LLVM: `declare void @mid_write(i8*, i64)`
   - C prototype: `void mid_write(const uint8_t *ptr, int64_t len);`
   - Call generation: extracts `ptr` and `len` from `buff` and calls `@mid_write(ptr, len)`.

## Statements and control flow

### Variable declarations (`VarDecl`)

- Stack slot is hoisted to the function `entry` block via `alloca_builder`.
- Maps `node.symbol` to the allocated pointer in `env`.
- If `node.init` is present: evaluates `node.init` in R-Value context and emits `builder.store(val, ptr)`.
- If `node.init` is absent: emits `builder.store(ir.Constant(ir_type, None), ptr)`.

### Expression statements (`ExprStmt`)

- Evaluates `node.expr` in R-Value context for its side effects.
- If the expression produces a non-void value, the value is ignored.

### Assignment statements (`AssignStmt`)

- **Direct assignment (`=`)**:
  1. Evaluate `target` in L-Value context to obtain pointer `target_ptr`.
  2. Evaluate `val` in R-Value context to obtain value `rhs_val`.
  3. Emit `builder.store(rhs_val, target_ptr)`.
- **Compound assignment (`+=`, `-=`, `*=`, `/=`, `%=`)**:
  1. Evaluate `target` in L-Value context **once** to obtain pointer `target_ptr`.
  2. Load current value: `curr_val = builder.load(target_ptr)`.
  3. Evaluate `val` in R-Value context to obtain value `rhs_val`.
  4. Compute the binary arithmetic operation corresponding to the assignment operator (using signed instructions for `i32`, unsigned for unsigned integers, and float instructions for `f32`).
  5. Emit `builder.store(result_val, target_ptr)`.

### Conditional branching (`IfStmt`)

An `IfStmt` consists of branches (`branches = [Branch(cond, body), ...]`) and an optional `else_body`.

Basic block allocation avoids redundant trampoline blocks and empty blocks:

1. Create a merge block without immediately appending it to the function:
   ```python
   merge_bb = ir.Block(builder.function, "if.merge")
   merge_reachable = False
   ```
2. For each branch `i` from `0` to `len(branches) - 1`:
   - Evaluate `branch.cond` in R-Value context -> `cond_val` (evaluated before creating `then_bb` to ensure any sub-blocks created by short-circuit operators precede `then_bb` in block order).
   - Coerce `cond_val` to `i1`: `cond_i1 = to_i1(cond_val)`.
   - Append `then_bb = builder.append_basic_block(f"if.then.{i}")`.
   - If branch is the last branch and no `else_body` exists:
     - `next_bb = merge_bb` (reuses merge block directly, eliminating redundant jumps).
   - Else:
     - `next_bb = builder.append_basic_block(f"if.next.{i}")`.
   - Emit conditional branch: `builder.cbranch(cond_i1, then_bb, next_bb)`.
   - Position builder at `then_bb` and emit statements in `branch.body`.
   - If `not builder.block.is_terminated`:
     - Emit branch: `builder.branch(merge_bb)`.
     - `merge_reachable = True`
   - If `next_bb != merge_bb`:
     - Position builder at `next_bb`.
3. Handle `else_body` (if present):
   - Position builder at the final `next_bb`.
   - Emit statements of `else_body`.
   - If `not builder.block.is_terminated`:
     - Emit branch: `builder.branch(merge_bb)`.
     - `merge_reachable = True`
4. If no `else_body` existed:
   - The final `next_bb` is `merge_bb`, so fallthrough path is naturally reachable: `merge_reachable = True`.
5. Positioning after the `if` statement:
   - If `merge_reachable` is `True`:
     - If `merge_bb` was not yet appended: `builder.function.basic_blocks.append(merge_bb)`.
     - Position the builder at `merge_bb`: `builder.position_at_end(merge_bb)`.
   - If `merge_reachable` is `False` (all branches terminated with `return` or `break`):
     - Discard `merge_bb` (never appended). The builder remains terminated for dead-code elimination.

### Loops (`LoopStmt`)

Mid provides unbounded `loop { ... }` statements.

To avoid leaving empty, unreferenced basic blocks when loops have no reachable `break` statements:

1. Create basic blocks:
   - Append header block: `loop_head_bb = builder.append_basic_block("loop.head")`.
   - Create exit block without appending it: `loop_exit_bb = ir.Block(builder.function, "loop.exit")`.
   - Track exit reachability: `loop_ctx = {"head": loop_head_bb, "exit": loop_exit_bb, "exit_reachable": False}`.
2. Emit branch into loop header: `builder.branch(loop_head_bb)`.
3. Push `loop_ctx` onto loop context stack:
   ```python
   loop_stack.append(loop_ctx)
   ```
4. Position builder at `loop_head_bb` and emit statements of `node.body`.
5. If `not builder.block.is_terminated`, emit back-edge: `builder.branch(loop_head_bb)`.
6. Pop loop context: `ctx = loop_stack.pop()`.
7. Loop exit positioning:
   - If `ctx["exit_reachable"]` is `True` (at least one `break` targeted this loop):
     - Append `ctx["exit"]` to function: `builder.function.basic_blocks.append(ctx["exit"])`.
     - Position builder at `ctx["exit"]`: `builder.position_at_end(ctx["exit"])`.
   - If `ctx["exit_reachable"]` is `False` (infinite loop with no reachable `break`):
     - Discard `ctx["exit"]` without appending it.
     - The builder remains terminated, skipping any dead code following the loop.

### Break statements (`BreakStmt`)

- Retrieve top loop context: `ctx = loop_stack[-1]`.
- Mark exit reachable: `ctx["exit_reachable"] = True`.
- Emit jump to exit block: `builder.branch(ctx["exit"])`.

### Continue statements (`ContinueStmt`)

- Retrieve top loop context: `ctx = loop_stack[-1]`.
- Emit jump to loop header block: `builder.branch(ctx["head"])`.

### Return statements (`ReturnStmt`)

- **Inside `main`**:
  - `builder.ret(ir.Constant(ir.IntType(32), 0))`.
- **Inside void functions (`ret_type is None`)**:
  - `builder.ret_void()`.
- **Inside value-returning functions**:
  - Evaluate `node.value` in R-Value context -> `ret_val`.
  - If return type is `bool`, ensure `ret_val` is `i8`.
  - Emit `builder.ret(ret_val)`.

### Dead-code handling

`docs/stages/semantics.md` does not reject unreachable statements after `return`, `break`, or `continue`. However, LLVM IR requires each basic block to contain at most one terminator instruction.

During block traversal, as soon as `builder.block.is_terminated` is `True`, code generation for all subsequent statements in that block is skipped.

## Expressions and evaluation contexts

Every expression is evaluated in one of two contexts:
- **L-Value context**: returns an `ir.Value` representing the memory pointer (`T*`) to the target storage. Only addressable expressions may be evaluated in L-Value context.
- **R-Value context**: returns an `ir.Value` representing the value (`T`) of the expression.

Addressable expressions are:
- `Identifier` (local variables, parameters, globals);
- `DereferenceExpr` (`ptr^`);
- `IndexExpr` when the indexed base target is addressable.

### Literals

- `Int`: `ir.Constant(ir_type(node.ty), node.val)`.
- `Float`: `ir.Constant(ir.FloatType(), float(node.val))`.
- `Bool`: `ir.Constant(ir.IntType(8), 1 if node.val else 0)`.
- `Char`: `ir.Constant(ir.IntType(8), node.val)`.
- `String`:
  - Mid strings are of type `[]u8`.
  - The byte content (length `N`) is emitted as a private global array `[(N + 1) x i8]`:
    ```llvm
    @.str.0 = private global [N + 1 x i8] c"...\00"
    ```
  - Emitting string literals as private mutable globals (`global` rather than `constant`) ensures that write operations on slice elements (`s[0] = 'x'` or `read(s)`) do not trigger hardware memory protection traps, adhering to Mid's design where constness is excluded (`docs/features.md:20`).
  - For empty strings (`N == 0`), an array `[1 x i8] c"\00"` is emitted.
  - The expression evaluates to a slice struct `{ i8*, i64 }`:
    - `ptr`: GEP to first element `[i64 0, i64 0]` of the global array;
    - `len`: `ir.Constant(ir.IntType(64), N)`.
    - Constructed via `insert_value` or `ir.Constant.literal_struct([ptr, len])`.

### Identifiers

- **L-Value context**: Look up `node.symbol` in `env` and return the storage pointer `ptr`.
- **R-Value context**: Obtain `ptr` from L-Value context and load the value: `builder.load(ptr)`.

### Arithmetic and comparison binary operators

- **Addition, Subtraction, Multiplication**:
  - Signed and unsigned integers (`u8`, `i32`, `u32`, `usize`): `builder.add(l, r)`, `builder.sub(l, r)`, `builder.mul(l, r)`.
  - Floating point (`f32`): `builder.fadd(l, r)`, `builder.fsub(l, r)`, `builder.fmul(l, r)`.
- **Division**:
  - Signed integer (`i32`): `builder.sdiv(l, r)`.
  - Unsigned integers (`u8`, `u32`, `usize`): `builder.udiv(l, r)`.
  - Floating point (`f32`): `builder.fdiv(l, r)`.
- **Modulo**:
  - Signed integer (`i32`): `builder.srem(l, r)`.
  - Unsigned integers (`u8`, `u32`, `usize`): `builder.urem(l, r)`.
- **Comparisons (`==`, `!=`, `<`, `<=`, `>`, `>=`)**:
  - Signed integer (`i32`): `builder.icmp_signed(op_str, l, r)`.
  - Unsigned integer / boolean (`u8`, `u32`, `usize`, `bool`): `builder.icmp_unsigned(op_str, l, r)`.
  - Floating point (`f32`):
    - **Inequality (`!=`)**: emitted using `builder.fcmp_unordered('!=', l, r)` (LLVM `une`). This guarantees that `NaN != NaN` and any comparison involving `NaN` evaluates to `true` (`1`), adhering to IEEE 754 and C semantics.
    - **Other operators (`==`, `<`, `<=`, `>`, `>=`)**: emitted using `builder.fcmp_ordered(op_str, l, r)` (`oeq`, `olt`, `ole`, `ogt`, `oge`), returning `false` (`0`) if either operand is `NaN`.
  - Comparison instructions produce an `i1`. The code generator immediately zero-extends the result to `i8`:
    ```python
    cmp_i8 = builder.zext(cmp_i1, ir.IntType(8))
    ```

### Short-circuit logical operators (`&&`, `||`)

Logical `&&` and `||` evaluate their operands using short-circuit control flow:

- **Logical AND (`A && B`)**:
  1. Evaluate `A` in R-Value context -> `a_val`.
  2. Coerce `a_val` to `i1`: `a_i1 = to_i1(a_val)`.
  3. Record `lhs_block = builder.block`.
  4. Create `rhs_bb = builder.append_basic_block("and.rhs")` and `merge_bb = builder.append_basic_block("and.merge")`.
  5. `builder.cbranch(a_i1, rhs_bb, merge_bb)`.
  6. In `rhs_bb`:
     - Evaluate `B` in R-Value context -> `b_val`.
     - Coerce `b_val` to `i1`: `b_i1 = to_i1(b_val)`.
     - Record `rhs_block = builder.block`.
     - `builder.branch(merge_bb)`.
  7. In `merge_bb`:
     - `phi = builder.phi(ir.IntType(1), name="and.res")`.
     - `phi.add_incoming(ir.Constant(ir.IntType(1), 0), lhs_block)`.
     - `phi.add_incoming(b_i1, rhs_block)`.
     - Return `to_i8(phi)`.

- **Logical OR (`A || B`)**:
  1. Evaluate `A` in R-Value context -> `a_val`.
  2. Coerce `a_val` to `i1`: `a_i1 = to_i1(a_val)`.
  3. Record `lhs_block = builder.block`.
  4. Create `rhs_bb = builder.append_basic_block("or.rhs")` and `merge_bb = builder.append_basic_block("or.merge")`.
  5. `builder.cbranch(a_i1, merge_bb, rhs_bb)`.
  6. In `rhs_bb`:
     - Evaluate `B` in R-Value context -> `b_val`.
     - Coerce `b_val` to `i1`: `b_i1 = to_i1(b_val)`.
     - Record `rhs_block = builder.block`.
     - `builder.branch(merge_bb)`.
  7. In `merge_bb`:
     - `phi = builder.phi(ir.IntType(1), name="or.res")`.
     - `phi.add_incoming(ir.Constant(ir.IntType(1), 1), lhs_block)`.
     - `phi.add_incoming(b_i1, rhs_block)`.
     - Return `to_i8(phi)`.

### Unary operators

- **Logical NOT (`!`)**:
  - Operand is `bool` (`i8`).
  - Emitted as: `builder.xor(val_i8, ir.Constant(ir.IntType(8), 1))`.
- **Negation (`-`)**:
  - Handled in `UnaryExpr`:
    - While parentheses are unwrapped by the parser during AST construction and have no dedicated AST node, the generator defensives against synthetic/wrapper parenthesis nodes (`ParenExpr`).
    - If the unwrapped operand is a numeric literal (`Int` or `Float`), it is folded into a single negative constant:
      ```python
      if isinstance(inner, ast.Int):
          return ir.Constant(ir_type(node.ty), -inner.val)
      if isinstance(inner, ast.Float):
          return ir.Constant(ir.FloatType(), -float(inner.val))
      ```
      This folding ensures that minimum negative values such as `-(2147483648)` or `-((2147483648))` are emitted directly as the valid signed constant `-2147483648` without intermediate positive overflow.
    - Otherwise, evaluate operand in R-Value context:
      - Integer (`i32`): `builder.neg(val)`.
      - Floating point (`f32`): `builder.fneg(val)`.
- **Address-of (`&`)**:
  - Operand must be addressable.
  - Evaluates operand in L-Value context and returns the pointer directly.
- **Dereference (`^`)**:
  - Operand must have pointer type `^T`.
  - Evaluate operand in R-Value context to obtain pointer `ptr`.
  - In L-Value context: return `ptr`.
  - In R-Value context: return `builder.load(ptr)`.

### Explicit type casts (`as`)

Casting follows the Mid cast matrix in `docs/stages/semantics.md`:

| Source Type | Target Type | LLVM IR Instruction |
| --- | --- | --- |
| `T` | `T` (identity) | No-op (returns original value unchanged). |
| `i32` | `u32` | No-op (same LLVM bit-width `i32`). |
| `u32` | `i32` | No-op (same LLVM bit-width `i32`). |
| Integer | Narrower integer | `builder.trunc(val, target_ty)` |
| `i32` | Wider integer (`usize`) | `builder.sext(val, target_ty)` (sign extension) |
| Unsigned int | Wider integer | `builder.zext(val, target_ty)` (zero extension) |
| `i32` | `f32` | `builder.sitofp(val, ir.FloatType())` |
| Unsigned int | `f32` | `builder.uitofp(val, ir.FloatType())` |
| `f32` | `i32` | `builder.fptosi(val, target_ty)` (truncate toward zero) |
| `f32` | Unsigned int | `builder.fptoui(val, target_ty)` (truncate toward zero) |
| Integer | `bool` | `builder.zext(builder.icmp_unsigned('!=', val, Constant(0)), ir.IntType(8))` |
| `bool` | `u8` | No-op (both represented as `i8`). |
| `bool` | `i32`, `u32`, `usize` | `builder.zext(val, target_ty)` |
| `^T` | `^u8` | `builder.bitcast(val, target_ty)` |
| `^u8` | `^T` | `builder.bitcast(val, target_ty)` |

### Postfix operations

#### Function calls (`CallExpr`)

- The callee is looked up to obtain the `ir.Function` reference.
- Arguments are evaluated in R-Value context in source order.
- Boolean arguments are verified to be `i8`.
- Fat-pointer slices (`[]T`) are passed by value as `{ T*, i64 }` structs to user functions.
- The call instruction is emitted: `builder.call(fn_val, arg_vals)`.

#### Indexing (`IndexExpr`)

The target is an array `[N]T` or a slice `[]T`. The index may be any integer type (`u8`, `i32`, `u32`, `usize`).

1. **Index coercion to `i64` (`to_i64`)**:
   - `i32`: `builder.sext(idx, ir.IntType(64))`
   - `u8`, `u32`: `builder.zext(idx, ir.IntType(64))`
   - `usize`: unchanged (`i64`)
2. **Array target (`[N]T`)**:
   - **Addressable targets** (identifiers, dereferences, indexed addressable structures):
     - Evaluate target in L-Value context to obtain array pointer `arr_ptr` (`[N x T]*`).
   - **Non-addressable targets** (temporary array R-Values, e.g. function call returns `f()[i]`):
     - Evaluate target in R-Value context -> `arr_val` (`[N x T]`).
     - Allocate a temporary stack slot via `alloca_builder`: `temp_ptr = alloca_builder.alloca(ir_type(target.ty))`.
     - Store the temporary array: `builder.store(arr_val, temp_ptr)`.
     - Use `temp_ptr` as `arr_ptr`.
   - Calculate element pointer: `elem_ptr = builder.gep(arr_ptr, [ir.Constant(ir.IntType(64), 0), idx_i64])`.
   - In L-Value context: return `elem_ptr`.
   - In R-Value context: return `builder.load(elem_ptr)`.
3. **Slice target (`[]T`)**:
   - Evaluate target in R-Value context to obtain slice struct `{ T*, i64 }`.
   - Extract base pointer: `base_ptr = builder.extract_value(slice_val, 0)`.
   - Calculate element pointer: `elem_ptr = builder.gep(base_ptr, [idx_i64])`.
   - In L-Value context: return `elem_ptr`.
   - In R-Value context: return `builder.load(elem_ptr)`.

#### Slicing ranges (`SliceExpr`)

The target is an array `[N]T` or slice `[]T`. Range bounds `low` and `high` are optional.

1. **Bound normalization**:
   - `low`: if present, coerced to `i64` via `to_i64(low)`; if omitted, `ir.Constant(ir.IntType(64), 0)`.
   - `high`:
     - if present, coerced to `i64` via `to_i64(high)`;
     - if omitted on array `[N]T`, compile-time constant `ir.Constant(ir.IntType(64), N)`;
     - if omitted on slice `[]T`, `builder.extract_value(slice_val, 1)`.
2. **Base pointer calculation**:
   - Array target: evaluate in L-Value context (or hoist temporary stack slot if non-addressable) -> `arr_ptr` (`[N x T]*`).
     `new_ptr = builder.gep(arr_ptr, [ir.Constant(ir.IntType(64), 0), low_i64])`.
   - Slice target: evaluate in R-Value context -> `slice_val` (`{ T*, i64 }`).
     `base_ptr = builder.extract_value(slice_val, 0)`.
     `new_ptr = builder.gep(base_ptr, [low_i64])`.
3. **Slice length calculation**:
   - `new_len = builder.sub(high_i64, low_i64)`.
4. **Result struct creation**:
   - Construct `{ T*, i64 }`:
     ```python
     sl = ir.Constant(slice_ty, ir.Undefined)
     sl = builder.insert_value(sl, new_ptr, 0)
     sl = builder.insert_value(sl, new_len, 1)
     ```
   - Returns `sl`.

#### Length access (`FieldExpr`)

The only valid field in Mid is `.len` (`ast.FieldExpr(target, "len")`).

- **Array target (`[N]T`)**:
  - The array size `N` is known at compile time.
  - To preserve program semantics without unnecessary loads, `target` is evaluated for side effects only if it contains potential side-effect expressions (such as `CallExpr`), discarding the result; for identifier variables, no load is emitted. The compile-time constant `ir.Constant(ir.IntType(64), N)` is returned.
- **Slice target (`[]T`)**:
  - Evaluate `target` in R-Value context to obtain slice struct `{ T*, i64 }`.
  - Extract and return length field: `builder.extract_value(slice_val, 1)`.

## Undefined behaviour

The following operations are not rejected by semantic analysis but constitute undefined behaviour at runtime in LLVM:

1. **Integer division and modulo by zero**:
   Dividing or taking the remainder by zero (`sdiv`, `udiv`, `srem`, `urem` with RHS equal to `0`) is undefined in LLVM and generates a hardware exception or trap on standard architectures.
2. **Signed integer overflow in division**:
   Executing `sdiv` or `srem` on `i32` with LHS equal to `-2147483648` (`INT_MIN`) and RHS equal to `-1` causes signed integer overflow, which is undefined behaviour in LLVM and results in an arithmetic trap on x86-64.
3. **Out-of-range floating-point to integer casts**:
   Using `as` to convert `f32` to an integer via `fptosi` or `fptoui` when the float value is `NaN`, infinite, or outside the range of representable integer values is undefined behaviour in LLVM and Mid semantics.
4. **Out-of-bounds indexing and slicing**:
   Accessing array or slice elements outside the allocated range `[0, len)` without runtime bounds checking is undefined behaviour and will read or corrupt adjacent memory.

## Error handling and invariants

The code generation stage assumes a semantically verified AST:

- **Preconditions**: `errors` list returned by the semantic analyzer must be empty.
- **`ErrorNode` handling**: The parser and semantic analyzer may construct `ErrorNode` nodes during error recovery. If an `ErrorNode` is visited during code generation, the code generator raises an assertion error indicating an internal compiler invariant violation.
- **Unreachable code**: Instructions must not be added to already terminated basic blocks. Traversal within a block halts once `builder.block.is_terminated` is `True`.
