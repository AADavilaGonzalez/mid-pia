``` ebnf
type                ::= { "^" | "[" [ INT ] "]" } IDENT ;

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
postfix             ::= primary { call | idx | "^" } ;
primary             ::= IDENT | INT | FLOAT | CHAR | STRING | "(" expression ")" ;

call                ::= "(" [ expression { "," expression } [","] ] ")";
idx                 ::= "[" expression "]"
```
