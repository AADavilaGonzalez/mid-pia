# Parser Specification

The parser consumes the token sequence produced by the lexer and constructs an
unannotated abstract syntax tree (AST). It validates grammatical structure,
preserves source spans, and reports recoverable syntax errors. Type validity,
name resolution, and assignability are semantic-analysis responsibilities.

The parser is specified as a recursive-descent parser. Expression parsing uses
one routine per precedence level, from logical-or expressions down to postfix
expressions.

## Grammar

The grammar below is the normative grammar for the parser. Quoted keywords and
punctuation refer to their corresponding lexer tokens.

```ebnf
type                ::= { "^" | "[" [ INTEGER ] "]" } IDENT ;

(* toplevel grammar *)
program             ::= { var_decl | fn_decl } ;

fn_decl             ::= "fn" IDENT param_list [ "->" type ] block ;
param_list          ::= "(" [ param { "," param } [ "," ] ] ")";
param               ::= IDENT ":" type ;

block               ::= "{" { statement } "}";


(* statement grammar *)
statement           ::= var_decl | complex_stmt | if_stmt | loop_stmt
                      | return_stmt | continue_stmt | break_stmt ;

continue_stmt       ::= "continue" ";" ;

break_stmt          ::= "break" ";" ;

return_stmt         ::= "return" [ expression ] ";" ;

loop_stmt           ::= "loop" block ;

if_stmt             ::= "if" expression block { "else" "if" expression block } [ "else" block ] ;

var_decl            ::= IDENT ( ":=" expression | ":" type [ "=" expression ] ) ";" ;

(* covers both expr_stmt and assign_stmt *)
complex_stmt        ::= expression [ assign_op expression ] ";" ;
assign_op           ::= "=" | "+=" | "-=" | "*=" | "/=" | "%=" ;



(* expression grammar *)
expression          ::= logic_or ;

logic_or            ::= logic_and { "||" logic_and } ;

logic_and           ::= equality { "&&" equality } ;

equality             ::= comparison { ( "==" | "!=" ) comparison } ;

comparison           ::= term { ( ">" | "<" | ">=" | "<=" ) term } ;

term                ::= factor { ( "+" | "-" ) factor } ;

factor              ::= cast { ( "*" | "/" | "%" ) cast } ;

cast                ::= unary { "as" type } ;

unary               ::= ( "!" | "-" | "&" ) unary | postfix ;

postfix             ::= primary { call | idx | "^" } ;

primary             ::= IDENT | INTEGER | FLOAT | CHAR | STRING | "(" expression ")" ;

call                ::= "(" [ expression { "," expression } [","] ] ")";

idx                 ::= "[" expression "]"
```

## Grammar conventions and resolved decisions

- `TRUE` and `FALSE` are also primary expressions. They construct `Bool` nodes,
  even though the compact grammar above lists only the original literal forms.
- The final `IDENT` in `type` is accepted as a type name without checking
  whether it is built-in or declared. Semantic analysis performs that check.
- Type qualifiers are preserved in source order. `^` is a pointer qualifier,
  `[INTEGER]` is a fixed-size array qualifier, and `[]` is a slice qualifier.
- Top level is restricted to `var_decl` and `fn_decl`. Statements are valid
  only inside blocks.
- Parameter lists and calls may contain one trailing comma. Empty parameter
  lists and empty calls are valid.
- The postfix `^` constructs a `DereferenceExpr`
- `complex_stmt` covers both expression statements and assignment statements.
  The parser accepts the grammatical shape; semantic analysis rejects
  non-assignable assignment targets such as literals or binary expressions.
- `else if` clauses are stored as ordered branches of one `IfStmt`, with an
  optional separate final `else` block.

## Parser interface and AST

The parser receives the complete token sequence, including `EOF`, and returns
the current AST wrapper:

```text
parser(tokens) -> AST
AST.program -> Program
```

