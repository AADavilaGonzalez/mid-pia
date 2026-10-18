import argparse
import sys


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mid", add_help=True)

    parser.add_argument("input", type=str, help="Input source file")
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="a.out",
        metavar="TEXT",
        help="Output file name (default: a.out)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Dumps output to stdout, overrides --output flag"
    )

    phase_group = parser.add_mutually_exclusive_group()
    phase_group.add_argument(
        "-l", "--lex",
        action="store_true",
        help="Stop after lexing phase, output Token Stream as json file",
    )
    phase_group.add_argument(
        "-p", "--parse",
        action="store_true",
        help="Stop after parsing phase, output AST as json file",
    )
    phase_group.add_argument(
        "-a", "--analyze",
        action="store_true",
        help="Stop after analysis phase, output Annotated AST as json file",
    )
    phase_group.add_argument(
        "-i", "--ir",
        action="store_true",
        help="Stop after IR codegen phase, output LLVM IR file",
    )
    phase_group.add_argument(
        "-c", "--obj",
        action="store_true",
        help="Stop after object codegen phase, ouput object file",
    )
    return parser


if __name__ == "__main__":
    from pprint import pformat

    from mid.backend import codegen
    from mid.frontend import analyzer, lexer, parser

    args = create_parser().parse_args()
    def read() -> str:
        try:
            with open(args.input, "r") as input_file:
                source = input_file.read()
        except FileNotFoundError as error:
            print(f"Error: File '{error.filename}' does not exist")
            sys.exit(1)
        except PermissionError as error:
            print(f"Error: User lacks read permision for file '{error.filename}'")
            sys.exit(1)
        except RuntimeError as e:
            print(f"Error: Unexpected error while trying to read file '{args.input}'")
            print("...")
            print(e)
            sys.exit(1)
        return source
    def write(content: str):
        try:
            with open(args.output, "r") as output_file:
                output_file.write(content)
        except PermissionError as error:
            print(f"Error: User lacks write permision for file '{error.filename}'")
            sys.exit(1)
        except RuntimeError as e:
            print(f"Error: Unexpected error while trying to write to file '{args.input}'")
            print("...")
            print(e)
            sys.exit(1)
    def attempt_exit(obj, flag: bool, fmt):
        if flag:
            output = fmt(obj)
            if args.stdout: print(output)
            else: write(output)
            sys.exit(0)

    source = read()

    tokens = lexer(source)
    attempt_exit(tokens, args.lex, pformat)

    ast = parser(tokens)
    attempt_exit(ast, args.parse, pformat)

    ast, st = analyzer(ast)
    attempt_exit(ast, args.analyze, pformat)

    mod = codegen(ast, st)
    attempt_exit(mod, args.ir, str)

    raise NotImplementedError
