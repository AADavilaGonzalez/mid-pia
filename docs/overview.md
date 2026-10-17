# Mid Lang
Another mid low level language

## Primitive Types
- u8                : 8bit unsigned integer
- bool              : 8bit unsigned integer with semantic value between 0 and 1
- i32               : 32bit signed integer
- u32               : 32bit unsigned integer
- f32               : 32bit single precision floating point
- usize             : word size unsigned integer

## Qualified Types
- ^pointer          : a word sized address
- [INT]array        : a stack allocated storage, decays to pointer
- []slice           : a builtin generic struct holding a ptr and length

## Builtin Functions
- fn read(buff: ^byte, capacity: usize) -> usize;
    * buff: address to the start of byte buffer to be writen to
    * capacity: maximum amount of bytes to read from stdin
    * RETURNS total amount of bytes read from stdin
- fn write(buff: ^byte, len: usize);
    * buff: address to the start of the buffer to be read from
    * len: total bytes from buff to write to stdout
