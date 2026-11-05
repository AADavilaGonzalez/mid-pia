## Semana 4: Análisis semántico {#semana-4:-análisis-semántico}

En esta etapa construimos el analizador semántico. El analizador recibe el AST que produce el parser y revisa que el programa tenga sentido, no solo que esté bien escrito. Por ejemplo, x := y + 1; es correcto para el parser, pero es un error si y no está declarada. El analizador entrega tres cosas: el mismo AST con anotaciones de tipos y símbolos, la tabla de símbolos y la lista de errores que encontró. El código está en src/mid/frontend/analyzer.py.

El analizador recorre el programa en cuatro pasadas. Primero registra todas las funciones y variables globales. Después revisa los valores iniciales de las variables globales, en el orden en que aparecen. Luego comprueba que exista la función main. Por último revisa el cuerpo de cada función. Gracias a la primera pasada, una función puede llamar a otra que esté definida más abajo en el archivo.

### Implementación de la tabla de símbolos {#implementación-de-la-tabla-de-símbolos}

La tabla de símbolos guarda cada nombre declarado en el programa junto con la información necesaria para usarlo. Está en src/mid/types/symbol_table.py y se compone de tres clases. Symbol es una entrada de la tabla. Scope es un ámbito: guarda un diccionario de nombres a símbolos, su scope padre y sus scopes hijos. SymbolTable administra la jerarquía de scopes.

La siguiente tabla muestra los campos de cada símbolo.

| Campo | Qué guarda |
| :---- | :---- |
| name | El nombre |
| kind | Si es variable, parámetro, función, función de la biblioteca estándar o tipo |
| type | El tipo de la variable o del parámetro |
| parameters | Los tipos de los parámetros, solo en funciones |
| return_type | El tipo de retorno, solo en funciones. Es void si la función no regresa valor |
| span | La posición de la declaración en el código fuente |
| mutable | Si se le puede asignar un valor |
| is_global | Si se declaró en el scope global |

SymbolTable tiene cuatro operaciones. define agrega un símbolo al scope actual. Si el nombre ya es visible, no lo agrega y devuelve el símbolo que ya existía, para que el analizador pueda reportar el error. lookup busca un nombre en el scope actual y, si no lo encuentra, sigue con los scopes padre hasta llegar al global. enter_scope crea un scope hijo y entra en él, y exit_scope regresa al scope padre.

Al crearse, la tabla ya contiene los seis tipos primitivos y las cuatro funciones de la biblioteca estándar.

| Símbolo | Clase | Firma |
| :---- | :---- | :---- |
| u8, bool, i32, u32, f32, usize | Tipo | No aplica |
| eof | Función estándar | eof() -> bool |
| getline | Función estándar | getline([]u8, ^bool) -> []u8 |
| read | Función estándar | read([]u8) -> []u8 |
| write | Función estándar | write([]u8) |

Registramos los tipos como símbolos para que todos los nombres compartan un mismo espacio. Así, declaraciones como u8 := 1; o write := 0; se rechazan con la misma regla que cualquier nombre repetido.

Para representar los tipos creamos la clase SemType, en src/mid/types/sem_type.py. El parser ya representa los tipos con nodos Type, pero esos nodos guardan su posición en el código, y por eso dos i32 escritos en líneas distintas no resultan iguales al compararlos. SemType guarda solo el nombre base y la lista de calificadores, como se ve en la siguiente tabla.

| Tipo en Mid | SemType |
| :---- | :---- |
| i32 | SemType("i32", ()) |
| ^u8 | SemType("u8", (Pointer(),)) |
| [3]^bool | SemType("bool", (Array(3), Pointer())) |
| []u8 | SemType("u8", (Slice(),)) |

Dos SemType son iguales cuando tienen el mismo nombre y los mismos calificadores en el mismo orden. Además no se pueden modificar y se pueden usar como llaves de un diccionario, cosa que aprovecha la generación de código.

### Manejo de alcance y visibilidad {#manejo-de-alcance-y-visibilidad}

