"""Semantic types used by the analyzer and the code generator.

A ``SemType`` is a type without source information: a base type name plus its
qualifiers, outermost first (the same order as ``ast.Type.qual``). For example
``^[3]u8`` is ``SemType("u8", (Pointer(), Array(3)))``.

Unlike ``ast.Type`` nodes, ``SemType`` values compare by structure only (no
spans) and are hashable, so they can be used as dictionary keys.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Pointer:
    def __str__(self) -> str:
        return "^"


@dataclass(frozen=True)
class Array:
    size: int

    def __str__(self) -> str:
        return f"[{self.size}]"


@dataclass(frozen=True)
class Slice:
    def __str__(self) -> str:
        return "[]"


Qualifier = Pointer | Array | Slice


@dataclass(frozen=True)
class SemType:
    name: str
    qual: tuple[Qualifier, ...] = ()

    def __str__(self) -> str:
        return "".join(str(q) for q in self.qual) + self.name

    def __repr__(self) -> str:
        return f"SemType({str(self)!r})"

    # --- classification ------------------------------------------------

    @property
    def is_integer(self) -> bool:
        return self in INTEGER_TYPES

    @property
    def is_numeric(self) -> bool:
        return self in NUMERIC_TYPES

    @property
    def is_pointer(self) -> bool:
        return bool(self.qual) and isinstance(self.qual[0], Pointer)

    @property
    def is_array(self) -> bool:
        return bool(self.qual) and isinstance(self.qual[0], Array)

    @property
    def is_slice(self) -> bool:
        return bool(self.qual) and isinstance(self.qual[0], Slice)

    # --- construction --------------------------------------------------

    def inner(self) -> SemType:
        """Pointee of a pointer, or element type of an array or slice."""
        return SemType(self.name, self.qual[1:])

    def pointer(self) -> SemType:
        """``^self``"""
        return SemType(self.name, (Pointer(),) + self.qual)

    def slice(self) -> SemType:
        """``[]self``"""
        return SemType(self.name, (Slice(),) + self.qual)


U8 = SemType("u8")
BOOL = SemType("bool")
I32 = SemType("i32")
U32 = SemType("u32")
F32 = SemType("f32")
USIZE = SemType("usize")

# Return type of functions declared without ``-> type``.
VOID = SemType("void")
# Type of expressions whose analysis already failed. It is compatible with
# everything so one error does not cascade into more errors.
ERROR = SemType("<error>")

PRIMITIVE_TYPES = (U8, BOOL, I32, U32, F32, USIZE)
INTEGER_TYPES = frozenset({U8, I32, U32, USIZE})
NUMERIC_TYPES = INTEGER_TYPES | {F32}

# Values an integer literal may take for each integer type.
INTEGER_RANGES = {
    U8: (0, 2**8 - 1),
    I32: (-(2**31), 2**31 - 1),
    U32: (0, 2**32 - 1),
    USIZE: (0, 2**64 - 1),
}

__all__ = [
    "Pointer", "Array", "Slice", "Qualifier", "SemType",
    "U8", "BOOL", "I32", "U32", "F32", "USIZE", "VOID", "ERROR",
    "PRIMITIVE_TYPES", "INTEGER_TYPES", "NUMERIC_TYPES", "INTEGER_RANGES",
]
