; ModuleID = "main"
target triple = "unknown-unknown-unknown"
target datalayout = ""

declare void @"__builtin_print_i32"(i32 %".1")

define i32 @"main"()
{
entry:
  %"x" = alloca i32
  %"y" = alloca i32
  store i32 10, ptr %"x"
  store i32 20, ptr %"y"
  %".4" = load i32, ptr %"x"
  %".5" = load i32, ptr %"y"
  %".6" = add i32 %".4", %".5"
  store i32 %".6", ptr %"x"
  %".8" = load i32, ptr %"x"
  call void @"__builtin_print_i32"(i32 %".8")
  ret i32 0
}