Hay tres niveles de scope. El scope global tiene los tipos, la biblioteca estándar, las funciones y las variables globales. Cada función tiene su propio scope, con sus parámetros y las variables declaradas directamente en su cuerpo. Cada bloque anidado, como el cuerpo de un if, de un else o de un loop, tiene un scope de bloque.

Veamos un ejemplo:

limite: u32 = 10;

fn main() {

x := limite + 5;

if x > 12 {

y: u8 = 1;

}

}

La tabla de símbolos queda así. No incluimos los símbolos de la biblioteca estándar.

| Scope | Dentro de | Símbolos |
| :---- | :---- | :---- |
| Global | Ninguno | limite (variable u32), main (función) |
| Función main | Global | x (variable u32) |
| Bloque del if | Función main | y (variable u8) |

Desde el bloque del if se ven y, x y limite. Desde el cuerpo de main no se ve y, porque se declaró en un scope hijo que ya terminó.

El lenguaje no permite shadowing. Un nombre no se puede declarar si ya es visible desde el scope actual, aunque esté en un scope exterior. La regla aplica a variables, parámetros, funciones, funciones estándar y tipos. Así, cada nombre visible se refiere a una sola cosa y el código no se presta a confusiones. Dos bloques hermanos sí pueden usar el mismo nombre, porque ninguno ve al otro. La siguiente tabla muestra las reglas con ejemplos.

| Regla | Ejemplo | Resultado |
| :---- | :---- | :---- |
| No hay shadowing | i := 0; if c { i := 1; } | Error: i ya es visible |
| Los bloques hermanos no se ven | if c { i := 1; } else { i := 2; } | Válido |
| Una variable local se ve después de declararla | y := x; x := 1; | Error: x todavía no existe |
| El valor inicial se revisa antes de registrar la variable | x := x + 1; | Error: x todavía no existe |
| Las globales se predeclaran | fn main() { g = 1; } g: i32; | Válido |
| Una global con := tiene tipo hasta que se revisa su valor inicial | a := b; b := 1; | Error: el tipo de b todavía no se conoce |
| Una global con tipo explícito se puede usar antes | a: i32 = b; b: i32 = 1; | Válido |

Predeclarar las funciones y las globales permite escribir el programa en cualquier orden, sin prototipos.

### Verificación de tipos {#verificación-de-tipos}

El analizador calcula el tipo de cada expresión de forma recursiva y lo compara con el tipo que espera el lugar donde aparece. Los tipos enteros son u8, i32, u32 y usize. Los numéricos son los enteros y f32, y bool no cuenta como numérico. Los tipos compuestos son el puntero ^T, el arreglo [N]T, que debe tener N mayor que cero, y el slice []T. Si el nombre de un tipo no existe, como byte, el analizador reporta un error.

No hay conversiones implícitas. Las asignaciones, los valores iniciales, los argumentos y los valores de retorno deben tener exactamente el tipo esperado. Si a es u8 y b es i32, a = b; y a + b son errores, y hay que escribir b as u8. Tampoco se convierte un arreglo en slice por sí solo; para eso se escribe arr[..].

La única excepción son los literales numéricos, que no tienen un ancho fijo y toman el tipo que espera su contexto. En i: usize = 0; el 0 es usize. Si el contexto no espera un entero, como en x := 5;, el literal es i32. El contexto puede ser el tipo declarado de la variable, el destino de una asignación, el parámetro de una función, el tipo de retorno o el otro operando de una operación. Sin esta regla, casi cualquier programa necesitaría escribir cosas como i: usize = 0 as usize;. El valor del literal debe caber en su tipo:

| Tipo | Rango |
| :---- | :---- |
| u8 | 0 a 255 |
| i32 | -2,147,483,648 a 2,147,483,647 |
| u32 | 0 a 4,294,967,295 |
| usize | 0 a 18,446,744,073,709,551,615 |

