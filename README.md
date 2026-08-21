# python-trace-compact

A zero-dependency high-density CLI compactor that compresses raw Python lines execution logs into readable structural matrices and chronological sequences.

## Installation

Install the package directly from your local development repository or download wheel artifacts:

```bash
pip install .
```

For live active development tracking, link the source paths using editable mode:

```bash
pip install -e .
```

## Usage

Pip pipelines register a universal entry point executable named `trace-compact` into your system binary environment paths.

### 1. High-Level Summary Matrix (`--summary`)
Aggregates overall module statistics sorted chronologically by the earliest trace step execution window entry point.

```bash
python3 -m trace --trace script.py | trace-compact --summary
```

**Output Layout:**
```text
# fields: earliest and latest trace step seen, filename, first and last line numbers, average calls (calls / distinct lines)
0007563-0027062 _base.py                         line 4-642, avg hits 1.1
0027063-0027110 units.py                         line 12-85, avg hits 1.0
```

To dynamically inject metrics back into the default view, supply comma-separated parameters via the `--fields` argument:
```bash
python3 -m trace --trace script.py | trace-compact --summary --fields count,distinct
```

### 2. Unique Execution Tallies (`--detailed-summary`)
Produces an alphabetically sorted filename summary displaying explicit total execution counts mapped to individual code lines.

```bash
python3 -m trace --trace script.py | trace-compact --detailed-summary
```

**Output Layout:**
```text
base.py|842✖️5|848✖️6|
typing.py|273✖️6|274✖️6|
```

### 3. Chronological Sequence Layout (Default Stream)
Collapses matching sequential executions within a file onto a single continuous line, using ellipsis truncation strings (`…`) to absorb repetitive loop structures.

```bash
python3 -m trace --trace script.py | trace-compact
```

**Output Layout:**
```text
enum.py:383:384:674:680:681:…:680:681:683:690
```

## Options & Arguments

To see the complete automated user configuration handbook directly inside your terminal, execute:

```bash
trace-compact --help
```

* `--skip-libs`: Automatically filters standard library internals, hidden wrappers, and `site-packages` dependencies out of output data logs to isolate your primary project application files.
* `-o`, `--output`: Instructs the processing core to dump compiled summaries into a persistent storage file instead of piping directly to `stdout`.

## License
* **Source Logic & Code Blocks**: Distributed under the terms of the [MIT License](LICENSE.md).
* **User Manuals & Layout Specifications**: Distributed under the terms of the [Creative Commons BY-NC-ND 4.0 International License](LICENSE.md).
