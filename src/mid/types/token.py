from enum import Enum, auto
from dataclasses import dataclass
from copy import copy

from mid.types.util import Pos, Span

class TokenType(Enum):
    LPAREN = auto()    
    RPAREN = auto()   
    LBRACE = auto()   
    RBRACE = auto()   
    LBRACKET = auto()   
    RBRACKET = auto() 
    COMMA = auto() 
    SEMICOLON = auto()    
    CARET = auto()
    COLON = auto()          
    COLON_EQUAL = auto()    
    PLUS = auto()
    PLUS_EQUAL = auto()     
    MINUS = auto()
    MINUS_EQUAL = auto()    
    ARROW = auto()
    STAR = auto()    
    STAR_EQUAL = auto()     
    SLASH = auto()
    SLASH_EQUAL = auto()    
    PERCENT = auto()      
    PERCENT_EQUAL = auto()  
    GREATER = auto()
    GREATER_EQUAL = auto()  
    LESSER = auto()
    LESSER_EQUAL = auto()   
    BANG = auto()
    BANG_EQUAL = auto()     
    AMP = auto()
    AMPAMP = auto()      
    BARBAR = auto()   
    EQUAL = auto()   
    EQUAL_EQUAL =  auto()
    DOT = auto() 
    DOTDOT = auto()      
    FUNCTION = auto()   
    AS = auto() 
    RETURN = auto()       
    LOOP = auto()   
    BREAK = auto()     
    CONTINUE = auto()
    IF = auto() 
    ELSE = auto()       
    TRUE = auto()     
    FALSE = auto()     
    INTEGER = auto()    
    FLOAT = auto()
    CHAR = auto()
    STRING = auto()
    IDENT = auto()
    ERROR = auto()    
    EOF = auto()    

@dataclass
class Token:
    lexeme: str
    type: TokenType
    pos: Pos

    def start(self) -> Pos:
        return copy(self.pos)

    def end(self) -> Pos:
        pos = copy(self.pos)
        pos.idx += len(self.lexeme)
        pos.line += len(self.lexeme)
        return pos

    def span(self) -> Span:
        return Span(self.start(), self.end())