Un - escrito directamente antes de un literal forma un literal negativo. Por eso -2147483648 es un i32 válido y x: u32 = -1; es un error. Los literales enteros nunca se convierten en f32 ni en bool.

La siguiente tabla muestra qué aceptan los operadores y qué tipo producen.

| Operador | Operandos | Resultado |
| :---- | :---- | :---- |
| ! | bool | bool |
| - (prefijo) | i32 o f32 | El mismo tipo |
| & | Una expresión que tenga dirección | ^T |
| ^ (sufijo) | ^T | T |
| && \|\| | Dos bool | bool |
| + - * / | Dos numéricos del mismo tipo | Ese tipo |
| % | Dos enteros del mismo tipo | Ese tipo |
| > < >= <= | Dos numéricos del mismo tipo | bool |
| == != | Dos numéricos del mismo tipo, o dos bool | bool |

No se permite hacer aritmética ni comparaciones con punteros, arreglos o slices.

Las conversiones explícitas se escriben con as. La siguiente tabla dice cuáles se permiten. Las filas son el tipo de origen y las columnas el tipo de destino.

| De \ A | u8 | i32 | u32 | usize | f32 | bool |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| u8 | Sí | Sí | Sí | Sí | Sí | Sí |
| i32 | Sí | Sí | Sí | Sí | Sí | Sí |
| u32 | Sí | Sí | Sí | Sí | Sí | Sí |
| usize | Sí | Sí | Sí | Sí | Sí | Sí |
| f32 | Sí | Sí | Sí | Sí | Sí | No |
| bool | Sí | Sí | Sí | Sí | No | Sí |

Entre punteros solo se permite convertir cualquier ^T a ^u8 y ^u8 a cualquier ^T. No se permiten conversiones entre punteros y enteros, ni conversiones con arreglos o slices. La siguiente tabla muestra qué hace cada conversión.

| Conversión | Qué hace |
| :---- | :---- |
| Entero a entero más pequeño | Se queda con los bits bajos: 300 as u8 es 44 |
| Entero a entero más grande | Rellena con ceros si el origen no tiene signo, o con el signo si es i32 |
| Entre i32 y u32 | Conserva los bits: -1 as u32 es 4294967295 |
| Entero a f32 | Da el f32 más cercano |
| f32 a entero | Quita los decimales |
| bool a entero | Da 0 o 1 |
| Entero a bool | Da x != 0, así que 2 as bool es true |

Para los arreglos y slices, a[i] requiere que a sea arreglo o slice y que i sea de cualquier tipo entero, y el resultado es el tipo de los elementos. a[x..y] produce un slice, y sus límites son opcionales pero deben ser enteros. El único campo del lenguaje es .len. Es de tipo usize, solo se puede leer y existe en arreglos y slices. En un arreglo su valor se conoce al compilar, y en un slice se lee al ejecutar.

En las llamadas, solo se puede llamar a una función por su nombre. El número de argumentos debe ser igual al de parámetros, y cada argumento debe tener el tipo exacto del parámetro. Una función sin tipo de retorno solo se puede llamar como sentencia; usar su resultado como valor es un error. En las asignaciones, solo se puede asignar a variables, parámetros, elementos de arreglos o slices (a[i]) y valores apuntados (p^). No se puede asignar a literales, a funciones ni a .len.

### Detección de errores semánticos {#detección-de-errores-semánticos}

El analizador maneja los errores igual que el lexer y el parser. No se detiene en el primer error: guarda cada uno en una lista y sigue revisando, así que una sola corrida puede reportar varios. Cada error es un objeto AnalyzerError con un código, la posición en el código fuente y un mensaje. El analizador no imprime nada. El programa principal junta los errores de las tres etapas y los imprime con el formato AnalyzerError(código) [line:L, col:C]: mensaje. Estos son los códigos:

