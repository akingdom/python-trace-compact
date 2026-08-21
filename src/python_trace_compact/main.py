#!/usr/bin/env python3
import sys
import argparse
import re
import os
import linecache
from collections import defaultdict

def create_parser():
    help_text = r"""Massively compress Python trace files into dense metrics, ranges, or structural summaries.

Usage Examples:

   1. Default Mode (Compact view with header)
   
   python3 -m trace --trace script.py | ./trace-compact --summary
   
   Output layout:
   
   # fields: earliest and latest trace step seen, filename, first and last line numbers, average calls (calls / distinct lines)
   0007563-0027062 _base.py                         line 4-642, avg hits 1.1

   2. Using --fields to add back data
   If you temporarily want to see total file hits or unique lines hit, pass them as a comma-separated list:
   
   python3 -m trace --trace script.py | ./trace-compact --summary --fields count,distinct
   
   Output layout:
   
   # fields: earliest and latest trace step seen, filename, first and last line numbers, average calls (calls / distinct lines)
   0007563-0027062 _base.py                         line 4-642, avg hits 1.1, line count 100, distinct lines 90
"""

    parser = argparse.ArgumentParser(
        description=help_text,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "input", 
        nargs="?", 
        help="Path to raw trace log file (if omitted, reads from stdin)"
    )
    parser.add_argument(
        "-o", "--output", 
        type=argparse.FileType("w"), 
        default=sys.stdout,
        help="Path to save summary (defaults to stdout)"
    )
    parser.add_argument(
        "--src",
        type=readable_dir,
        help="Verify trace lines against real source code files inside this root path directory"
    )
    parser.add_argument(
        "--skip-libs", 
        action="store_true", 
        help="Filter out standard library and site-packages files"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="High-level text overview sorted by log index range"
    )
    parser.add_argument(
        "--detailed-summary",
        action="store_true",
        help="Matrix summary by filename displaying sorted execution tallies per line"
    )
    parser.add_argument(
        "--fields",
        type=str,
        default="",
        help="Comma-separated optional fields to add back to the summary row (supported: count, distinct)"
    )
    return parser

def readable_dir(path_str):
    """Custom argparse type to expand paths and enforce directory existence."""
    expanded = os.path.abspath(os.path.expanduser(path_str.strip("'\"")))
    if not os.path.exists(expanded):
        raise argparse.ArgumentTypeError(f"Directory does not exist: '{path_str}' (resolved to '{expanded}')")
    if not os.path.isdir(expanded):
        raise argparse.ArgumentTypeError(f"Path is not a directory: '{path_str}'")
    return expanded

