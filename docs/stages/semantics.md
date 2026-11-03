# Semantic Analysis

Semantic analysis consumes the parser's AST and verifies that the program has
meaning according to the Mid language rules. It resolves names, checks scopes,
validates types and operations, verifies control-flow context, and annotates
the AST with the information required by later stages.

The analyzer always returns a triplet:

```text
analyzer(ast) -> (annotated_ast, symbol_table, errors)
```

`errors` is a list of structured `AnalyzerError` objects. The analyzer may
return an AST containing error markers and a partially populated symbol table;
the code generator is the first stage that requires the error list to be empty.
The analyzer must not change the program's source structure. It may attach
semantic information to AST nodes and must populate the symbol table described
below.

## Semantic responsibilities

The analyzer performs these checks:

- declaration and name resolution;
- scope and visibility rules;
- duplicate declarations and forbidden shadowing;
- declaration type validation;
- type inference for `:=` declarations;
- typing of numeric literals from their context;
- exact type compatibility for assignments, arguments, and returns;
- explicit cast validity;
- operator operand and result types;
- function-call arity and argument types;
- array, slice, `.len`, pointer, and dereference operations;
- `break` and `continue` loop context;
- function return rules;
- presence and signature of `main`;
- reads of undeclared names;
- use of names before their declaration where required;
- attempts to reassign protected standard-library symbols.

The analyzer returns all recoverable semantic errors as structured
`AnalyzerError` objects in the `errors` list. It does not print diagnostics
while analyzing. The compiler driver aggregates errors from all front-end
stages and prints them after the front-end pass. Diagnostics must never be
printed to standard output.

## Types

The built-in primitive types are:

| Type | Meaning |
| --- | --- |
| `u8` | 8-bit unsigned integer |
| `bool` | Boolean value represented by `0` or `1` |
| `i32` | 32-bit signed integer |
| `u32` | 32-bit unsigned integer |
| `f32` | 32-bit single-precision floating point |
| `usize` | Word-sized unsigned integer (64 bits) |

The **integer types** are `u8`, `i32`, `u32`, and `usize`. The **numeric
types** are the integer types plus `f32`. `bool` is not a numeric type.

Qualified types are formed by applying the qualifiers parsed in source order:

| Syntax | Meaning |
| --- | --- |
| `^T` | Pointer to `T` |
| `[N]T` | Fixed-size array of `N` elements of `T` |
| `[]T` | Slice of `T` |

The analyzer resolves the final type-name identifier and rejects unknown type
names. An array size `N` must be greater than zero. Qualifier order is
preserved; semantically distinct qualified types are not interchangeable
merely because they contain the same components.

Two types are equal when they have the same type name and the same list of
qualifiers (including array sizes). Source spans are not part of a type's
identity, so implementations must not compare `Type` nodes with the dataclass
`==` operator directly.

The analyzer uses the AST `Type` nodes as the primary type representation. If
normalization, canonical identity, or inferred type information cannot be
represented by the AST node, the implementation may introduce a separate
semantic type object and attach it to the annotated AST.

