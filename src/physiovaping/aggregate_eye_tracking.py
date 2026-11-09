"""Aggregate retained fixation events by exact ObjectName, separately per session."""
import argparse
import csv
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


def aggregate(path):
    with path.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    session = path.name.removesuffix('_FixationLineItem.csv')
    participant, scene = session.split('_', 1)
    first = min(rows, key=lambda row: Decimal(row['Start_Unix'])) if rows else None
    if first and sum(r['Start_Unix'] == first['Start_Unix'] for r in rows) > 1:
        raise ValueError(f'Ambiguous first fixation in {session}')
    groups = defaultdict(list)
    for row in rows:
        groups[row['ObjectName']].append(row)
    result = []
    for name, events in groups.items():
        result.append(dict(Participant=participant, Scene=scene, ObjectName=name,
                           FixationCount=len(events),
                           TotalFixationDuration_s=str(sum((Decimal(r['Duration_s']) for r in events), Decimal(0))),
                           IsFirstFixationObject=name == first['ObjectName']))
    result.sort(key=lambda r: (-Decimal(r['TotalFixationDuration_s']), r['ObjectName']))
    assert sum(r['FixationCount'] for r in result) == len(rows)
    assert sum((Decimal(r['TotalFixationDuration_s']) for r in result), Decimal(0)) == sum((Decimal(r['Duration_s']) for r in rows), Decimal(0))
    target = path.with_name(f'{session}_FixationByObject.csv')
    fields = ['Participant', 'Scene', 'ObjectName', 'FixationCount', 'TotalFixationDuration_s', 'IsFirstFixationObject']
    with target.open('x', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result)
    with target.open(newline='', encoding='utf-8') as handle:
        saved = list(csv.DictReader(handle))
    assert saved == [{k: str(v) for k, v in r.items()} for r in result]
    return dict(session=session, first_fixation=first, objects=result, output=str(target))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    args = parser.parse_args()
    print(json.dumps([aggregate(path) for path in args.files], indent=2))


if __name__ == '__main__':
    main()
