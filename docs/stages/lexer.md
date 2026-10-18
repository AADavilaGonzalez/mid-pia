/*
This document is incomplete and contains some ambiguities. If asked to implement this
as is warn the user first before proceeding. Issues include
- FLOAT dot ambiguity with COLON and COLON_COLON
- Inconsistent STRING, CHAR, FLOAT regexes
- Unclarified use of [-u-1, u] range on INT, (simplify arithmetic and comparison with large negative numbers when type checking)
- probably other errors
Leaving this here for temporary commit
*/

# Lexer Implementation Document

## Goal
Implement a lexer capable of converting a source text input into a series
of tokens according to the regular expressions defined in this document.
- The lexer must abide by the maximal much principle.
- The lexer must implement single line comment handling (line skipping).
- The lexer must implement error recovery and reporting.
- The lexer must convert literal values into a corresponding memory representation.

## Features

### Single line comment removal initated by character sequence '//'
When encountering a '//' character sequence the lexer must skip all input until
the next newline '\n' character. Then it must continue processing the from the
character following the newline
// this is a comment
fn main () { // Valid tokens, then skip until end of line
**This is the only form of commment supported by the language and the lexer**

### Error handling (recovery and emission)
When encountering an error, the lexer must add an error token to the sequnce and
report the error through the standard error stream. Then it must continue processing
by syncing to a known token terminator (i.e unescaped '"' for STRING, !digit() for INT, etc)
or the next following character for simpler tokens. Error recovery must be kept local
to that line. If a newline is encountered while attempting to sync to the token terminator,
the lexer must abandon syncing and continue processing the character after the newline.

**Possible Errors**
LexerError(1): Unexpected character
Emited when the lexer encounters a character it cannot process
(i.e '\0' in the middle of source)

LexerError(2): Unterminated string literal
Emited when string literal does not terminate before newline or EOF

LexerError(3): Integer literal is too large
Emited when integer literal is too large to fit into the biggest supported unsigned
integer type (currently unsigned 64 bit integer)

LexerError(4): Invalid char literal
Emited when the character literal does not correspond to any know char sequence including
supported escape sequences

LexerError(5): Invalid escape sequence

### Literal value conversion
If the lexer encounters any of the following tokens correponding to literals (CHAR, STRING,
INT, FLOAT) then it must convert the token lexeme to a suitable memory representation
and attach the value to the token before emiting it.

**CHAR**
CHARs must be converted to a data representation capable of storing at least
an unsigned 8 bit integer. The data representation must support standar integer arithmetic
Accepted values include all printable ascii characters except for "'" and '\' which must
be inputed with the use of a preceding escape '\'. Additionally, the following characters are
accepted as part of a valid escape escape  digraph (n, t, b, r, a, f, v, 0) and map to the
same values as their traditional C interpretation. Thererefore all valid value for any
char literal lie within the range 0 - 126 with some values not being able to be represented
directly through char literals such as ASCII 127 DEL.

**STRING**
STRINGs must be converted to a data representation capable of storing an arbitrarily
long sequence of bytes. The value of the token is derived by removing the start and end
'"' characters from the lexeme and collapsing all escape sequences found inside of the
contents of the lexeme to their corresponding ascii values. Supported escape sequences:
(\n, \t, \b, \r, \a, \f, \v, \0, \").

**INT**
INTs must be converted to a data representation capable of storing the any integer in the
range `[-u-1,u]` where u is equal to the largest unsigned integer supported by the language.
Currently the largest supported unsigned integer is the unsigned 64 bit integer limit.
The data representation must be able to perform standard integer arithmetic. The conversion
should be done following standard no separators allowed interger parsing rules.

**FLOAT**
FLOATs must be converted to a data representation capable of storing any single precission
32 bit floating point number. The data representaton mist be abe to perform standard 32bit
floating point arithmetic. The converision should be done following standard no separators
allowed floating point parsing rules.

## List of Tokens
``` text
- LPAREN            : (
- RPAREN            : )
- LBRACE            : {
- RBRACE            : }
- LBRACKET          : [
- RBRACKET          : ]
- COMMA             : ,
- SEMICOLON         : ;
- CARET             : ^
- COLON             : :
- COLON_EQUAL       : :=
- PLUS              : +
- PLUS_EQUAL        : +=
- MINUS             : -
- MINUS_EQUAL       : -=
- ARROW             : ->
- STAR              : *
- STAR_EQUAL        : *=
- SLASH             : /
- SLASH_EQUAL       : /=
- PERCENT           : %
- PERCENT_EQUAL     : %=
- GREATER           : >
- GREATER_EQUAL     : >=
- LESSER            : <
- LESSER_EQUAL      : <=
- BANG              : !
- BANG_EQUAL        : !=
- AMP               : &
- AMPAMP            : &&
- BARBAR            : ||
- EQUAL             : =
- EQUAL_EQUAL       : ==
- DOT               : .
- DOTDOT            : ..
- FUNCTION          : fn
- AS                : as
- RETURN            : return
- LOOP              : loop
- BREAK             : break
- CONTINUE          : continue
- IF                : if
- ELSE              : else
- TRUE              : true
- FALSE             : false
- INTEGER           : [0-9]+
- FLOAT             : ([0-9]+\.|[0-9]*\.[0-9]+)
- CHAR              : '([^\\']|\\(n|t|b|r|a|f|v|0|\\|'))'
- STRING            : ".*"
- IDENT             : [a-zA-Z_][a-zA-Z0-9_]*
- ERROR             : **NA**
- EOF               : **NA**
```