def compress_with_ellipses(sequence):
    """Compresses chronological line logs using the ellipsis rule."""
    if not sequence:
        return ""
    n = len(sequence)
    compressed = []
    i = 0
    while i < n:
        match_found = False
        for pattern_len in range(min(10, (n - i) // 3), 0, -1):
            pattern = sequence[i:i + pattern_len]
            count = 1
            while i + (count + 1) * pattern_len <= n and sequence[i + count * pattern_len : i + (count + 1) * pattern_len] == pattern:
                count += 1
            if count >= 3:
                pattern_str = ":".join(pattern)
                compressed.append(f"{pattern_str}:…:{pattern_str}")
                i += count * pattern_len
                match_found = True
                break
        if not match_found:
            compressed.append(sequence[i])
            i += 1
    return ":".join(compressed)

def index_source_tree(root_path):
    """
    Builds a lightweight mapping of filename basenames to relative paths and line counts.
    Structure: { 'utils.py': [ ('pkg_a/utils.py', '/abs/path', line_count) ] }
    """
    tree_map = {}
    abs_root = os.path.abspath(root_path)

    if not os.path.exists(abs_root) or not os.path.isdir(abs_root):
        return tree_map, abs_root

    for root, _, files in os.walk(abs_root, followlinks=True):
        for f in files:
            if f.endswith(".py"):
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, abs_root)
                try:
                    with open(full_path, "rb") as fp:
                        line_count = sum(1 for _ in fp)
                    if f not in tree_map:
                        tree_map[f] = []
                    tree_map[f].append((rel_path, full_path, line_count))
                except Exception:
                    continue

    return tree_map, abs_root

def verify_and_resolve_file(trace_file_path, line_no, trace_statement, source_tree):
    """
    Fast verification using line bounds first, resorting to linecache only when ambiguous.
    """
    trace_basename = os.path.basename(trace_file_path)

    if trace_basename not in source_tree:
        return None, False

    candidates = source_tree[trace_basename]
    valid_candidates = [
        (rel_path, full_path) 
        for rel_path, full_path, line_count in candidates 
        if 1 <= line_no <= line_count
    ]

    if not valid_candidates:
        return None, False

    # Single match by path/line bounds: accept immediately without file I/O
    if len(valid_candidates) == 1:
        return valid_candidates[0][0], True

    # Disambiguate multiple matches by checking source content via linecache
    clean_statement = trace_statement.strip()
    for rel_path, full_path in valid_candidates:
        disk_line = linecache.getline(full_path, line_no).strip()
        if clean_statement == disk_line:
            return rel_path, True

    # Fallback to first valid candidate if formatting slightly differs
    return valid_candidates[0][0], True

def process_trace():
    parser = create_parser()
    args = parser.parse_args()

    trace_pattern = re.compile(r'^([^:]+\.py)\((\d+)\):\s*(.*)$')
    ignore_keywords = ['site-packages', 'lib/python3', '/lib/', '<frozen']
    
    # Initialize source file indexing if a verification directory path was provided
    source_tree = {}
    src_root_abs = ""
    if args.src:
        source_tree, src_root_abs = index_source_tree(args.src)
    
    requested_fields = [f.strip().lower() for f in args.fields.split(",") if f.strip()]
    
    global_tally = defaultdict(lambda: defaultdict(int))
    file_min_log_idx = {}
    file_max_log_idx = {}
    file_min_src_line = {}
    file_max_src_line = {}
    
    current_file = None
    line_sequence = []
    
    if args.input:
        with open(args.input, 'r') as f:
            input_lines = f.readlines()
    else:
        input_lines = sys.stdin.readlines()

    valid_matches = []

    for raw_line in input_lines:
        match = trace_pattern.match(raw_line.strip())
        if not match:
            continue
            
        file_path, line_no_str, statement = match.groups()
        line_no = int(line_no_str)
        
        # 1. Apply generic system library filters
        if args.skip_libs and any(kw in file_path for kw in ignore_keywords):
            continue
            
        # 2. Run source content verification filter if --src is passed
        if args.src:
            resolved_name, is_valid = verify_and_resolve_file(
                file_path, line_no, statement, source_tree
            )
            if not is_valid:
                continue
            display_name = resolved_name
        else:
            # Fallback to standard base name if no verification directory is specified
            display_name = os.path.basename(file_path)
            
        valid_matches.append((display_name, line_no, statement))

    total_valid_lines = len(valid_matches)
    padding_width = max(5, len(str(total_valid_lines)))

    if args.summary:
        args.output.write("# fields: earliest and latest trace step seen, filepath, first and last line numbers, average calls (calls / distinct lines)\n")
        
        for idx, (filename, line_num, statement) in enumerate(valid_matches, start=1):
            global_tally[filename][str(line_num)] += 1
            if filename not in file_min_log_idx:
                file_min_log_idx[filename] = idx
            file_max_log_idx[filename] = idx
            
            if filename not in file_min_src_line or line_num < file_min_src_line[filename]:
                file_min_src_line[filename] = line_num
            if filename not in file_max_src_line or line_num > file_max_src_line[filename]:
                file_max_src_line[filename] = line_num

        summary_rows = []
        for filename in global_tally.keys():
            line_counts = global_tally[filename].values()
            total_hits = sum(line_counts)
            distinct_lines = len(line_counts)
            average_hits = (total_hits / distinct_lines) if distinct_lines > 0 else 0.0
            
            avg_str = f"{average_hits:.1f}" if average_hits % 1 != 0 else f"{int(average_hits)}"
            a_str = str(file_min_log_idx[filename]).zfill(padding_width)
            b_str = str(file_max_log_idx[filename]).zfill(padding_width)
            c = file_min_src_line[filename]
            d = file_max_src_line[filename]
            
            padded_filename = f"{filename:<32}"
            row_text = f"{a_str}-{b_str} {padded_filename} line {c}-{d}, avg hits {avg_str}"
            
            if "count" in requested_fields:
                row_text += f", line count {total_hits}"
            if "distinct" in requested_fields:
                row_text += f", distinct lines {distinct_lines}"
                
            summary_rows.append((file_min_log_idx[filename], row_text))
            
        summary_rows.sort(key=lambda x: x[0])
        for _, row in summary_rows:
            args.output.write(f"{row}\n")
            
    elif args.detailed_summary:
        args.output.write("# fields: filepath, line number✖calls|...\n")
        for idx, (filename, line_num, statement) in enumerate(valid_matches, start=1):
            global_tally[filename][str(line_num)] += 1

        for filename in sorted(global_tally.keys()):
            sorted_lines = sorted(global_tally[filename].items(), key=lambda x: int(x[0]))
            line_blocks = "".join(f"{line_no}✖️{count}|" for line_no, count in sorted_lines)
            args.output.write(f"{filename}|{line_blocks}\n")
            
    else:
        args.output.write("# fields: filepath, line numbers\n")
        for idx, (filename, line_num, statement) in enumerate(valid_matches, start=1):
            if filename != current_file:
                if current_file and line_sequence:
                    seq_str = compress_with_ellipses(line_sequence)
                    args.output.write(f"{current_file}:{seq_str}\n")
                current_file = filename
                line_sequence = [str(line_num)]
            else:
                line_sequence.append(str(line_num))

        if current_file and line_sequence:
            seq_str = compress_with_ellipses(line_sequence)
            args.output.write(f"{current_file}:{seq_str}\n")

    if args.output is not sys.stdout:
        args.output.close()

if __name__ == "__main__":
    process_trace()
