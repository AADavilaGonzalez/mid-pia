"""Symbol table with nested scopes (docs/stages/semantics.md).

All names (variables, parameters, functions, standard-library functions and
type names) share one namespace, and shadowing is forbidden: a name cannot be
defined if it is already visible from the current scope.
"""

from dataclasses import dataclass, field
from enum import Enum, auto

from mid.types.sem_type import BOOL, PRIMITIVE_TYPES, U8, VOID, SemType
from mid.types.util import Span


class SymbolKind(Enum):
    VARIABLE = auto()
    PARAMETER = auto()
    FUNCTION = auto()
    BUILTIN_FUNCTION = auto()
    TYPE = auto()


@dataclass(eq=False)
class Symbol:
    name: str
    kind: SymbolKind
    # Variable/parameter type, or the type a TYPE symbol names. For a global
    # declared with ':=' it is None until its initializer has been analyzed.
    type: SemType | None = None
    # Functions only.
    parameters: list[SemType] | None = None
    return_type: SemType | None = None  # VOID for functions without '-> type'
    span: Span | None = None  # None for built-in symbols
    mutable: bool = False
    is_global: bool = False

    @property
    def is_function(self) -> bool:
        return self.kind in (SymbolKind.FUNCTION, SymbolKind.BUILTIN_FUNCTION)

    def describe(self) -> str:
        return {
            SymbolKind.VARIABLE: "variable",
            SymbolKind.PARAMETER: "parameter",
            SymbolKind.FUNCTION: "function",
            SymbolKind.BUILTIN_FUNCTION: "standard-library function",
            SymbolKind.TYPE: "type",
        }[self.kind]


class ScopeKind(Enum):
    GLOBAL = auto()
    FUNCTION = auto()
    BLOCK = auto()


@dataclass(eq=False)
class Scope:
    kind: ScopeKind
    parent: Scope | None = field(default=None, repr=False)
    symbols: dict[str, Symbol] = field(default_factory=dict)
    children: list[Scope] = field(default_factory=list, repr=False)

    def lookup_local(self, name: str) -> Symbol | None:
        return self.symbols.get(name)

    def lookup(self, name: str) -> Symbol | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.symbols:
                return scope.symbols[name]
            scope = scope.parent
        return None


BUILTIN_FUNCTIONS = [
    # name, parameter types, return type
    ("eof", [], BOOL),
    ("getline", [U8.slice(), BOOL.pointer()], U8.slice()),
    ("read", [U8.slice()], U8.slice()),
    ("write", [U8.slice()], VOID),
]


class SymbolTable:
    def __init__(self, builtins: bool = True):
        self.global_scope = Scope(ScopeKind.GLOBAL)
        self.current_scope = self.global_scope
        if builtins:
            self._load_builtins()

    def _load_builtins(self):
        for type_ in PRIMITIVE_TYPES:
            self.define(Symbol(type_.name, SymbolKind.TYPE, type=type_))
        for name, params, ret in BUILTIN_FUNCTIONS:
            self.define(Symbol(
                name, SymbolKind.BUILTIN_FUNCTION, parameters=params, return_type=ret,
            ))

    @property
    def in_global_scope(self) -> bool:
        return self.current_scope is self.global_scope

    def enter_scope(self, kind: ScopeKind = ScopeKind.BLOCK) -> Scope:
        scope = Scope(kind, self.current_scope)
        self.current_scope.children.append(scope)
        self.current_scope = scope
        return scope

    def exit_scope(self):
        if self.current_scope.parent is None:
            raise RuntimeError("cannot exit the global scope")
        self.current_scope = self.current_scope.parent

    def lookup(self, name: str) -> Symbol | None:
        """Find a name in the current scope or any enclosing scope."""
        return self.current_scope.lookup(name)

    def define(self, symbol: Symbol) -> Symbol | None:
        """Add ``symbol`` to the current scope.

        If the name is already visible (in this scope or an enclosing one) the
        symbol is not added and the existing symbol is returned, so the caller
        can report a duplicate declaration or forbidden shadowing. Returns None
        on success.
        """
        existing = self.lookup(symbol.name)
        if existing is not None:
            return existing
        symbol.is_global = self.in_global_scope
        self.current_scope.symbols[symbol.name] = symbol
        return None


__all__ = ["SymbolKind", "Symbol", "ScopeKind", "Scope", "SymbolTable", "BUILTIN_FUNCTIONS"]
