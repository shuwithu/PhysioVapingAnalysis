"""Aggregate filtered events into user-defined vaping cue categories.

KeyAOI is a subtotal (NonSocialVapingCue + SocialVapingCue), not a
fourth mutually exclusive category. Shares use all retained fixation time.
"""
import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path

CATEGORIES = ('NonSocialVapingCue', 'SocialVapingCue', 'Other')
NON_SOCIAL_OBJECTS = {
    'VapeShelfAOI', 'CigarettesAOI', 'PhoneScreenAOI',
    'PosterVape1', 'PosterVape2', 'PosterVape3', 'PosterVape4',
}


def classify(name, tag):
    # Strip whitespace for matching only; preserve source names in outputs.
    name, tag = name.strip(), tag.strip()
    if name in NON_SOCIAL_OBJECTS or tag == 'Vapes' or (tag == 'Smoke' and 'VapeSmoke' in name):
        return 'NonSocialVapingCue'
    if tag == 'Vapers':
        return 'SocialVapingCue'
    if tag not in {'Poster', 'Smoke', 'VirtualHumans', 'Alcohol', 'Others'}:
        raise ValueError(f'Unreviewed object tag: {name!r}, {tag!r}')
    return 'Other'


def write_csv(path, rows):
    with path.open('x', newline='', encoding='utf-8') as h:
        writer = csv.DictWriter(h, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with path.open(newline='', encoding='utf-8') as h:
        assert list(csv.DictReader(h)) == [{k: str(v) for k, v in r.items()} for r in rows]


def aggregate(path):
    with path.open(newline='', encoding='utf-8') as h:
        events = list(csv.DictReader(h))
    session = path.name.removesuffix('_FixationLineItem.csv')
    participant, scene = session.split('_', 1)
    duration = lambda rows: sum((Decimal(r['Duration_s']) for r in rows), Decimal(0))
    total = duration(events)
    first = min(events, key=lambda r: Decimal(r['Start_Unix'])) if events else None
    groups = {c: [r for r in events if classify(r['ObjectName'], r['ObjectTag']) == c] for c in CATEGORIES}
    assert sum(len(g) for g in groups.values()) == len(events)
    assert sum((duration(g) for g in groups.values()), Decimal(0)) == total
    groups['KeyAOI'] = groups['NonSocialVapingCue'] + groups['SocialVapingCue']
    rows = []
    for category, members in groups.items():
        rows.append(dict(Participant=participant, Scene=scene, Category=category,
                         IsSubtotal=category == 'KeyAOI', FixationCount=len(members),
                         TotalFixationDuration_s=str(duration(members)),
                         ShareOfRetainedFixationTime_pct=str((100*duration(members)/total).quantize(Decimal('0.01'))) if total else '',
                         FirstFixationObject=first['ObjectName'] if first else '',
                         FirstFixationCategory=classify(first['ObjectName'], first['ObjectTag']) if first else ''))
    write_csv(path.with_name(f'{session}_FixationByCueCategory.csv'), rows)
    return rows, {(r['ObjectName'], r['ObjectTag'], classify(r['ObjectName'], r['ObjectTag'])) for r in events}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    # Verify explicit rules, including the not-yet-observed phone-screen AOI.
    assert classify('PhoneScreenAOI', 'Others') == 'NonSocialVapingCue'
    assert classify('CigarettesAOI', 'Vapes') == 'NonSocialVapingCue'
    assert classify('JoeVapeSmoke', 'Smoke') == 'NonSocialVapingCue'
    assert classify('BBQSmoke1', 'Smoke') == 'Other'
    assert classify('JoeAOI', 'Vapers') == 'SocialVapingCue'
    assert classify('CustomerAOI', 'VirtualHumans') == 'Other'
    summaries, mapping = [], set()
    for path in sorted(args.directory.glob('*_FixationLineItem.csv')):
        rows, objects = aggregate(path)
        summaries.extend(rows)
        mapping.update(objects)
    write_csv(args.directory/'Pilot_FixationByCueCategory.csv', summaries)
    write_csv(args.directory/'Pilot_ObservedObjectCueMapping.csv',
              [dict(ObjectName=n, ObjectTag=t, Category=c) for n,t,c in sorted(mapping)])
    metadata = dict(non_social_explicit_objects=sorted(NON_SOCIAL_OBJECTS),
                    additional_non_social_rules=['ObjectTag == Vapes', 'ObjectTag == Smoke and ObjectName contains VapeSmoke'],
                    social_rule='ObjectTag == Vapers', other='Remaining recognized tags',
                    key_aoi='NonSocialVapingCue + SocialVapingCue; subtotal only',
                    denominator='Total duration of all retained fixations per participant/scene',
                    absent_category='Zero observed retained fixation time, not evidence of zero exposure',
                    input_filter='Existing line items unchanged; fully inside marker window and Duration_s >= 0.275')
    (args.directory/'cue_category_definitions.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps(summaries, indent=2))


if __name__ == '__main__':
    main()
