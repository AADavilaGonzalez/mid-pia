## Variable declaration before use
Variables must be declared before they can be used as a target for assignment or
inside of an expression
Allowed
```
x: i32;
x = x + 1;
```
Not Allowed
```
x = x + 1;
```
Implemented by: Checking presence of name in symbol table. Symbol not being
present leads to error

## No variable redeclaration
Once a variable has been declared it cannot be declared again later
in the program
Allowed
```
x: i32;
y: i32;
```
Not Allowed
```
x: i32;
x: i32;
```
Implemented by: Checking for presence of name in symbol table. Symbol already
being present leads to error

## Number literal limit
All number literals must be equal to or less than 2^31 - 1