There are no implicit conversions between typed values. Assignment,
initialization, function arguments, and return values require exact type
compatibility unless an explicit cast is present. The only exception is
numeric literals, described in [Numeric literals](#numeric-literals).
Arrays never convert to slices automatically: a slice of an array must be
written explicitly with a range expression such as `arr[..]`.

## Declarations and inference

### Variables

The parser accepts these declaration forms:

```text
name := expression;
name: type;
name: type = expression;
```

`:=` infers the variable's type from the initializer. A declaration using `:`
must provide an explicit type. Its initializer is optional; when present, its
type must exactly match the declared type (a numeric literal initializer takes
the declared type, see [Numeric literals](#numeric-literals)).

Variables are mutable, including global variables. A local variable becomes
visible only after its declaration has been semantically checked and inserted
into the current scope. A variable cannot be read before its declaration.

This phase checks declaration visibility, not definite initialization. A
declared variable may therefore be read even if its declaration did not include
an initializer; runtime initialization behavior is defined by later stages.

### Global variables

Global variables behave like local variable declarations, except for when they
become visible:

1. Every global variable is predeclared before any initializer is analyzed. Its
   storage exists from program start with an unspecified value (the code
   generator may zero-initialize it).
2. Global initializers are not required to be constant expressions. They run
   once, in source order, before `main` is called.
3. Because globals are predeclared, functions and global initializers may
   reference any global variable, including ones declared later in the source.
   Reading a later global from an initializer observes its value before its
   own initializer has run.
4. A global declared with `:=` has no known type until its initializer has been
   analyzed. Referencing it from a global initializer that appears **before**
   it in the source is therefore an error (`AnalyzerError(1)`). Globals with an
   explicit type (`name: type ...`) have no such restriction.

Function bodies are analyzed after every global initializer, so every global
is fully typed inside function bodies.

### Functions

Functions have a unique name in the global scope. Defining the same function
name more than once is a redeclaration error, including collisions with a
standard-library function.

Function parameters are symbols in the function scope. Parameter names must be
unique within that function and cannot shadow any visible name under the
language's no-shadowing rule.

If a function has no `-> type`, its `FnDecl.ret_type` is `None` and it has void
return behavior. A void function may use `return;` but may not return an
expression. A function with a declared return type must return an expression
in every `return` statement, and its type must exactly match that return type.

### Return paths

A function with a declared return type must not be able to reach the end of
its body. The analyzer decides this with the following conservative rules. A
statement **always returns** when it is:

- a `return` statement;
- an `if` statement that has an `else` block, where every branch body and the
  `else` block always return;
- a `loop` statement whose body contains no `break` that exits that loop
  (`break` statements inside nested loops do not count), since such a loop
  never completes normally.

A block always returns when any of its statements always returns. If the body
of a non-void function does not always return, the analyzer reports
`AnalyzerError(10)`. A void function may complete without an explicit return.

### The `main` function

Every program must define exactly one `main` function with the signature:

```text
fn main()
```

`main` takes no parameters and has no return type; the program always returns
`0` to the operating system. A missing `main`, or a `main` with parameters or a
return type, is reported as `AnalyzerError(11)`.

## Scope and visibility

The symbol table contains:

1. one global scope;
2. one function scope for each function body; and
3. one nested scope for each block.

Nested scopes are created for blocks in functions, condition branches, loop
bodies, and other AST `Block` nodes. A scope searches its own bindings first,
then its parent scopes.

Variable shadowing is forbidden. A declaration is invalid if its name already
exists in the current scope or any visible enclosing scope. This applies to
variables, parameters, functions, built-in functions, and type names, which all
share one namespace. Sibling blocks are not visible from each other, so two
sibling blocks may declare the same name.

Global declarations are processed in these steps:

1. built-in types and standard-library functions are preloaded;
2. all global functions and variables are predeclared so global references can
   resolve consistently;
3. global variable initializers are analyzed in source order; and
4. function bodies are analyzed.

Local declarations are processed in source order and become visible only after
their declaration and initializer have been checked. Function declarations are
visible globally before function bodies are analyzed.

The analyzer must reject references to undeclared names and references that
violate the visibility rules.

## Symbol table

`SymbolTable` is a hierarchy of scopes. Each scope maps a name to one symbol
entry and has an optional parent scope.

The required conceptual interface is:

```text
SymbolTable
  global_scope: Scope
  current_scope: Scope

Scope
  parent: Scope | None
  symbols: map[str, Symbol]

Symbol
  name: str
  kind: variable | function | parameter | builtin_function | type
  type: Type | None
  parameters: list[Type] | None
  return_type: Type | None
  span: Span
  mutable: bool
```

The implementation may use a different Python representation, but it must
provide equivalent behavior:

- define a symbol in the current scope;
- reject duplicate names and forbidden shadowing;
- look up a name in the current scope and its parents;
- enter and leave nested scopes;
- distinguish variables, parameters, functions, built-in functions, and types;
- expose function parameter and return types for call checking;
- expose mutability for assignment checking.

User-defined variables and parameters are mutable. User-defined function
symbols are not assignable and cannot be redefined. Standard-library functions
are global, immutable symbols. If standard-library variables are added later,
they are also protected from user reassignment, although library internals may
mutate their backing state.

## Standard-library symbols

The analyzer preloads the built-in type names (`u8`, `bool`, `i32`, `u32`,
`f32`, `usize`) and the standard-library functions into the global scope:

```text
eof() -> bool
getline([]u8, ^bool) -> []u8
read([]u8) -> []u8
write([]u8) -> void
```

These symbols participate in duplicate-name checks and function-call checking.
They cannot be redeclared or assigned by user code.

## Expression typing

The analyzer recursively computes the type of every expression. The concrete
storage mechanism for inferred types, resolved symbols, and other annotations
is an implementation decision: annotations may be added to AST nodes, stored
in a side table, or represented by wrapper objects. The implementation must
preserve equivalent information for later stages.

Expressions are checked with an optional **expected type** coming from their
context. The expected type is:

- the declared type, for the initializer of `name: type = expression`;
- the target's type, for the right side of an assignment or compound
  assignment;
- the parameter type, for a call argument;
- the function's return type, for a `return` expression;
- the type of the other operand, for an operand of a binary operator;
- none, everywhere else (for example `name := expression`, cast operands,
  index and range bounds, and expression statements).

### Literals and identifiers

| Expression | Type |
| --- | --- |
| character literal | `u8` |
| boolean literal | `bool` |
| integer literal | expected integer type, otherwise `i32` |
| float literal | `f32` |
| string literal | `[]u8` |
| identifier | type of its resolved symbol |

An identifier expression resolves to a variable or parameter symbol. Using a
function name as a value is invalid unless the language later defines
first-class function values; function names may only appear as the callee of
a call.

### Numeric literals

Numeric literals have no fixed width until their context gives them one:

- An integer literal may take the type `u8`, `i32`, `u32`, or `usize`. When
  the expected type is one of these, the literal takes that type. Otherwise it
  defaults to `i32`.
- A float literal always has type `f32`.
- An integer literal never becomes `f32` or `bool`, and a float literal never
  becomes an integer type. For example, `x: f32 = 1;` is a type mismatch and
  must be written `x: f32 = 1.0;`.
- The literal's value must fit its final type, otherwise the analyzer reports
  `AnalyzerError(4)`:

  | Type | Range |
  | --- | --- |
  | `u8` | `0 ..= 255` |
  | `i32` | `-2147483648 ..= 2147483647` |
  | `u32` | `0 ..= 4294967295` |
  | `usize` | `0 ..= 18446744073709551615` |

- A unary `-` applied directly to an integer literal (optionally inside
  parentheses) forms a single negative literal. `-2147483648` is therefore a
  valid `i32`, while `x: u32 = -1;` is an error.
- In a binary operation, a literal operand takes the type of the other
  operand. If both operands are literals, both take the expected type of the
  whole expression, or the default type when there is none.

This rule applies only to literals. Values of different widths are never
converted implicitly: if `a: u8` and `b: i32`, then `a = b;` and `a + b` are
errors and require an explicit cast.

### Operators

The operator rules are:

- `!` requires `bool` and produces `bool`;
- unary `-` requires `i32` or `f32` and preserves that type (negating an
  unsigned type is an error, except for the negative-literal case above);
- unary `&` requires an addressable expression and produces a pointer to its
  type;
- `^` requires a pointer and produces its pointee type;
- `&&` and `||` require two `bool` operands and produce `bool`;
- `+`, `-`, `*`, and `/` require two operands of the same numeric type and
  produce that type;
- `%` requires two operands of the same integer type and produces that type;
- `<`, `>`, `<=`, and `>=` require two operands of the same numeric type and
  produce `bool`;
- `==` and `!=` require two operands of the same numeric type or two `bool`
  operands, and produce `bool`.

Pointer arithmetic, array arithmetic, and aggregate arithmetic are invalid.
Pointer, array, and slice equality and ordering are invalid.

Addressable expressions are variables and parameters, index expressions whose
target is an addressable array or a slice, and dereference expressions.
Literals, calls, casts, `.len`, and function names are not addressable.

### Assignment

The left side of an assignment must be assignable and the right side must have
the exact same type. Assignable expressions are the addressable expressions
listed above. Function symbols, standard-library symbols, and `.len` are not
assignable.

Compound assignments (`+=`, `-=`, `*=`, `/=`, `%=`) require the same operand
rules as the corresponding binary operator and update the target in place.

### Calls

The callee must be an identifier that resolves to a function or
standard-library function symbol. The number of arguments must equal the
number of parameters, and each argument must have the exact corresponding
parameter type. A call expression has the function's return type; calling a
void function is valid only as an expression statement, and using its result
as a value is an error.

### Casts

Explicit casts use the `as` operator. An integer literal used as a cast
operand has no expected type and therefore defaults to `i32` (so
`300 as u8` evaluates to `44`).

Primitive casts follow this table (rows are the source type, columns are the
target type):

| from \ to | `u8` | `i32` | `u32` | `usize` | `f32` | `bool` |
| --- | --- | --- | --- | --- | --- | --- |
| `u8` | yes | yes | yes | yes | yes | yes |
| `i32` | yes | yes | yes | yes | yes | yes |
| `u32` | yes | yes | yes | yes | yes | yes |
| `usize` | yes | yes | yes | yes | yes | yes |
| `f32` | yes | yes | yes | yes | yes | no |
| `bool` | yes | yes | yes | yes | no | yes |

Conversion semantics:

- **integer to narrower integer**: truncates to the low bits
  (`300 as u8` is `44`);
- **integer to wider integer**: zero-extends from an unsigned source and
  sign-extends from `i32`;
- **between `i32` and `u32`**: keeps the bit pattern (`-1 as u32` is
  `4294967295`);
- **integer to `f32`**: converts to the nearest `f32`, treating the source as
  signed only when it is `i32`;
- **`f32` to integer**: truncates toward zero; values outside the target range
  produce undefined behavior;
- **`bool` to integer**: produces `0` or `1`;
- **integer to `bool`**: produces `x != 0` (it does not truncate, so
  `2 as bool` is `true`);
- **`T as T`**: allowed for every type and has no effect.

Pointer casts follow these rules:

- `^T` may be cast to `^u8`;
- `^u8` may be cast to another `^T`;
- the latter conversion is accepted without proving alignment or layout safety
  and may therefore produce undefined behavior.

Every other cast is invalid, including casts between other pointer types,
between pointers and integers, and any cast involving arrays or slices (except
`T as T`). Invalid cast pairs are reported as `AnalyzerError(8)`.

### Arrays, slices, fields, and ranges

- An index expression requires an array or slice target and an index of any
  integer type, signed or unsigned. Its result is the element type.
- A range expression requires a slice target or an addressable array target,
  and bounds of any integer type. Its result is a slice of the target's element
  type. `arr[..]` is the explicit way to turn an array into a slice.
- Range bounds may be omitted as permitted by the parser. The analyzer checks
  only their types and does not require compile-time bounds unless a later
  rule adds that requirement.
- Mid has no user-defined aggregate types, so field access is invalid in
  general. The only valid field is `.len`:
  - on an array `[N]T` it has type `usize` and is resolved at compile time to
    `N`;
  - on a slice `[]T` it has type `usize` and reads the slice's length at run
    time;
  - it is read-only.

  Any other field name, or `.len` on a type that is not an array or slice, is
  reported as `AnalyzerError(9)`.

## Statements and control flow

- `if` conditions must have type `bool`.
- `loop` creates a nested scope and a loop context.
- `break` is valid only inside a loop.
- `continue` is valid only inside a loop.
- `return` is checked against the enclosing function's return type.
- Variable declarations and assignments are checked in source order.
- An expression statement may contain any valid expression, including a call
  to a void function.

The current semantic contract validates loop context but does not diagnose
unreachable statements after `break`, `continue`, or `return`.

## Error nodes

The parser may produce `ErrorNode` nodes. The analyzer skips them without
reporting new errors: an `ErrorNode` expression has an internal *error type*
that is compatible with every type and every operator, so a single syntax
error does not cascade into additional semantic errors. The same error type is
given to any expression whose analysis already reported an error.

## Implementation and annotated AST

The implementation lives in `src/mid/frontend/analyzer.py`, with the symbol
table in `src/mid/types/symbol_table.py` and the semantic types in
`src/mid/types/sem_type.py`.

Types are represented by `SemType(name, qual)`: a base name plus a tuple of
`Pointer()`, `Array(size)` and `Slice()` qualifiers, outermost first. `SemType`
values compare by structure and are hashable. Predefined values: `U8`, `BOOL`,
`I32`, `U32`, `F32`, `USIZE`, `VOID` (return type of functions without
`-> type`) and `ERROR` (expressions whose analysis failed). Symbols store
`SemType` values in `type`, `parameters` and `return_type`.

The analyzer returns the same AST object it receives, annotated in place
through two keyword-only fields of every `ASTNode` (both `None` before
analysis and ignored by `==`):

| Field | Set on | Meaning |
| --- | --- | --- |
| `ty` | every expression | the expression's type |
| `ty` | `VarDecl`, `Param` | the variable's type (also for `:=`) |
| `ty` | `Type` | the resolved type |
| `symbol` | `Identifier` | the symbol it refers to (also the callee of a call) |
| `symbol` | `VarDecl`, `Param`, `FnDecl` | the symbol it declares |

`symbol.is_global` distinguishes global variables from locals. Since sibling
blocks may reuse names, the code generator should identify storage by symbol
object rather than by name.

A unary `-` applied directly to an `Int` is a single negative literal: both
nodes get the literal's type and `Int.val` keeps the absolute value. For
example `-2147483648` is `UnaryExpr(NEGATE, Int(2147483648))` typed `i32`; the
code generator should emit it as one constant.

## Semantic diagnostics

Semantic diagnostics follow the established lexer/parser strategy:

1. append a structured `AnalyzerError` containing code, span, and message to
   the returned `errors` list; and
2. let the compiler driver print `AnalyzerError(code) [line:L, col:C]: message`
   to `stderr` after aggregating all front-end errors.

| Code | Condition |
| --- | --- |
| `AnalyzerError(1)` | Name is undeclared or used before its declaration |
| `AnalyzerError(2)` | Duplicate declaration or forbidden shadowing |
| `AnalyzerError(3)` | Unknown type name or invalid type (array size `0`) |
| `AnalyzerError(4)` | Type mismatch, or literal out of range for its type |
| `AnalyzerError(5)` | Invalid operator operands |
| `AnalyzerError(6)` | Invalid assignment target or protected symbol assignment |
| `AnalyzerError(7)` | Invalid function call or argument list |
| `AnalyzerError(8)` | Invalid cast |
| `AnalyzerError(9)` | Invalid index, range, field, pointer, or dereference operation |
| `AnalyzerError(10)` | Invalid `break`, `continue`, or return, or missing return |
| `AnalyzerError(11)` | Missing or invalid `main` function |

The analyzer should continue after recoverable semantic errors so it can report
multiple independent issues in one run.
