"""Recursive-descent parser for Mid.

Input: token list produced by the lexer (it must end with EOF).
Output: unannotated AST.

Syntax errors are collected as ``ParserError`` objects and returned with the
AST. The returned AST may be partial: invalid constructs become ``ErrorNode``
nodes. The compiler driver is responsible for printing the collected errors.

Error codes (the specification does not fix them, these are the ones used here):

    1  unexpected token
    2  missing expression
    3  missing identifier
    4  missing type name
    5  missing delimiter (';', ')', ']', '}', ...)
    6  unexpected end of file
    7  invalid token produced by the lexer (ERROR token)
    8  declaration or statement in an invalid context
"""

from copy import copy

from mid.types.ast import (
    AST,
    AssignStmt,
    BinaryExpr,
    Block,
    Bool,
    BreakStmt,
    CallExpr,
    CastExpr,
    Char,
    ContinueStmt,
    DereferenceExpr,
    ErrorNode,
    Expr,
    ExprStmt,
    FieldExpr,
    Float,
    FnDecl,
    Identifier,
    IfStmt,
    IndexExpr,
    Int,
    LoopStmt,
    Param,
    Program,
    ReturnStmt,
    SliceExpr,
    String,
    Type,
    UnaryExpr,
    VarDecl,
)
from mid.types.token import Token, TokenType as T
from mid.types.errors import ParserError
from mid.types.util import Pos, Span

E_UNEXPECTED = 1
E_EXPR = 2
E_IDENT = 3
E_TYPE = 4
E_DELIM = 5
E_EOF = 6
E_LEXER = 7
E_CONTEXT = 8


# Binary operators by precedence level, from the loosest (logic_or) to the
# tightest (factor). Each level is left associative.
BINARY_LEVELS: list[dict[T, BinaryExpr.Op]] = [
    {T.BAR_BAR: BinaryExpr.Op.OR},
    {T.AMP_AMP: BinaryExpr.Op.AND},
    {T.EQUAL_EQUAL: BinaryExpr.Op.EQUAL, T.BANG_EQUAL: BinaryExpr.Op.NOT_EQUAL},
    {
        T.GREATER: BinaryExpr.Op.GREATER,
        T.LESSER: BinaryExpr.Op.LESSER,
        T.GREATER_EQUAL: BinaryExpr.Op.GREATER_EQUAL,
        T.LESSER_EQUAL: BinaryExpr.Op.LESSER_EQUAL,
    },
    {T.PLUS: BinaryExpr.Op.ADD, T.MINUS: BinaryExpr.Op.SUB},
    {
        T.STAR: BinaryExpr.Op.MULT,
        T.SLASH: BinaryExpr.Op.DIV,
        T.PERCENT: BinaryExpr.Op.MOD,
    },
]

UNARY_OPS = {
    T.BANG: UnaryExpr.Op.NOT,
    T.MINUS: UnaryExpr.Op.NEGATE,
    T.AMP: UnaryExpr.Op.ADDRESS,
}

ASSIGN_OPS = {
    T.EQUAL: AssignStmt.Op.DIRECT,
    T.PLUS_EQUAL: AssignStmt.Op.ADD,
    T.MINUS_EQUAL: AssignStmt.Op.SUB,
    T.STAR_EQUAL: AssignStmt.Op.MULT,
    T.SLASH_EQUAL: AssignStmt.Op.DIV,
    T.PERCENT_EQUAL: AssignStmt.Op.MOD,
}

STMT_KEYWORDS = {T.IF, T.LOOP, T.RETURN, T.CONTINUE, T.BREAK}

# Tokens that can start an expression.
EXPR_START = {
    T.IDENT, T.INTEGER, T.FLOAT, T.CHAR, T.STRING, T.TRUE, T.FALSE,
    T.LPAREN, T.BANG, T.MINUS, T.AMP,
}

