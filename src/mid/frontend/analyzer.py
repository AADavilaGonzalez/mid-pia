from mid.types.ast import AST
from mid.types.errors import AnalyzerError
from mid.types.symbol_table import SymbolTable


def analyzer(ast: AST) -> tuple[AST, SymbolTable, list[AnalyzerError]]:
    raise NotImplementedError
