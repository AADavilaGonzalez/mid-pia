"""In-process MCJIT execution engine and standard-library runtime stubs for Mid."""

import ctypes
import sys
from typing import BinaryIO

import llvmlite.binding as llvm
from llvmlite import ir

# Initialize LLVM targets
llvm.initialize_native_target()
llvm.initialize_native_asmprinter()

WRITE_CFUNC = ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_uint8), ctypes.c_int64)
READ_CFUNC = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.POINTER(ctypes.c_uint8), ctypes.c_int64)
GETLINE_CFUNC = ctypes.CFUNCTYPE(
    ctypes.c_int64,
    ctypes.POINTER(ctypes.c_uint8),
    ctypes.c_int64,
    ctypes.POINTER(ctypes.c_uint8),
)
EOF_CFUNC = ctypes.CFUNCTYPE(ctypes.c_uint8)


class StreamContext:
    """Manages I/O streams for Mid standard-library functions."""

    def __init__(self, in_stream: BinaryIO, out_stream: BinaryIO):
        self.in_stream = in_stream
        self.out_stream = out_stream
        self._eof = False
        self._peeked_byte: bytes | None = None

    def write(self, data: bytes) -> None:
        if self.out_stream:
            try:
                self.out_stream.write(data)
            except TypeError:
                self.out_stream.write(data.decode("utf-8", errors="replace"))
            if hasattr(self.out_stream, "flush"):
                self.out_stream.flush()

    def read_byte(self) -> bytes:
        if self._peeked_byte is not None:
            b = self._peeked_byte
            self._peeked_byte = None
            return b
        raw = self.in_stream.read(1)
        b = raw.encode("utf-8") if isinstance(raw, str) else raw
        if not b:
            self._eof = True
        return b

    def peek_byte(self) -> bytes:
        if self._peeked_byte is None:
            raw = self.in_stream.read(1)
            self._peeked_byte = raw.encode("utf-8") if isinstance(raw, str) else raw
            if not self._peeked_byte:
                self._eof = True
        return self._peeked_byte

    def is_eof(self) -> bool:
        if self._eof:
            return True
        b = self.peek_byte()
        return not b

    def read(self, length: int) -> bytes:
        chunk = bytearray()
        while len(chunk) < length:
            b = self.read_byte()
            if not b:
                break
            chunk.extend(b)
        return bytes(chunk)

    def getline(self, length: int) -> tuple[bytes, bool]:
        """Reads a line up to newline. Returns (bytes_read, full_line_read)."""
        chunk = bytearray()
        full = False
        while len(chunk) < length:
            b = self.read_byte()
            if not b:
                if len(chunk) > 0:
                    full = True
                break
            if b == b"\n":
                full = True
                break
            if b == b"\r":
                if self.peek_byte() == b"\n":
                    self.read_byte()
                full = True
                break
            chunk.extend(b)
        return bytes(chunk), full


_DEFAULT_CONTEXT: StreamContext | None = None
_CURRENT_CONTEXT: StreamContext | None = None


def get_current_context() -> StreamContext:
    global _DEFAULT_CONTEXT
    if _CURRENT_CONTEXT is not None:
        return _CURRENT_CONTEXT
    if _DEFAULT_CONTEXT is None:
        in_s = getattr(sys.stdin, "buffer", sys.stdin)
        out_s = getattr(sys.stdout, "buffer", sys.stdout)
        _DEFAULT_CONTEXT = StreamContext(in_s, out_s)
    return _DEFAULT_CONTEXT


def set_current_context(ctx: StreamContext | None) -> None:
    global _CURRENT_CONTEXT
    _CURRENT_CONTEXT = ctx


@WRITE_CFUNC
def _c_mid_write(ptr, length):
    if length > 0:
        get_current_context().write(bytes(ptr[:length]))


@READ_CFUNC
def _c_mid_read(ptr, length):
    if length <= 0:
        return 0
    chunk = get_current_context().read(length)
    for i, b in enumerate(chunk):
        ptr[i] = b
    return len(chunk)


@GETLINE_CFUNC
def _c_mid_getline(ptr, length, full_line_ptr):
    if length <= 0:
        full_line_ptr[0] = 0
        return 0
    chunk, full = get_current_context().getline(length)
    for i, b in enumerate(chunk):
        ptr[i] = b
    full_line_ptr[0] = 1 if full else 0
    return len(chunk)


@EOF_CFUNC
def _c_mid_eof():
    return 1 if get_current_context().is_eof() else 0


def bind_runtime_symbols() -> None:
    """Register runtime symbols globally in LLVM engine."""
    llvm.add_symbol("mid_write", ctypes.cast(_c_mid_write, ctypes.c_void_p).value)
    llvm.add_symbol("mid_read", ctypes.cast(_c_mid_read, ctypes.c_void_p).value)
    llvm.add_symbol("mid_getline", ctypes.cast(_c_mid_getline, ctypes.c_void_p).value)
    llvm.add_symbol("mid_eof", ctypes.cast(_c_mid_eof, ctypes.c_void_p).value)


# Initial symbol binding
bind_runtime_symbols()


class JITRunner:
    """Compiles an llvmlite.ir.Module with MCJIT for execution."""

    def __init__(self, module: ir.Module):
        bind_runtime_symbols()
        self.ir_str = str(module)
        self.llvm_mod = llvm.parse_assembly(self.ir_str)
        self.llvm_mod.verify()

        self.target_machine = llvm.Target.from_default_triple().create_target_machine()
        self.llvm_mod.triple = llvm.get_default_triple()
        self.llvm_mod.data_layout = str(self.target_machine.target_data)

        self.engine = llvm.create_mcjit_compiler(self.llvm_mod, self.target_machine)
        self.engine.finalize_object()
        self.engine.run_static_constructors()

    def call(self, name: str, restype, *argtypes_and_args):
        addr = self.engine.get_function_address(name)
        assert addr != 0, f"Function {name!r} not found in JIT module"
        argtypes = [t for t, _ in argtypes_and_args]
        args = [v for _, v in argtypes_and_args]
        fn = ctypes.CFUNCTYPE(restype, *argtypes)(addr)
        return fn(*args)

    def call_main(self) -> int:
        return self.call("main", ctypes.c_int32)

    def get_global(self, name: str, ctype):
        addr = self.engine.get_global_value_address(name)
        assert addr != 0, f"Global {name!r} not found in JIT module"
        return ctype.from_address(addr).value


def run_jit(
    module: ir.Module,
    input_stream: BinaryIO | None = None,
    output_stream: BinaryIO | None = None,
) -> int:
    """Execute module's @main function via MCJIT with configured I/O streams."""
    global _CURRENT_CONTEXT
    in_s = getattr(sys.stdin, "buffer", sys.stdin) if input_stream is None else input_stream
    out_s = getattr(sys.stdout, "buffer", sys.stdout) if output_stream is None else output_stream

    ctx = StreamContext(in_s, out_s)
    prev_ctx = _CURRENT_CONTEXT
    _CURRENT_CONTEXT = ctx
    try:
        bind_runtime_symbols()
        runner = JITRunner(module)
        return runner.call_main()
    finally:
        _CURRENT_CONTEXT = prev_ctx


__all__ = [
    "JITRunner",
    "StreamContext",
    "run_jit",
    "bind_runtime_symbols",
    "get_current_context",
    "set_current_context",
]