The parser constructs the AST types in `src/mid/types/ast.py`:

| Source construct          | AST node          |
| ------------------------- | ----------------- |
| Program declarations      | `Program`         |
| `fn` declaration          | `FnDecl`          |
| Variable declaration      | `VarDecl`         |
| Parameter                 | `Param`           |
| Type                      | `Type`            |
| Identifier                | `Identifier`      |
| `INTEGER`                 | `Int`             |
| `FLOAT`                   | `Float`           |
| `CHAR`                    | `Char`            |
| `STRING`                  | `String`          |
| `TRUE` / `FALSE`          | `Bool`            |
| Binary operator           | `BinaryExpr`      |
| `!`, unary `-`, unary `&` | `UnaryExpr`       |
| `as type`                 | `CastExpr`        |
| Call postfix              | `CallExpr`        |
| Index postfix             | `IndexExpr`       |
| Dereference postfix `^`   | `DereferenceExpr` |
| Expression statement      | `ExprStmt`        |
| Assignment statement      | `AssignStmt`      |
| `if` statement            | `IfStmt`          |
| `loop` statement          | `LoopStmt`        |
| `return` statement        | `ReturnStmt`      |
| `continue` statement      | `ContinueStmt`    |
| `break` statement         | `BreakStmt`       |

Literal nodes receive the decoded `val` from their tokens. Identifier and type
names receive their token lexemes. The parser does not perform type inference,
symbol-table lookup, or type compatibility checks.

Every successfully constructed AST node receives a `Span` covering its complete
source construct. The span starts at the first token belonging to the node and
ends immediately after the final token. For a parenthesized expression, the
span includes the parentheses.

Recoverable syntax errors produce explicit error nodes in the AST. The AST
definition must therefore add appropriate error-node types and include them in
the declaration, statement, or expression unions before parser implementation.
The parser may return a partial AST containing valid constructs alongside those
error nodes.

## Operator precedence and associativity

Operators on a lower grammar line bind less tightly than operators on a higher
line. Repeated binary operators at the same level associate left-to-right.
Prefix unary operators recurse into another unary expression, and casts recurse
through the unary level.

Postfix operations are applied in source order and may be chained. For example:

```text
f(x)[i]^
```

is parsed as a call on `f`, followed by indexing, followed by dereferencing.

## Diagnostics and recovery

The parser reports syntax errors in two ways:

1. it appends a structured diagnostic to the parser's diagnostic collection; and
2. it immediately prints a `ParserError(...)` diagnostic to standard error.

Diagnostics include an error code, source position or span, and message. They
must not be printed to standard output.

Recovery uses recursive-descent panic-mode synchronization sets derived from
the grammar:

- **Declaration synchronization:** stop before `fn`, `IDENT`, or `EOF`.
- **Statement synchronization:** stop before `;`, `}`, `fn`, `IDENT`, or a
  statement keyword (`if`, `loop`, `return`, `continue`, or `break`).
- **Expression synchronization:** stop before the caller's delimiters, normally
  `)`, `]`, `,`, `;`, or `}`, without consuming a delimiter belonging to the
  enclosing production.
- **Block synchronization:** after an invalid statement, consume through `;`
  when present; otherwise stop at `}` or `EOF`.

The parser must make progress after every error: recovery either consumes at
least one token or returns because it reached `EOF`. A missing delimiter is
reported where it was expected. An unexpected delimiter is left for the
enclosing production when doing so is safe.

Typical parser errors include:

- missing `;`, `)`, `]`, or `}`;
- missing identifier, type name, or expression;
- malformed parameter or argument lists;
- a declaration or statement in an invalid context;
- an unexpected `EOF` before a required construct is complete;
- a lexer `ERROR` token appearing where a syntactic token is required.

Lexer `ERROR` tokens are consumed as invalid parser input. The parser reports a
syntax diagnostic, creates an error node for the affected construct, and
continues according to the applicable synchronization set.
