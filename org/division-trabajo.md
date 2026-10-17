# Division de Trabajo PIA Compiladores

## Objetivo
Implementar un compilador / traductor de lenguaje para el lenguaje mid en python
en el transcurso de 5 semanas. La implementación del compilador se dividirá en 1
pseudo-etapa continua de planeación y 4 etapas cerradas de implementación. Estas
5 etapas serán distribuidas entre 6 integrantes.

### Integrantes 
- Aldo
- Esmeralda
- Diego
- Rodrigo
- Luis
- Roberto

### Etapas de implementación
0. Planeación e Interfaces
1. Lexer
2. Parser
3. Analizador semántico
4. Generación de código


## Etapa de Planeación e Interfaces (Aldo)
El objetivo principal de esta etapa es generar la documentación y especificación
del lenguaje mid para facilitar el progreso de las etapas posteriores, asi como
definir las estructuras de datos que se utilizarán como interfaces (entrada y salida)
entre las diferentes etapas para permitir una implementación sin cuellos de botella.

Esta etapa tendrá lugar durante las 5 semanas de desarrollo ya que se relaciona con
cada una de las 4 etapas de implementación.

**Responsabilidades**
- Generar la especificación del lenguaje (docs/**.md)                                       | Semana 1 - 3
- Evitar modificaciones innecesarias una vez quede acordada la especificación               | Semana 1 - 5
- En caso de ambigüedades, resolver dudas y aclarar la especificación                       | Semana 1 - 5
- Generar las especificaciones para la implementación de cada fase (docs/stages/*.md)       | Semana 1 - 4
- Implementar las estructuras de datos relacionados con los tokens (src/mid/types/token.py) | Semana 1
- Implementar las estructuras de datos relacionados con el AST (src/mid/types/ast.py)       | Semana 1 - 2
- Implementar la CLI y la concatenación de las salidas de las fases (src/mid/main.py)       | Semana 2 - 5

**Secciones del Proyecto relacionadas**
- docs/**.md
- docs/stages/*.md
- src/mid/types/token.py
- src/mid/types/ast.py
- src/mid/main.py


## Etapas de Implementación
Estas etapas se relacionan directamente con la implementación de cada una de las
fases del compilador. Tienen entradas y salidas definidas y por lo
tanto es necesario implementar pruebas unitarias para comprobar el correcto
funcionamiento de las distintas fases. Cada fase debe contar por lo menos con
3 pruebas unitarias diseñadas para encontrar errores comunes y casos extremos.


### Lexer (Roberto) | Límite de entrega: Semana 2
Implementar el Lexer (src/mid/frontend/lexer.py) de acuerdo a la especificación
ubicada en (docs/stages/lexer.md).
- Entrada: String con el contenido del código fuente
- Salida: Iterador / Flujo de tokens (token stream)

**Responsabilidades**
- Implementar componente Lexer funcional ubicado en src/mid/frontend/lexer.py
- Mínimo de 3 pruebas unitarias que demuestren el funcionamiento del lexer

**Secciones del Proyecto relacionadas**
- src/mid/frontend/lexer.py
- src/mid/types/token.py
- docs/stages/lexer.md


### Parser (Luis) | Límite de entrega: Semana 3
Implementar el Parser (src/mid/frontend/parser.py) de acuerdo a la especificación
ubicada en (docs/stages/parser.md)
- Entrada: Iterador / Flujo de tokens (token stream)
- Salida: AST (Arbol de Sintaxis Abstracta) no anotado

**Responsabilidades**
- Implementar componente Parser funcional ubicado en src/mid/frontend/parser.py
- Mínimo de 3 pruebas unitarias que demuestren el funcionamiento del parser

**Secciones del Proyecto relacionadas**
- src/mid/frontend/parser.py
- src/mid/types/token.py
- src/mid/types/ast.py
- docs/stages/parser.md


### Analizador semántico (Esmeralda y Diego) | Límite de entrega: Semana 4
Implementar la Tabla de Símbolos y el Analizador Semántico (src/mid/frontend/analyzer.py) de acuerdo
a la especificación ubicada en (docs/stages/analyzer.md).
- Entrada: AST sin anotar
- Salida: AST Decorado (anotado con tipos) y Tabla de Símbolos poblada y validada

**Responsabilidades**
- Implementar la Tabla de Símbolos y manejo de scopes (src/mid/types/symbol_table.py)
- Implementar componente Analizador funcional ubicado en src/mid/frontend/analyzer.py
- Mínimo de 3 pruebas unitarias que demuestren el funcionamiento del analizador

**Secciones del Proyecto relacionadas**
- src/mid/frontend/analyzer.py
- src/mid/types/ast.py
- src/mid/types/symbol_table.py
- docs/stages/analyzer.md


### Generación de código (Rodrigo) | Límite de entrega: Semana 5
Implementar la generación de código utilizando la librería llvmlite de acuerdo a
la especificación ubicada en (docs/stages/codegen.md)
- Entrada: AST Decorado y Tabla de Símbolos
- Salida: Objeto módulo de llvmlite (LLVM IR)

**Responsabilidades**
- Componente de generación de código ubicado en src/mid/backend/codegen.py
- Mínimo de 3 pruebas unitarias que demuestren el funcionamiento del generador de código
  (validando las cadenas de texto del LLVM IR emitido con `str(module)`)

**Secciones del Proyecto relacionadas**
- src/mid/backend/codegen.py
- src/mid/types/ast.py
- src/mid/types/symbol_table.py
- docs/stages/codegen.md
