#!/usr/bin/env python3
import sys
import argparse
import re
from collections import defaultdict

def create_parser():
    # Multi-line raw description string to preserve text layout in --help output
    help_text = """Massively compress Python trace files into dense metrics, ranges, or structural summaries.

Usage Examples:

   1. Default Mode (Compact view with header)
   
   python3 -m trace --trace script.py | ./python-trace-compact --summary
   
   Output layout:
   
   # fields: earliest and latest trace step seen, filename, first and last line numbers, average calls (calls / distinct lines)
   0007563-0027062 _base.py                         line 4-642, avg hits 1.1

   2. Using --fields to add back data
   If you temporarily want to see total file hits or unique lines hit, pass them as a comma-separated list:
   
   python3 -m trace --trace script.py | ./python-trace-compact --summary --fields count,distinct
   
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

def process_trace():
    parser = create_parser()
    args = parser.parse_args()

    trace_pattern = re.compile(r'^([^:]+\.py)\((\d+)\):\s*(.*)$')
    ignore_keywords = ['site-packages', 'lib/python3', '/lib/', '<frozen']
    
    # Process optional requested fields
    requested_fields = [f.strip().lower() for f in args.fields.split(",") if f.strip()]
    
    # Global tracking structures
    global_tally = defaultdict(lambda: defaultdict(int))
    file_min_log_idx = {}
    file_max_log_idx = {}
    file_min_src_line = {}
    file_max_src_line = {}
    
    current_file = None
    line_sequence = []
    
    # Consume lines from file or standard input
    if args.input:
        with open(args.input, 'r') as f:
            input_lines = f.readlines()
    else:
        input_lines = sys.stdin.readlines()

    valid_matches = []

    # First pass: Parse and filter out library modules
    for raw_line in input_lines:
        match = trace_pattern.match(raw_line.strip())
        if not match:
            continue
            
        file, line_no, statement = match.groups()
        if args.skip_libs and any(kw in file for kw in ignore_keywords):
            continue
            
        valid_matches.append((file, int(line_no), statement))

    # Dynamically find maximum width for tracking index padding
    total_valid_lines = len(valid_matches)
    padding_width = max(5, len(str(total_valid_lines)))

    # Second pass: Process lines with precise global log index metrics
    for idx, (file, line_num, statement) in enumerate(valid_matches, start=1):
        if args.summary or args.detailed_summary:
            global_tally[file][str(line_num)] += 1
            
            # Map log sequence boundaries
            if file not in file_min_log_idx:
                file_min_log_idx[file] = idx
            file_max_log_idx[file] = idx
            
            # Map source code line ranges
            if file not in file_min_src_line or line_num < file_min_src_line[file]:
                file_min_src_line[file] = line_num
            if file not in file_max_src_line or line_num > file_max_src_line[file]:
                file_max_src_line[file] = line_num
        else:
            # Chronological inline trace tracking
            if file != current_file:
                if current_file and line_sequence:
                    seq_str = compress_with_ellipses(line_sequence)
                    args.output.write(f"{current_file}:{seq_str}\n")
                current_file = file
                line_sequence = [str(line_num)]
            else:
                line_sequence.append(str(line_num))

    # Output generation
    if args.summary:
        # Write out the required descriptive metadata header documentation
        args.output.write("# fields: earliest and latest trace step seen, filename, first and last line numbers, average calls (calls / distinct lines)\n")
        
        summary_rows = []
        for filename in global_tally.keys():
            line_counts = global_tally[filename].values()
            total_hits = sum(line_counts)
            distinct_lines = len(line_counts)
            average_hits = (total_hits / distinct_lines) if distinct_lines > 0 else 0.0
            
            # Format average hits cleanly
            avg_str = f"{average_hits:.1f}" if average_hits % 1 != 0 else f"{int(average_hits)}"
            
            # Zero-padded index string generation
            a_str = str(file_min_log_idx[filename]).zfill(padding_width)
            b_str = str(file_max_log_idx[filename]).zfill(padding_width)
            
            c = file_min_src_line[filename]
            d = file_max_src_line[filename]
            
            # Force filenames to be exactly 32-character left-aligned fields
            padded_filename = f"{filename:<32}"
            
            # Build basic compact string
            row_text = f"{a_str}-{b_str} {padded_filename} line {c}-{d}, avg hits {avg_str}"
            
            # Inject conditionally added metrics if requested via CLI flags
            if "count" in requested_fields:
                row_text += f", line count {total_hits}"
            if "distinct" in requested_fields:
                row_text += f", distinct lines {distinct_lines}"
                
            summary_rows.append((file_min_log_idx[filename], row_text))
            
        # Chronologically sort summary rows by execution startup index 'a'
        summary_rows.sort(key=lambda x: x)
        for _, row in summary_rows:
            args.output.write(f"{row}\n")
            
    elif args.detailed_summary:
        for filename in sorted(global_tally.keys()):
            sorted_lines = sorted(global_tally[filename].items(), key=lambda x: int(x))
            line_blocks = "".join(f"{line_no}✖️{count}|" for line_no, count in sorted_lines)
            args.output.write(f"{filename}|{line_blocks}\n")
            
    else:
        # Final flush for native pipeline stream execution
        if current_file and line_sequence:
            seq_str = compress_with_ellipses(line_sequence)
            args.output.write(f"{current_file}:{seq_str}\n")

    if args.output is not sys.stdout:
        args.output.close()

if __name__ == "__main__":
    process_trace()