| Código | Cuándo ocurre |
| :---- | :---- |
| 1 | Un nombre no está declarado o se usa antes de su declaración |
| 2 | Un nombre se declara dos veces o hace shadowing |
| 3 | El tipo no existe o es inválido, como un arreglo de tamaño 0 |
| 4 | Los tipos no coinciden o un literal no cabe en su tipo |
| 5 | Un operador recibe operandos que no acepta |
| 6 | Se asigna a algo que no se puede asignar, como un literal o una función |
| 7 | Una llamada a función es inválida o sus argumentos no coinciden |
| 8 | La conversión con as no está permitida |
| 9 | Un índice, slice, campo, puntero o desreferencia es inválido |
| 10 | Hay un break, continue o return inválido, o falta un return |
| 11 | Falta la función main o su firma es incorrecta |

Un error no debe provocar otros errores en cascada. Para lograrlo, una expresión con error recibe un tipo interno llamado ERROR, que es compatible con cualquier otro tipo. Por ejemplo, si x se declaró con un nombre que no existe, las líneas que usan x después no reportan nada más. Los ErrorNode que deja el parser se tratan igual, así que un error de sintaxis tampoco produce errores semánticos de más.

Veamos un ejemplo con varios errores en el mismo programa:

fn promedio(a: i32, b: i32) -> i32 {

if a > b {

return (a + b) / 2;

}

}

fn main() {

total: u8 = 300;

n: i32 = 4;

total = n;

r := promedio(n);

if n { break; }

valor := desconocido + 1;

}

El analizador reporta lo siguiente:

AnalyzerError(10) [line:1, col:1]: Function 'promedio' must return a value of type 'i32' on every path

AnalyzerError(4) [line:8, col:17]: Integer literal 300 does not fit in type 'u8'

AnalyzerError(4) [line:10, col:13]: Expected 'u8' but found 'i32' in the assignment

AnalyzerError(7) [line:11, col:10]: Function 'promedio' expects 2 argument(s) but 1 were given

AnalyzerError(4) [line:12, col:8]: Condition must be 'bool', found 'i32'

AnalyzerError(10) [line:12, col:12]: 'break' outside of a loop

AnalyzerError(1) [line:13, col:14]: Name 'desconocido' is not declared

El primer error es que promedio no regresa nada cuando a no es mayor que b. Después, 300 no cabe en un u8, y n es i32, así que no se puede guardar en total, que es u8. promedio recibe un solo argumento cuando espera dos. La condición del if es un entero en lugar de un bool, el break está fuera de un ciclo y desconocido no está declarada.

### Anotación del AST {#anotación-del-ast}

El analizador no construye un árbol nuevo. Agrega información al mismo AST que recibe, usando los campos ty y symbol que tiene cada nodo. El parser deja estos campos vacíos y el analizador los llena como se ve en la siguiente tabla.

| Campo | En qué nodos | Qué guarda |
| :---- | :---- | :---- |
| ty | Cada expresión | Su tipo |
| ty | VarDecl y Param | El tipo de la variable, también cuando se declaró con := |
| ty | Type | El tipo ya resuelto |
| symbol | Identifier | El símbolo al que se refiere el nombre |
| symbol | VarDecl, Param y FnDecl | El símbolo que declaran |

Tomemos la línea x := limite + 5; del ejemplo de la sección de alcance. El parser produce este AST, simplificado y escrito como en la Semana 3:

VarDecl(name='x'): init = BinaryExpr(op=ADD)

BinaryExpr(op=ADD): left = Identifier(name='limite'), right = Int(val=5)

Después del análisis, el mismo AST queda así:

VarDecl(name='x', ty=u32): init = BinaryExpr(op=ADD, ty=u32)

BinaryExpr(op=ADD, ty=u32): left = Identifier(name='limite', ty=u32, symbol=limite), right = Int(val=5, ty=u32)

El literal 5 quedó como u32 porque el otro operando de la suma es u32, y por eso x también es u32. El campo symbol de limite apunta al símbolo de la variable global.

La generación de código usa estas anotaciones. El campo ty le indica qué instrucción emitir, por ejemplo una suma entera o una de punto flotante, con signo o sin signo. El campo symbol le indica en qué variable se lee o se guarda cada valor. Como dos bloques hermanos pueden usar el mismo nombre, el generador identifica cada variable por su símbolo y no por su nombre.

