# Lexical Analysis

The lexer converts Mid source text into a sequence of tokens. It is the first
compiler stage and does not validate whether the resulting token sequence is a
syntactically valid program; that is the parser's responsibility.

This document is the lexical contract for the language. The implementation and
its tests must be aligned with this contract before the parser is implemented.

## Input and output

The lexer receives one source string and returns an ordered token sequence that
always ends with `EOF`. Every token contains:

- `lexeme`: the exact source slice consumed by the token;
- `type`: one of the token types listed below;
- `pos`: the token's starting source position;
- `val`: a decoded value for literal and boolean tokens, or `None` otherwise.

Source positions use a zero-based character index and one-based line and column
numbers. A token's position is the position of its first source character.
`EOF` has an empty lexeme and the position immediately after the final source
character.

## Scanning rules

The lexer scans from left to right and applies the **maximal munch** rule:
when more than one token can begin at the current character, it consumes the
longest valid token. This is especially important for:

- `:=`, `+=`, `-=`, `->`, `*=`, `/=`, `%=`;
- `>=`, `<=`, `!=`, `&&`, `||`, `==`;
- `..`, which must not be consumed as part of a decimal literal.

Signs are operators, not part of numeric literals. For example, `-128` is
tokenized as `MINUS` followed by `INTEGER(128)`.

### Whitespace and comments

The lexer ignores spaces, tabs, carriage returns, and newlines. Newlines still
update the position recorded on subsequent tokens.

Mid supports only single-line comments. The sequence `//` causes the lexer to
skip characters up to, but not including, the next newline or the end of input.
Comment markers inside a character or string literal are ordinary literal
contents. Block comments are not supported: `/` and `*` are scanned as their
individual operators.

## Token types

| Token           | Lexeme |
| --------------- | ------ |
| `LPAREN`        | `(`    |
| `RPAREN`        | `)`    |
| `LBRACE`        | `{`    |
| `RBRACE`        | `}`    |
| `LBRACKET`      | `[`    |
| `RBRACKET`      | `]`    |
| `COMMA`         | `,`    |
| `SEMICOLON`     | `;`    |
| `CARET`         | `^`    |
| `COLON`         | `:`    |
| `COLON_EQUAL`   | `:=`   |
| `PLUS`          | `+`    |
| `PLUS_EQUAL`    | `+=`   |
| `MINUS`         | `-`    |
| `MINUS_EQUAL`   | `-=`   |
| `ARROW`         | `->`   |
| `STAR`          | `*`    |
| `STAR_EQUAL`    | `*=`   |
| `SLASH`         | `/`    |
| `SLASH_EQUAL`   | `/=`   |
| `PERCENT`       | `%`    |
| `PERCENT_EQUAL` | `%=`   |
| `GREATER`       | `>`    |
| `GREATER_EQUAL` | `>=`   |
| `LESSER`        | `<`    |
| `LESSER_EQUAL`  | `<=`   |
| `BANG`          | `!`    |
| `BANG_EQUAL`    | `!=`   |
| `AMP`           | `&`    |
| `AMP_AMP`       | `&&`   |
| `BAR_BAR`       | `||`   |
| `EQUAL`         | `=`    |
| `EQUAL_EQUAL`   | `==`   |
| `DOT`           | `.`    |
| `DOT_DOT`       | `..`   |

The following identifier lexemes are reserved keywords:

| Lexeme     | Token      |
| ---------- | ---------- |
| `fn`       | `FUNCTION` |
| `as`       | `AS`       |
| `return`   | `RETURN`   |
| `loop`     | `LOOP`     |
| `break`    | `BREAK`    |
| `continue` | `CONTINUE` |
| `if`       | `IF`       |
| `else`     | `ELSE`     |
| `true`     | `TRUE`     |
| `false`    | `FALSE`    |

All other identifiers match `[A-Za-z_][A-Za-z0-9_]*`. Identifiers are
case-sensitive and use ASCII letters only.

## Literals

Literal lexemes are converted before their tokens are emitted. The original
lexeme remains available on the token.

