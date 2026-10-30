``` ebnf

program ::= { stmt } ;

stmt ::= decl | assign | print ;
decl ::= IDENT ":" "i32" ";" ;
assign ::= IDENT "=" expr ";" ;
print ::= "print" expr ";" ;

expr ::= term ;
term = factor { ("+" | "-") factor } ;
factor = primary { ("*" | "/") primary } ;
primary = IDENT | NUMBER | "(" expr ")" ;

```
