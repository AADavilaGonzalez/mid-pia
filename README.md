# Compilador Mid Pia Compiladores Jul-Dec 2026

## Descripción

Mid es un compilador experimental para el lenguaje de programación del mismo
nombre. El proyecto implementa las etapas de análisis léxico, análisis
sintáctico, análisis semántico y generación de código LLVM, además de permitir
la ejecución de los programas compilados mediante un JIT.

## Cómo ejecutar los ejemplos

Desde la raíz del proyecto, crea y activa un entorno virtual e instala las
dependencias:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install llvmlite pytest
```

Después, ejecuta un archivo `.mid` usando el módulo principal y establece
`src` como ruta de importación:

```bash
PYTHONPATH=src python -m mid.main docs/examples/simple/assignment.mid
```

También puedes mostrar el resultado de las distintas fases directamente en la terminal:

```bash
PYTHONPATH=src python -m mid.main --ir docs/examples/complex/sum.mid --stdout
```

Para consultar todas las fases, opciones y banderas disponibles, lee
[`docs/cli.md`](docs/cli.md).

## Profesor: Luis Ángel Gutiérrez Rodríguez

## Integrantes
- Esmeralda Gabriela Mendieta Gonzalez 2064574
- Roberto Sánchez Santoyo 2177547
- Luis Fernando Segobia Torres 2177528
- Diego Flores López 2066033
- Rodrigo Zacatenco Olive 1857791
- Aldo Adrián Dávila González 1994122
