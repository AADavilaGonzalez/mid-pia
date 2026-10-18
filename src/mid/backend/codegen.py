from llvmlite import ir

from mid.types.ast import AST
from mid.types.symbol_table import SymbolTable


def codegen(ast: AST, st: SymbolTable) -> ir.Module:
    raise NotImplementedError
