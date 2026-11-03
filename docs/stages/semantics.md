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
- exact type compatibility for assignments, arguments, and returns;
- explicit cast validity;
- operator operand and result types;
- function-call arity and argument types;
- array, slice, field, pointer, and dereference operations;
- `break` and `continue` loop context;
- function return rules;
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
| `usize` | Word-sized unsigned integer |

Qualified types are formed by applying the qualifiers parsed in source order:

| Syntax | Meaning |
| --- | --- |
| `^T` | Pointer to `T` |
| `[N]T` | Fixed-size array of `N` elements of `T` |
| `[]T` | Slice of `T` |

The analyzer resolves the final type-name identifier and rejects unknown type
names. Qualifier order is preserved; semantically distinct qualified types are
not interchangeable merely because they contain the same components.

The analyzer uses the AST `Type` nodes as the primary type representation. If
normalization, canonical identity, or inferred type information cannot be
represented by the AST node, the implementation may introduce a separate
semantic type object and attach it to the annotated AST.

There are no implicit conversions. Assignment, initialization, function
arguments, and return values require exact type compatibility unless an
explicit cast is present.

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
type must exactly match the declared type.

Variables are mutable, including global variables. A local variable becomes
visible only after its declaration has been semantically checked and inserted
into the current scope. A variable cannot be read before its declaration.

This phase checks declaration visibility, not definite initialization. A
declared variable may therefore be read even if its declaration did not include
an initializer; runtime initialization behavior is defined by later stages.

### Functions

Functions have a unique name in the global scope. Defining the same function
name more than once is a redeclaration error, including collisions with a
standard-library function.

Function parameters are symbols in the function scope. Parameter names must be
unique within that function and cannot shadow any visible name under the
language's no-shadowing rule.

If a function has no `-> type`, its `FnDecl.ret_type` is `None` and it has void
return behavior. A void function
may use `return;` but may not return an expression. A function with a declared
return type may return expressions only when their type exactly matches that
return type.

The analyzer checks that a non-void function returns a value on every required
execution path. A function with no return type may complete without an explicit
return.

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
variables, parameters, functions, built-in functions, and type names whenever
the names share the same namespace.

Global declarations are processed in two steps:

1. all global functions and variables are predeclared so global references can
   resolve consistently; and
2. global variable initializers are analyzed and evaluated in source order.

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

The analyzer preloads the standard-library functions into the global scope:

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

### Literals and identifiers

| Expression | Type |
| --- | --- |
| character literal | `u8` |
| boolean literal | `bool` |
| integer literal | `i32` by default, subject to range checking |
| float literal | `f32` |
| string literal | `[]u8` |
| identifier | type of its resolved symbol |

Unsuffixed integer literals default to `i32`. An integer literal whose value
cannot be represented by `i32` is a semantic error unless a later language rule
adds an explicit contextual typing mechanism.

An identifier expression resolves to a variable, parameter, or function symbol.
Using a function name as a value is invalid unless the language later defines
first-class function values.

### Operators

The standard operator rules are:

- `!` requires `bool` and produces `bool`;
- unary `-` requires a numeric type and preserves that type;
- unary `&` requires an addressable expression and produces a pointer to its
  type;
- `^` requires a pointer and produces its pointee type;
- `&&` and `||` require two `bool` operands and produce `bool`;
- `+`, `-`, `*`, `/`, and `%` require compatible numeric operands and produce
  the common exact type;
- `<`, `>`, `<=`, and `>=` require compatible ordered operands and produce
  `bool`;
- `==` and `!=` require compatible comparable operands and produce `bool`.

Pointer arithmetic, array arithmetic, and aggregate arithmetic are invalid.
Pointer equality and ordering are invalid unless explicitly added to the
language rules.

### Assignment

The left side of an assignment must be assignable and the right side must have
the exact same type. Assignable expressions include mutable variables,
dereferences of valid pointers, and valid mutable indexed storage. Function
symbols and standard-library symbols are not assignable.

Compound assignments (`+=`, `-=`, `*=`, `/=`, `%=`) require the same operand
rules as the corresponding binary operator and update the target in place.

### Calls

The callee must resolve to a function symbol. The number of arguments must equal
the number of parameters, and each argument must have the exact corresponding
parameter type. A call expression has the function's return type; calling a
void function in a value-required context is an error.

### Casts

Explicit casts use the `as` operator. Primitive casts are allowed only between
permitted primitive types defined by the language's type-conversion table.
Implicit conversions are never inserted.

Pointer casts follow these rules:

- `^T` may be cast only to `^u8`;
- `^u8` may be cast to another `^T`;
- the latter conversion is accepted without proving alignment or layout safety
  and may therefore produce undefined behavior.

Invalid cast pairs are semantic errors.

### Arrays, slices, fields, and ranges

- An index expression requires an array or slice target and an integer index.
  Its result is the element type.
- A range expression requires an array or slice target and integer bounds.
  Its result is a slice of the target's element type.
- Range bounds may be omitted as permitted by the parser. The analyzer checks
  only their types and does not require compile-time bounds unless a later
  rule adds that requirement.
- Field access is currently invalid for all types because Mid does not yet
  define user-visible aggregate or field-bearing types. The AST support is
  reserved for a future type-system extension.

## Statements and control flow

- `if` conditions must have type `bool`.
- `loop` creates a nested scope and a loop context.
- `break` is valid only inside a loop.
- `continue` is valid only inside a loop.
- `return` is checked against the enclosing function's return type.
- Variable declarations and assignments are checked in source order.

The current semantic contract validates loop context but does not diagnose
unreachable statements after `break`, `continue`, or `return`.

## Semantic diagnostics

Semantic diagnostics follow the established lexer/parser strategy:

1. append a structured diagnostic containing code, span, and message to the
   returned `errors` list; and
2. let the compiler driver print `SemanticError(code) [line:L, col:C]: message`
   to `stderr` after aggregating all front-end errors.

Suggested diagnostic categories include:

| Code | Condition |
| --- | --- |
| `SemanticError(1)` | Name is undeclared |
| `SemanticError(2)` | Duplicate declaration or forbidden shadowing |
| `SemanticError(3)` | Unknown type name |
| `SemanticError(4)` | Type mismatch |
| `SemanticError(5)` | Invalid operator operands |
| `SemanticError(6)` | Invalid assignment target or protected symbol assignment |
| `SemanticError(7)` | Invalid function call or argument list |
| `SemanticError(8)` | Invalid cast |
| `SemanticError(9)` | Invalid index, range, field, pointer, or dereference operation |
| `SemanticError(10)` | Invalid `break`, `continue`, or return |

The analyzer should continue after recoverable semantic errors so it can report
multiple independent issues in one run.
