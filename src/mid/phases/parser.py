from mid.types.ast import * # pyright: ignore
from mid.types.errors import ParserError
from mid.types.token import Token, TokenType
from mid.types.util import Span

OP = {
    TokenType.PLUS  : BinaryExpr.Op.ADD,
    TokenType.MINUS : BinaryExpr.Op.SUB,
    TokenType.STAR  : BinaryExpr.Op.MULT,
    TokenType.SLASH : BinaryExpr.Op.DIV
}

def parse(tokens: list[Token]) -> tuple[AST, list[ParserError]]:
    assert len(tokens) >= 1
    assert tokens[-1].type == TokenType.EOF

# Context
    current = 0
    errors: list[ParserError] = []

# API
    def peek(offset: int = 0) -> Token:
        idx = current + offset
        return tokens[idx] if idx < len(tokens) else tokens[-1]

    def advance() -> Token:
        nonlocal current
        token = peek()
        current += 1
        return token

    def is_at_end() -> bool:
        return peek().type == TokenType.EOF

    def match(types: set[TokenType]) -> Token | None:
        if peek().type in types:
            return advance()
        return None

    def expected(msg: str, token: Token) -> ParserError:
        return ParserError(f"Expected {msg}, got '{token.lexeme}'", token.start)

    def eat(type: TokenType) -> Token:
        token = peek()
        if token.type == type:
            return advance()
        raise expected(type.value, token)

    def sync(types: set[TokenType], consume: bool):
        while peek().type not in types: advance()
        if consume: advance()

# Recursive Decent
    def parse_program() -> Program:
        stmts: list[Stmt] = []

        def lookahead():
            token = peek(1)
            match token.type:
                case TokenType.COLON: stmts.append(parse_decl())
                case TokenType.EQUAL: stmts.append(parse_assign())
                case _: raise expected("':' or '='", token)

        while not is_at_end():
            token = peek()
            try:
                match token.type:
                    case TokenType.IDENT: lookahead()
                    case TokenType.PRINT: stmts.append(parse_print())
                    case _: raise expected("'print' or 'identifier'", token)
            except ParserError as e:
                errors.append(e)
                sync({TokenType.SEMICOLON}, consume=True)

        return Program(stmts)

    def parse_decl() -> Decl:
       ident = eat(TokenType.IDENT)
       eat(TokenType.COLON)
       eat(TokenType.TYPE_I32)
       semicolon = eat(TokenType.SEMICOLON)
       span = Span(ident.start, semicolon.end)
       return Decl(ident.lexeme, span)

    def parse_assign() -> Assign:
        ident = eat(TokenType.IDENT)
        eat(TokenType.EQUAL)
        expr = parse_expr()
        semicolon = eat(TokenType.SEMICOLON)
        span = Span(ident.start, semicolon.end)
        return Assign(ident.lexeme, expr, span)

    def parse_print() -> Print:
        print = eat(TokenType.PRINT)
        expr = parse_expr()
        semicolon = eat(TokenType.SEMICOLON)
        span = Span(print.start, semicolon.end)
        return Print(expr, span)

    def parse_expr(): return parse_term()

    def parse_term() -> Expr:
        left = parse_factor()
        while token := match({TokenType.PLUS, TokenType.MINUS}):
            right = parse_factor()
            left = BinaryExpr(left, OP[token.type], right)
        return left

    def parse_factor() -> Expr:
        left = parse_primary()
        while token := match({TokenType.STAR, TokenType.SLASH}):
            right = parse_primary()
            left = BinaryExpr(left, OP[token.type], right)
        return left

    def parse_primary() -> Expr:
        token = advance()
        match token.type:
            case TokenType.IDENT:
                expr = Ident(token.lexeme, token.span)
            case TokenType.NUMBER:
                expr = Number(int(token.lexeme), token.span)
            case TokenType.LPAREN:
                expr = parse_expr()
                eat(TokenType.RPAREN)
            case _:
                raise expected("an identifier or a number", token)
        return expr

    return AST(parse_program()), errors