### Integers

An integer matches `[0-9]+`. Separators, exponents, and decimal points are not
part of an integer. Leading zeroes are allowed.

The decoded value is an unsigned 64-bit-range integer:

```text
0 <= value <= 2^64 - 1
```

An integer's sign is represented by a separate `MINUS` or `PLUS` token. An
integer outside the range produces an `ERROR` token and a `LexerError(3)`
diagnostic.

### Floating-point numbers

A floating-point literal matches `[0-9]+\.[0-9]+`. Both the integer part and
the fractional part require at least one digit. Therefore:

- `3.14` is one `FLOAT` token;
- `.5` is `DOT` followed by `INTEGER(5)`;
- `1.` is `INTEGER(1)` followed by `DOT`;
- `1..5` is `INTEGER(1)`, `DOT_DOT`, `INTEGER(5)`;
- `buff.len` is `IDENT`, `DOT`, `IDENT`.

The decoded value is rounded to IEEE 754 single-precision (`f32`). Values that
underflow to zero are valid. A value that cannot be represented as a finite
`f32` produces an `ERROR` token and a `LexerError(6)` diagnostic.

### Characters

A character literal is enclosed by single quotes and contains exactly one
decoded ASCII character. Printable ASCII characters from space through `~` are
accepted, except for `'` and `\`, which must be escaped. The supported escape
sequences are:

| Escape | Value           |
| ------ | --------------- |
| `\n`   | newline         |
| `\t`   | horizontal tab  |
| `\b`   | backspace       |
| `\r`   | carriage return |
| `\a`   | alert           |
| `\f`   | form feed       |
| `\v`   | vertical tab    |
| `\0`   | NUL             |
| `\\`   | backslash       |
| `\'`   | single quote    |

The token value is the character's integer code. Invalid or unterminated
character literals produce an `ERROR` token and a `LexerError(4)` diagnostic.

### Strings

A string literal is enclosed by double quotes. Its contents may contain
printable ASCII characters and the common escapes `\n`, `\t`, `\b`, `\r`, `\a`,
`\f`, `\v`, `\0`, and `\\`, plus the double-quote escape `\"`. The
single-quote escape `\'` is valid only in character literals. Raw newlines,
other control characters, and non-ASCII characters are not valid string
contents.

The token value is the string after removing the delimiters and decoding every
escape sequence. An unterminated string produces an `ERROR` token and a
`LexerError(2)` diagnostic. An invalid escape sequence produces an `ERROR`
token and a `LexerError(5)` diagnostic.

### Boolean keywords

`true` and `false` are reserved tokens. Their decoded values are `1` and `0`,
respectively, so they can be represented by the token value type used for
literal values.

## Errors and recovery

The lexer reports every recoverable lexical error in two ways:

1. it appends an `ERROR` token to the output sequence; and
2. it immediately prints a diagnostic to standard error in the form
   `LexerError(code) [line:L, col:C]: message`.

Diagnostics are not printed to standard output. The lexer does not silently
collect errors for a later phase, and callers do not need a separate error
list to know that scanning failed.

| Code            | Condition                                                 |
| --------------- | --------------------------------------------------------- |
| `LexerError(1)` | Unexpected character or invalid raw character in a string |
| `LexerError(2)` | Unterminated string literal                               |
| `LexerError(3)` | Integer is outside the unsigned 64-bit range              |
| `LexerError(4)` | Invalid or unterminated character literal                 |
| `LexerError(5)` | Unsupported escape sequence                               |
| `LexerError(6)` | Floating-point value overflows finite `f32`               |

Recovery is local to the current token and must not discard the next source
line:

- for a number, consume the complete numeric lexeme before emitting `ERROR`;
- for a quoted literal, continue through its closing quote when possible;
- if a quoted literal reaches a newline or end of input first, emit the error
  without consuming the newline, then resume scanning after normal newline
  handling;
- for a simple unexpected character, consume that character and resume at the
  following character.

After recovery, the lexer continues scanning and emits `EOF` normally.
