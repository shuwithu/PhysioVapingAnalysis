"""Filter exported ROI events without modifying source files.

Example: python3 src/physiovaping/process_eye_tracking.py --participants P5 P105
"""
import argparse
import csv
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path

if __package__:
    from .fixation_sequence import add_sequence, SEQUENCE_FIELDS
else:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from physiovaping.fixation_sequence import add_sequence, SEQUENCE_FIELDS


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_session(source, output):
    eye_files = list(source.glob('EyeFixation_*.csv'))
    event_files = list(source.glob('SceneEvents_*.csv'))
    if len(eye_files) != 1 or len(event_files) != 1:
        raise ValueError(f'Expected one file of each type: {source}')
    eye, events = eye_files[0], event_files[0]
    hashes = {str(p): digest(p) for p in (eye, events)}
    with events.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.reader(handle)
        header = next(reader)
        # These exports omit the Unix timestamp label from the header.
        if header != ['UtcIso', 'Scene', 'SecSinceLevelLoad', 'Event']:
            raise ValueError(f'Unexpected scene header: {header}')
        records = list(reader)
    if any(len(row) != 5 for row in records):
        raise ValueError('Expected five scene-event fields')
    timestamps = [Decimal(row[1]) for row in records]
    if timestamps != sorted(timestamps):
        raise ValueError('Scene records must be chronological')
    start = next(row for row in records if row[4] == 'KEY_S_PRESSED')
    end = next(row for row in records if row[4] == 'FADE_OUT_START')
    lower, upper = Decimal(start[1]), Decimal(end[1])
    if upper <= lower:
        raise ValueError('End marker must follow start marker')
    with eye.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    for source_row, row in enumerate(rows, 1):
        if None in row or any(v is None for v in row.values()):
            raise ValueError('Malformed eye-event row')
        if Decimal(row['End_Unix']) < Decimal(row['Start_Unix']):
            raise ValueError('Negative event interval')
        row['SourceRow'] = str(source_row)
    trimmed = [r for r in rows if Decimal(r['Start_Unix']) >= lower
               and Decimal(r['End_Unix']) <= upper]
    retained = [r for r in trimmed if Decimal(r['Duration_s']) >= Decimal('0.275')]
    retained = add_sequence(retained, lower)
    destination = output / f'{source.name}_FixationLineItem.csv'
    # Preserve original values; add sequence fields and sort chronologically.
    with destination.open('x', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields + SEQUENCE_FIELDS)
        writer.writeheader()
        writer.writerows(retained)
    with destination.open(newline='', encoding='utf-8') as handle:
        assert list(csv.DictReader(handle)) == retained
    assert all(digest(Path(p)) == h for p, h in hashes.items())
    return dict(session=source.name, start_local=start[0], end_local=end[0],
                start_unix=str(lower), end_unix=str(upper),
                window_seconds=str(upper-lower), input_rows=len(rows),
                within_window_rows=len(trimmed), excluded_by_window=len(rows)-len(trimmed),
                excluded_by_duration=len(trimmed)-len(retained), retained_rows=len(retained),
                retained_duration_seconds=str(sum((Decimal(r['Duration_s']) for r in retained), Decimal(0))),
                source_sha256=hashes, output=str(destination), output_sha256=digest(destination))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=os.environ.get('PHYSIOVAPING_DATA_ROOT'))
    parser.add_argument('--participants', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.data_root is None:
        parser.error('Set PHYSIOVAPING_DATA_ROOT or pass --data-root')
    args.output.mkdir(parents=True, exist_ok=False)
    summaries = [process_session(args.data_root / 'EyeTracking' / f'{pid}_CueScene{scene}', args.output)
                 for pid in args.participants for scene in (1, 2)]
    audit = dict(method='First KEY_S_PRESSED through first FADE_OUT_START, using exported Unix seconds; retain fully contained events (inclusive boundaries), then Duration_s >= 0.275. No event merging or tag exclusions.', sequence='Chronological Start_Unix, ties by SourceRow. Gaps and transitions concern qualifying fixations only; negative gaps denote overlap. Not a spatial trajectory.', sessions=summaries)
    (args.output / 'processing_audit.json').write_text(json.dumps(audit, indent=2) + '\n')
    print(json.dumps(summaries, indent=2))


if __name__ == '__main__':
    main()
