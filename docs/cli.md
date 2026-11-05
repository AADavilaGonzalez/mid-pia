# Command Line Inteface Specification for Mid Compiler

## Positionals:
  input TEXT REQUIRED           Input source file

## Flags:
  -h,     --help                Print this help message and exit
  -o,     --output TEXT [a.out] Output file name
          --stdout              Dumps output to stdout, overrides --output flag

  -l,     --lex                 Stop after lexing phase, output Token Stream as json file
  -p,     --parse               Stop after parsing phase, output AST as json file
  -a,     --analyze             Stop after analysis phase, output Annotated AST as json file
  -i,     --ir                  Stop after IR codegen phase, output LLVM IR file
  -c,     --obj                 Stop after object codegen phase, ouput object file
