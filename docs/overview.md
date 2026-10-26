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
- \[INT\]array        : a stack allocated storage, decays to pointer
- \[\]slice           : a builtin generic struct holding a ptr and length