Los campos ty y symbol se agregaron sin cambiar la forma de construir los nodos y no cuentan al comparar dos nodos, así que el parser y sus pruebas siguieron funcionando igual. El AST anotado se puede ver con el comando mid programa.mid -a --stdout.

### Validación del significado del programa {#validación-del-significado-del-programa}

Además de los tipos, el analizador revisa reglas sobre el flujo del programa. Las condiciones de if y de else if deben ser bool. break y continue solo pueden ir dentro de un loop. Una función sin tipo de retorno puede usar return; pero no puede regresar un valor, y una función con tipo de retorno debe regresar un valor de ese tipo en cada return.

Una función con tipo de retorno tampoco puede llegar al final de su cuerpo sin regresar un valor. Para revisarlo usamos tres reglas. Una sentencia siempre retorna si es un return, si es un if con else donde todas las ramas siempre retornan, o si es un loop sin ningún break que lo termine, porque ese ciclo nunca acaba. Un bloque siempre retorna si alguna de sus sentencias siempre retorna. La siguiente tabla muestra algunos casos para una función fn f() -> i32.

| Cuerpo de la función | Resultado |
| :---- | :---- |
| return 1; | Válido |
| if c { return 1; } | Error: si c es falso no hay return |
| if c { return 1; } else { return 2; } | Válido |
| loop { } | Válido: el ciclo nunca termina |
| loop { if c { break; } } | Error: el break sale del ciclo sin regresar nada |
| loop { loop { break; } } | Válido: el break solo sale del ciclo de adentro |

Estas reglas no evalúan las condiciones. Por eso pueden rechazar una función que en la práctica siempre regresa un valor, pero nunca aceptan una que pueda terminar sin regresarlo.

Todo programa debe tener exactamente una función con la firma fn main(), sin parámetros ni tipo de retorno. El programa siempre regresa 0 al sistema operativo. Si falta main, o si tiene parámetros o tipo de retorno, el analizador reporta el error 11.

Probamos el analizador con pruebas unitarias en pytest, en tests/test_analyzer.py. Son 55 pruebas. La siguiente tabla las agrupa por lo que comprueban.

| Qué comprueban | Pruebas |
| :---- | :---- |
| Tabla de símbolos: definir y buscar nombres, entrar y salir de scopes, rechazo de shadowing y símbolos precargados | 1 |
| Ejemplos: que los programas válidos de docs/examples no tengan errores y que semantic_errors.mid reporte exactamente los errores marcados | 2 |
| Función main: que falte o que tenga una firma incorrecta | 1 |
| Nombres y alcance: nombres no declarados, uso antes de la declaración, globales predeclaradas, nombres repetidos y bloques hermanos | 3 |
| Tipos y literales: tipos que no existen, literales según el contexto, rangos y falta de conversiones implícitas | 5 |
| Operadores, punteros y conversiones: cada regla de la tabla de operadores, & y ^, y la tabla de conversiones completa | 21 |
| Asignaciones, llamadas, arreglos y slices: destinos válidos e inválidos, asignación compuesta, argumentos, índices, rangos y .len | 4 |
| Control de flujo: break y continue, valores de retorno, condiciones y todos los casos de retorno en todos los caminos | 14 |
| Anotaciones y errores: tipos y símbolos en el AST, que el AST anotado se compare igual al original, que no haya errores en cascada y que cada error tenga su posición | 4 |

Las corremos con el comando PYTHONPATH=src uv run pytest -v tests/test_analyzer.py, y pasan las 55.

También probamos el analizador con los programas de docs/examples. Los archivos assignment.mid, stringify.mid, algorithms.mid e interactive.mid pasan sin ningún error semántico. El archivo semantic_errors.mid tiene un caso por cada código de error, con un comentario en cada línea que dice qué error se espera. El analizador reporta 16 errores, uno por cada comentario más el de la función main que falta.
