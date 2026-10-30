import argparse
import sys

from mid import lex, parse, analyze, generate_ir
from mid.types.errors import Error

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mid Compiler")
    parser.add_argument("input", type=str, help="Input source file")
    parser.add_argument("-o", "--output",
        default="a.out",
        help="Output file name (default: a.out)",
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

    module = generate_ir(ast)
    with open(args.output, "w") as f:
        f.write(module)
    sys.exit(0)
