# Standard library specification
The mid standard library's purpose is to provide a limited subset of basic functionality
needed to create primitive programs. All of the names declared in the standard library
are available under all scopes (have global scope) and cannot be reassigned.

## Basic IO
The IO functions assume no runtime errors for simplicity.

### eof
`fn eof() -> bool`
  Returns:
  * boolean representing whether EOF (End-Of-File) has been reached on stdin.

### getline
`fn getline(buff: []u8, read_full_line: ^bool) -> []u8`
  Provides line buffered input from stdin.
  Copies line input directly from stdin into a buffer excluding the terminating
  newline character and sets `read_full_line` flag to true. If the buffer cannot hold
  the entire line, `read_full_line` is set to false and the rest of the line is left
  unprocessed inside the input stream.
  
  Parameters:
  * buff: slice spanning the buffer where input is allowed to be copied to.
  * read_full_line: valid pointer to storage location for the boolean flag.

  Returns:
  * A length-adjusted slice spanning the segment of `buff` holding the input read.
  * If EOF is reached while reading, available bytes up to EOF are returned.

### read
`fn read(buff: []u8) -> []u8`
  Attempts to fill the passed-in slice with input from stdin. 

  Returns:
  * A length-adjusted slice spanning the segment of `buff` holding the input.
  * If the length of the returned slice is less than the length of `buff`, EOF has been reached.

### write
`fn write(buff: []u8)`
  Provides output to stdout. Writes all bytes contained within `buff`.

  Parameters:
  * buff: slice spanning the raw data to be written to stdout.
