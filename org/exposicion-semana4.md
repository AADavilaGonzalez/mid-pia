# Exposición: Análisis semántico (2 minutos)

| Tiempo | Quién | Tema | En pantalla |
| :---- | :---- | :---- | :---- |
| 0:00 – 1:00 | Esmeralda | Qué hace el analizador, tabla de símbolos y alcance | analyzer.py y symbol_table.py |
| 1:00 – 2:00 | Diego | Tipos, errores (demo) y AST anotado | analyzer.py, terminal y ast.py |

## Antes de empezar

Dejar abiertas estas pestañas en VS Code, en este orden:

1. src/mid/frontend/analyzer.py, en la línea 224 (analyze)
2. src/mid/types/symbol_table.py, en la línea 119 (define)
3. docs/examples/errors/semantic_errors.mid
4. src/mid/types/ast.py, en la línea 27 (campo ty)

En la terminal, dejar escrito este comando sin ejecutarlo:

```text
uv run mid docs/examples/errors/semantic_errors.mid
```

---

## Parte 1: Esmeralda (0:00 – 1:00)

**[Mostrar analyzer.py, función analyze, línea 224]**

> "El analizador semántico recibe el AST del parser y revisa que el programa
> tenga sentido: que los nombres existan, que los tipos coincidan y que el
> flujo sea válido. Entrega el AST anotado, la tabla de símbolos y la lista de
> errores. Trabaja en cuatro pasadas: primero registra todas las funciones y
> globales, luego revisa los valores iniciales de las globales, después
> comprueba que exista main y al final revisa cada función. Por eso una
> función puede llamar a otra que está más abajo en el archivo."

**[Cambiar a symbol_table.py, función define, línea 119]**

> "La tabla de símbolos organiza los nombres en tres niveles de scope: global,
> de función y de bloque. Ya trae precargados los tipos primitivos y las
> funciones de la biblioteca estándar. Mid no permite shadowing: define rechaza
> un nombre si ya es visible desde un scope exterior, y así cada nombre se
> refiere a una sola cosa. Los bloques hermanos sí pueden repetir nombres,
> porque no se ven entre sí."

> "Diego va a explicar cómo verificamos los tipos."

---

## Parte 2: Diego (1:00 – 2:00)

**[Mostrar analyzer.py, función int_literal, línea 487]**

> "No hay conversiones implícitas: si a es u8 y b es i32, a = b es un error y
> hay que usar as. La excepción son los literales, que toman el tipo de su
> contexto: en i: usize = 0, el cero es usize. Además revisamos que el valor
> quepa en el tipo; 300 no cabe en un u8. Las conversiones con as siguen una
> tabla que definimos en valid_cast."

**[Cambiar a la terminal y ejecutar el comando]**

> "Aquí está semantic_errors.mid, que tiene un error de cada tipo. El
> analizador no se detiene en el primero: reporta los 16, cada uno con su
> código, línea y columna. Y un error no provoca otros en cascada, porque la
> expresión que falla recibe un tipo especial, ERROR, compatible con todo."

**[Cambiar a ast.py, línea 27]**

> "Por último, anotamos el AST: cada nodo tiene un campo ty con su tipo y un
> campo symbol que apunta a su entrada en la tabla. Con eso la generación de
> código sabe qué instrucción emitir y qué variable usar. Lo probamos con 55
> pruebas unitarias."

---

## Si se acaba el tiempo

- Esmeralda puede omitir la frase de los bloques hermanos.
- Diego puede omitir la mención de valid_cast y el tipo ERROR.

## Posibles preguntas

| Pregunta | Respuesta corta |
| :---- | :---- |
| ¿Por qué no permiten shadowing? | Lo define la especificación del lenguaje, para que cada nombre visible se refiera a una sola cosa. |
| ¿Cómo saben que una función siempre regresa un valor? | Una sentencia siempre retorna si es un return, un if con else donde todas las ramas retornan, o un loop sin break. Son reglas conservadoras: nunca aceptan una función que pueda terminar sin valor. |
| ¿Por qué crearon SemType si ya existía el nodo Type? | El nodo Type guarda su posición en el código, así que dos i32 en líneas distintas no eran iguales al compararlos. SemType compara solo el nombre y los calificadores. |
| ¿Qué pasa si hay errores de sintaxis? | El parser deja ErrorNode en el AST y el analizador los ignora sin reportar errores extra. |
