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

equality            ::= comparison { ( "==" | "!=" ) comparison } ;

comparison          ::= term { ( ">" | "<" | ">=" | "<=" ) term } ;

term                ::= factor { ( "+" | "-" ) factor } ;

factor              ::= cast { ( "*" | "/" | "%" ) cast } ;

cast                ::= unary { "as" type } ;

unary               ::= ( "!" | "-" | "&" ) unary | postfix ;

postfix             ::= primary { call | idx | field | "^" } ;

primary             ::= IDENT | INTEGER | FLOAT | CHAR | STRING
                      | "true" | "false" | "(" expression ")" ;

call                ::= "(" [ expression { "," expression } [","] ] ")" ;

idx                 ::= "[" expression "]"
                      | "[" [ expression ] ".." [ expression ] "]" ;

field               ::= "." IDENT ;
```

## Grammar conventions and resolved decisions

- `true` and `false` are primary expressions. They construct `Bool` nodes.
- The final `IDENT` in `type` is accepted as a type name without checking
  whether it is built-in or declared. Semantic analysis performs that check.
- Type qualifiers are preserved in source order. `^` is a pointer qualifier,
  `[INTEGER]` is a fixed-size array qualifier, and `[]` is a slice qualifier.
- Top level is restricted to `var_decl` and `fn_decl`. Statements are valid
  only inside blocks.
- Parameter lists and calls may contain one trailing comma. Empty parameter
  lists and empty calls are valid.
- The postfix `^` constructs a `DereferenceExpr`.
- The postfix `.` followed by an identifier constructs a `FieldExpr`. Whether
  the field exists is a semantic-analysis responsibility.
- Brackets that contain `..` construct a `SliceExpr`. Both bounds are
  optional, so `a[1..]`, `a[..3]`, `a[1..3]` and `a[..]` are valid. Brackets
  without `..` construct an `IndexExpr`. A range is only valid inside brackets.
- `complex_stmt` covers both expression statements and assignment statements.
  The parser accepts the grammatical shape; semantic analysis rejects
  non-assignable assignment targets such as literals or binary expressions.
- A statement that starts with an identifier followed by `:=` or `:` is a
  `var_decl`. Any other statement that starts with an identifier is a
  `complex_stmt`. The parser needs one token of lookahead to decide.
- `else if` clauses are stored as ordered branches of one `IfStmt`, with an
  optional separate final `else` block.

## Parser interface and AST

The parser receives the complete token sequence, including `EOF`, and returns
the current AST wrapper:

```text
parser(tokens) -> AST
AST.program -> Program
```

The diagnostics of a run are also available through the `Parser` class:
`Parser(tokens).parse()` returns the same AST, and `Parser.diagnostics` holds
the list of `Diagnostic(code, span, message)` produced while parsing.

The parser constructs the AST types in `src/mid/types/ast.py`:

| Source construct                    | AST node          |
| ----------------------------------- | ----------------- |
| Program declarations                | `Program`         |
| `fn` declaration                    | `FnDecl`          |
| Variable declaration                | `VarDecl`         |
| Parameter                           | `Param`           |
| Type                                | `Type`            |
| Identifier                          | `Identifier`      |
| `INTEGER`                           | `Int`             |
| `FLOAT`                             | `Float`           |
| `CHAR`                              | `Char`            |
| `STRING`                            | `String`          |
| `TRUE` / `FALSE`                    | `Bool`            |
| Binary operator                     | `BinaryExpr`      |
| `!`, unary `-`, unary `&`           | `UnaryExpr`       |
| `as type`                           | `CastExpr`        |
| Call postfix                        | `CallExpr`        |
| Index postfix `[i]`                 | `IndexExpr`       |
| Range index postfix `[a..b]`        | `SliceExpr`       |
| Field access postfix `.name`        | `FieldExpr`       |
| Dereference postfix `^`             | `DereferenceExpr` |
| Expression statement                | `ExprStmt`        |
| Assignment statement                | `AssignStmt`      |
| `if` statement                      | `IfStmt`          |
| `loop` statement                    | `LoopStmt`        |
| `return` statement                  | `ReturnStmt`      |
| `continue` statement                | `ContinueStmt`    |
| `break` statement                   | `BreakStmt`       |
| Recoverable syntax error            | `ErrorNode`       |

Literal nodes receive the decoded `val` from their tokens. Identifier and type
names receive their token lexemes. The parser does not perform type inference,
symbol-table lookup, or type compatibility checks.

Every successfully constructed AST node receives a `Span` covering its complete
source construct. The span starts at the first token belonging to the node and
ends immediately after the final token. For a parenthesized expression, the
span includes the parentheses. An `if` branch that starts with `else if` has a
span that starts at the `else` token.

Recoverable syntax errors produce `ErrorNode` nodes in the AST. `ErrorNode` is
a single node type, included in the declaration, statement, and expression
unions, whose span covers the invalid construct. A missing expression produces
an empty span right after the last consumed token. The parser may return a
partial AST containing valid constructs alongside error nodes.

## Operator precedence and associativity

Operators on a lower grammar line bind less tightly than operators on a higher
line. Repeated binary operators at the same level associate left-to-right.
Prefix unary operators recurse into another unary expression, and casts recurse
through the unary level.

Postfix operations (call, index, range index, field access and dereference)
share one precedence level. They are applied in source order and may be
chained. For example:

```text
f(x).items[i]^
```

is parsed as a call on `f`, followed by field access, then indexing, then
dereferencing.

## Diagnostics and recovery

The parser reports syntax errors in two ways:

1. it appends a structured diagnostic to the parser's diagnostic collection; and
2. it immediately prints a `ParserError(...)` diagnostic to standard error in
   the form `ParserError(code) [line:L, col:C]: message`.

Diagnostics include an error code, source position or span, and message. They
must not be printed to standard output.

| Code             | Condition                                                  |
| ---------------- | ---------------------------------------------------------- |
| `ParserError(1)` | Unexpected token                                           |
| `ParserError(2)` | Missing expression                                         |
| `ParserError(3)` | Missing identifier (function, parameter or field name)     |
| `ParserError(4)` | Missing type name                                          |
| `ParserError(5)` | Missing delimiter (`;`, `)`, `]`, `}`, `{`, `(` or `:`)    |
| `ParserError(6)` | Unexpected end of file                                     |
| `ParserError(7)` | Invalid token produced by the lexer (`ERROR` token)        |
| `ParserError(8)` | Declaration or statement in an invalid context             |

Recovery uses recursive-descent panic-mode synchronization sets derived from
the grammar:

- **Declaration synchronization:** stop before `fn`, `IDENT`, or `EOF`.
- **Statement synchronization:** stop before `;`, `}`, `fn`, `IDENT`, or a
  statement keyword (`if`, `loop`, `return`, `continue`, or `break`).
- **Expression synchronization:** stop before the caller's delimiters, normally
  `)`, `]`, `,`, `;`, `{`, or `}`, and before `fn` or a statement keyword,
  without consuming a delimiter belonging to the enclosing production.
- **Block synchronization:** after an invalid statement, consume through `;`
  when present; otherwise stop at `}` or `EOF`. A `fn` found inside a block
  ends the block as if a `}` were missing, and the declaration is parsed at
  top level.

The parser must make progress after every error: recovery either consumes at
least one token or returns because it reached `EOF`. A missing delimiter is
reported where it was expected, which is right after the last consumed token.
An unexpected delimiter is left for the enclosing production when doing so is
safe. A missing delimiter does not consume any token, and parsing continues as
if the delimiter were present.

An `else` without a matching `if` is reported, and its optional condition and
block are consumed so that its closing `}` does not end the enclosing block.

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
