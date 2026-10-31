import argparse
import sys
import tempfile
import subprocess

from mid import lex, parse, analyze, generate_ir
from mid.types.errors import Error
from mid.util import LIB_FILE

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mid Compiler")
    parser.add_argument("input", type=str, help="Input source file")
    parser.add_argument("-o", "--output",
        default="a.out",
        help="Output file name (default: a.out)",
    )
    parser.add_argument("-ir",
        action="store_true",
        help="Emit llvm-ir instead of executable"
    )
    return parser.parse_args()

def main():
    args = parse_args()
    with open(args.input, "r") as f:
        source = f.read()
    errors: list[Error] = []

    tokens, lexer_errors = lex(source)
    errors.extend(lexer_errors)

    ast, parser_errors = parse(tokens)
    errors.extend(parser_errors)

    ast, analyzer_errors = analyze(ast)
    errors.extend(analyzer_errors)

    if errors:
        for error in errors:
            print(error)
        sys.exit(1)

    ir = generate_ir(ast)
    if args.ir:
        with open(args.output, "w") as f:
            f.write(ir)
    else:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ll") as tmp:
            tmp.write(ir)
            tmp.flush()
            subprocess.run(
                ["clang", tmp.name, str(LIB_FILE), "-o", args.output],
                check=False)
    sys.exit(0)