# Synchronization sets for panic-mode recovery (docs/stages/parser.md).
DECL_SYNC = {T.FUNCTION, T.IDENT, T.EOF}
STMT_SYNC = {T.SEMICOLON, T.RBRACE, T.FUNCTION, T.IDENT, T.EOF} | STMT_KEYWORDS
EXPR_SYNC = {
    T.RPAREN, T.RBRACKET, T.COMMA, T.SEMICOLON, T.LBRACE, T.RBRACE,
    T.FUNCTION, T.EOF,
} | STMT_KEYWORDS
LIST_SYNC = {T.COMMA, T.RPAREN, T.LBRACE, T.SEMICOLON, T.RBRACE, T.FUNCTION, T.EOF}


class _Abort(Exception):
    """Unwinds to the nearest declaration or statement after a reported error."""


def describe(token: Token) -> str:
    return "end of file" if token.type == T.EOF else repr(token.lexeme)


class Parser:
    def __init__(self, tokens: list[Token]):
        tokens = list(tokens)
        if not tokens or tokens[-1].type != T.EOF:
            # Tolerate token lists built by hand without the final EOF.
            pos = tokens[-1].end() if tokens else Pos(0, 1, 1)
            tokens.append(Token("", T.EOF, pos, None))
        self.tokens = tokens
        self.pos = 0
        self.errors: list[ParserError] = []

    @property
    def diagnostics(self) -> list[ParserError]:
        """Backward-compatible name for the parser's collected errors."""
        return self.errors

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def peek(self, offset: int = 0) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def at(self, *types: T) -> bool:
        return self.peek().type in types

    def advance(self) -> Token:
        token = self.tokens[self.pos]
        if token.type != T.EOF:
            self.pos += 1
        return token

    def match(self, *types: T) -> Token | None:
        return self.advance() if self.at(*types) else None

    def expect(self, token_type: T, what: str) -> Token | None:
        if self.at(token_type):
            return self.advance()
        self.report_expected(what)
        return None

    def expect_semicolon(self):
        self.expect(T.SEMICOLON, "';'")

    # ------------------------------------------------------------------
    # Spans
    # ------------------------------------------------------------------

    def prev_end(self) -> Pos:
        if self.pos == 0:
            return self.peek().start()
        return self.tokens[self.pos - 1].end()

    def span_from(self, start: Pos) -> Span:
        """Span from ``start`` to just after the last consumed token."""
        end = self.prev_end()
        if end.idx < start.idx:  # nothing consumed since ``start``
            end = copy(start)
        return Span(start, end)

    def missing_span(self) -> Span:
        """Empty span right after the last consumed token."""
        pos = self.prev_end()
        return Span(pos, copy(pos))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def report(self, code: int, message: str, span: Span):
        self.errors.append(ParserError(code, span, message))

    def report_expected(self, what: str):
        """A required token is missing; the offending token is not consumed."""
        token = self.peek()
        if token.type == T.EOF:
            self.report(E_EOF, f"Unexpected end of file, expected {what}", self.missing_span())
        elif token.type == T.ERROR:
            self.report(E_LEXER, f"Invalid token {token.lexeme!r} where {what} was expected", token.span())
        else:
            self.report(E_DELIM, f"Expected {what} but found {describe(token)}", self.missing_span())

    def report_missing(self, code: int, what: str):
        """A required construct (expression, name, type) is missing."""
        token = self.peek()
        if token.type == T.EOF:
            self.report(E_EOF, f"Unexpected end of file, expected {what}", token.span())
        elif token.type == T.ERROR:
            self.report(E_LEXER, f"Invalid token {token.lexeme!r} where {what} was expected", token.span())
        else:
            self.report(code, f"Expected {what} but found {describe(token)}", token.span())

    # ------------------------------------------------------------------
    # Program and declarations
    # ------------------------------------------------------------------

    def parse(self) -> tuple[AST, list[ParserError]]:
        start = self.peek().start()
        decls = []
        while not self.at(T.EOF):
            decls.append(self.declaration())
        return AST(Program(self.span_from(start), decls)), self.errors

    def declaration(self):
        start = self.peek().start()
        try:
            if self.at(T.FUNCTION):
                return self.fn_decl()
            if self.at(T.IDENT):
                return self.var_decl()
            token = self.advance()
            if token.type == T.ERROR:
                self.report(E_LEXER, f"Invalid token {token.lexeme!r}", token.span())
            else:
                self.report(
                    E_CONTEXT,
                    f"Only function and variable declarations are allowed at top level, found {describe(token)}",
                    token.span(),
                )
            raise _Abort
        except _Abort:
            # Every path that reaches here has consumed at least one token.
            while not self.at(*DECL_SYNC):
                self.advance()
            return ErrorNode(self.span_from(start))

    def fn_decl(self) -> FnDecl:
        start = self.peek().start()
        self.advance()  # fn
        name = ""
        if self.at(T.IDENT):
            name = self.advance().lexeme
        else:
            self.report_missing(E_IDENT, "a function name")
        params = self.param_list()
        ret_type = None
        if self.match(T.ARROW):
            ret_type = self.type_()
        body = self.block()
        return FnDecl(self.span_from(start), name, params, ret_type, body)

    def param_list(self) -> list[Param]:
        params: list[Param] = []
        if not self.expect(T.LPAREN, "'('"):
            return params
        while not self.at(T.RPAREN, T.EOF, T.LBRACE):
            param = self.param()
            if param is not None:
                params.append(param)
            if not self.match(T.COMMA):
                break
        self.expect(T.RPAREN, "')'")
        return params

    def param(self) -> Param | None:
        start = self.peek().start()
        if not self.at(T.IDENT):
            self.report_missing(E_IDENT, "a parameter name")
            self.sync_list()
            return None
        name = self.advance().lexeme
        if not self.expect(T.COLON, "':'"):
            self.sync_list()
            return None
        type_ = self.type_()
        if type_ is None:
            self.sync_list()
            return None
        return Param(self.span_from(start), name, type_)

    def sync_list(self):
        while not self.at(*LIST_SYNC):
            self.advance()

    def var_decl(self) -> VarDecl:
        """IDENT (":=" expression | ":" type ["=" expression]) ";" """
        start = self.peek().start()
        name_token = self.advance()
        type_ = None
        init = None
        if self.match(T.COLON_EQUAL):
            init = self.expression()
        elif self.match(T.COLON):
            type_ = self.type_()
            if type_ is None:
                raise _Abort
            if self.match(T.EQUAL):
                init = self.expression()
        else:
            self.report_missing(E_UNEXPECTED, "':=' or ':' after " + repr(name_token.lexeme))
            raise _Abort
        self.expect_semicolon()
        return VarDecl(self.span_from(start), name_token.lexeme, type_, init)

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    def type_(self) -> Type | None:
        """{ "^" | "[" [INTEGER] "]" } IDENT. Returns None (after reporting) if the name is missing."""
        start = self.peek().start()
        qualifiers: list = []
        while True:
            if self.match(T.CARET):
                qualifiers.append(Type.Pointer())
            elif self.match(T.LBRACKET):
                if self.at(T.INTEGER):
                    qualifiers.append(Type.Array(self.advance().val))
                else:
                    qualifiers.append(Type.Slice())
                self.expect(T.RBRACKET, "']'")
            else:
                break
        if not self.at(T.IDENT):
            self.report_missing(E_TYPE, "a type name")
            return None
        name = self.advance().lexeme
        return Type(self.span_from(start), qualifiers, name)

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------

    def block(self) -> Block:
        start = self.peek().start()
        self.expect(T.LBRACE, "'{'")
        stmts = []
        # 'fn' inside a block almost always means a missing '}' before it.
        while not self.at(T.RBRACE, T.EOF, T.FUNCTION):
            stmts.append(self.statement())
        self.expect(T.RBRACE, "'}'")
        return Block(self.span_from(start), stmts)

    def statement(self):
        start = self.peek().start()
        try:
            token_type = self.peek().type
            if token_type == T.IF:
                return self.if_stmt()
            if token_type == T.LOOP:
                return self.loop_stmt()
            if token_type == T.RETURN:
                return self.return_stmt()
            if token_type == T.CONTINUE:
                self.advance()
                self.expect_semicolon()
                return ContinueStmt(self.span_from(start))
            if token_type == T.BREAK:
                self.advance()
                self.expect_semicolon()
                return BreakStmt(self.span_from(start))
            # One token of lookahead separates declarations from expressions.
            if token_type == T.IDENT and self.peek(1).type in (T.COLON_EQUAL, T.COLON):
                return self.var_decl()
            if token_type in EXPR_START:
                return self.complex_stmt()
            if token_type == T.ELSE:
                # Consume the whole dangling clause so its '}' does not close
                # the enclosing block.
                token = self.advance()
                self.report(E_UNEXPECTED, "'else' without a matching 'if'", token.span())
                if self.match(T.IF):
                    self.expression()
                if self.at(T.LBRACE):
                    self.block()
                raise _Abort
            token = self.advance()
            if token.type == T.ERROR:
                self.report(E_LEXER, f"Invalid token {token.lexeme!r}", token.span())
            else:
                self.report(E_UNEXPECTED, f"Unexpected token {describe(token)}, expected a statement", token.span())
            raise _Abort
        except _Abort:
            # Every path that reaches here has consumed at least one token.
            self.sync_statement()
            return ErrorNode(self.span_from(start))

    def sync_statement(self):
        while not self.at(*STMT_SYNC):
            self.advance()
        self.match(T.SEMICOLON)

    def if_stmt(self) -> IfStmt:
        start = self.peek().start()
        self.advance()  # if
        cond = self.expression()
        body = self.block()
        branches = [IfStmt.Branch(self.span_from(start), cond, body)]
        else_body = None
        while self.at(T.ELSE):
            else_start = self.peek().start()
            self.advance()
            if self.match(T.IF):
                cond = self.expression()
                body = self.block()
                branches.append(IfStmt.Branch(self.span_from(else_start), cond, body))
            else:
                else_body = self.block()
                break
        return IfStmt(self.span_from(start), branches, else_body)

    def loop_stmt(self) -> LoopStmt:
        start = self.peek().start()
        self.advance()  # loop
        body = self.block()
        return LoopStmt(self.span_from(start), body)

    def return_stmt(self) -> ReturnStmt:
        start = self.peek().start()
        self.advance()  # return
        value = None
        if not self.at(T.SEMICOLON, T.RBRACE, T.EOF):
            value = self.expression()
        self.expect_semicolon()
        return ReturnStmt(self.span_from(start), value)

    def complex_stmt(self):
        """expression [assign_op expression] ";" (expression or assignment statement)."""
        start = self.peek().start()
        target = self.expression()
        if self.peek().type in ASSIGN_OPS:
            op = ASSIGN_OPS[self.advance().type]
            value = self.expression()
            self.expect_semicolon()
            return AssignStmt(self.span_from(start), target, op, value)
        self.expect_semicolon()
        return ExprStmt(self.span_from(start), target)

    # ------------------------------------------------------------------
    # Expressions (one routine per precedence level, loosest first)
    # ------------------------------------------------------------------

    def expression(self) -> Expr:
        return self.logic_or()

    def logic_or(self) -> Expr:
        return self._binary(0)

    def logic_and(self) -> Expr:
        return self._binary(1)

    def equality(self) -> Expr:
        return self._binary(2)

    def comparison(self) -> Expr:
        return self._binary(3)

    def term(self) -> Expr:
        return self._binary(4)

    def factor(self) -> Expr:
        return self._binary(5)

    def _binary(self, level: int) -> Expr:
        if level == len(BINARY_LEVELS):
            return self.cast()
        operators = BINARY_LEVELS[level]
        start = self.peek().start()
        left = self._binary(level + 1)
        while self.peek().type in operators:
            op = operators[self.advance().type]
            right = self._binary(level + 1)
            left = BinaryExpr(self.span_from(start), left, op, right)
        return left

    def cast(self) -> Expr:
        start = self.peek().start()
        expr = self.unary()
        while self.match(T.AS):
            type_ = self.type_()
            if type_ is None:
                expr = ErrorNode(self.span_from(start))
            else:
                expr = CastExpr(self.span_from(start), expr, type_)
        return expr

    def unary(self) -> Expr:
        if self.at(T.BANG, T.MINUS, T.AMP):
            start = self.peek().start()
            op = UNARY_OPS[self.advance().type]
            value = self.unary()
            return UnaryExpr(self.span_from(start), op, value)
        return self.postfix()

    def postfix(self) -> Expr:
        start = self.peek().start()
        expr = self.primary()
        while True:
            if self.at(T.LPAREN):
                args = self.arguments()
                expr = CallExpr(self.span_from(start), expr, args)
            elif self.match(T.LBRACKET):
                expr = self.index(start, expr)
            elif self.match(T.DOT):
                if self.at(T.IDENT):
                    name = self.advance().lexeme
                    expr = FieldExpr(self.span_from(start), expr, name)
                else:
                    self.report_missing(E_IDENT, "a field name")
                    expr = ErrorNode(self.span_from(start))
            elif self.match(T.CARET):
                expr = DereferenceExpr(self.span_from(start), expr)
            else:
                return expr

    def index(self, start: Pos, target: Expr) -> Expr:
        """After '[': expression "]" | [expression] ".." [expression] "]"."""
        low = None
        if not self.at(T.DOT_DOT):
            low = self.expression()
        if self.match(T.DOT_DOT):
            high = self.expression() if self.at(*EXPR_START) else None
            self.expect(T.RBRACKET, "']'")
            return SliceExpr(self.span_from(start), target, low, high)
        self.expect(T.RBRACKET, "']'")
        return IndexExpr(self.span_from(start), target, low)

    def arguments(self) -> list[Expr]:
        self.advance()  # (
        args: list[Expr] = []
        while not self.at(T.RPAREN, T.EOF):
            args.append(self.expression())
            if not self.match(T.COMMA):
                break
        self.expect(T.RPAREN, "')'")
        return args

    def primary(self) -> Expr:
        token = self.peek()
        token_type = token.type
        if token_type == T.IDENT:
            self.advance()
            return Identifier(token.span(), token.lexeme)
        if token_type == T.INTEGER:
            self.advance()
            return Int(token.span(), token.val)
        if token_type == T.FLOAT:
            self.advance()
            return Float(token.span(), token.val)
        if token_type == T.CHAR:
            self.advance()
            return Char(token.span(), token.val)
        if token_type == T.STRING:
            self.advance()
            return String(token.span(), token.val)
        if token_type in (T.TRUE, T.FALSE):
            self.advance()
            return Bool(token.span(), token_type == T.TRUE)
        if token_type == T.LPAREN:
            self.advance()
            inner = self.expression()
            self.expect(T.RPAREN, "')'")
            # The span of a parenthesized expression includes the parentheses.
            inner.span = self.span_from(token.start())
            return inner
        if token_type == T.ERROR:
            self.advance()
            self.report(E_LEXER, f"Invalid token {token.lexeme!r}", token.span())
            return ErrorNode(token.span())

        # Missing expression. Delimiters that belong to the caller are left in
        # place; anything else is skipped up to the next synchronization token.
        start = token.start()
        self.report_missing(E_EXPR, "an expression")
        if token_type in EXPR_SYNC:
            return ErrorNode(self.missing_span())
        while not self.at(*EXPR_SYNC):
            self.advance()
        return ErrorNode(self.span_from(start))


def parser(tokens: list[Token]) -> tuple[AST, list[ParserError]]:
    """Parse a token list (ending in EOF) into an AST and error list.

    ``Parser(tokens)`` may be used when access to the parser state is needed.
    """
    return Parser(tokens).parse()

__all__ = ["parser", "Parser"]
