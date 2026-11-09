"""Object-level sequence of qualifying fixations, not a spatial trajectory."""
from decimal import Decimal

from .aggregate_eye_tracking_cues import classify

SEQUENCE_FIELDS = [
    'SourceRow', 'FixationOrder', 'StartSinceSceneStart_s',
    'EndSinceSceneStart_s', 'CueCategory', 'PreviousObjectName',
    'PreviousCueCategory', 'GapSincePreviousFixation_s',
    'SameStartAsPrevious', 'OverlapsPrevious',
]


def add_sequence(rows, scene_start):
    """Stable chronological order; source-row tie break does not imply gaze order.

    Rows carry SourceRow (1-based data row, excluding header). Negative gaps
    flag overlaps and are preserved. First-row previous fields are blank.
    """
    ordered = sorted(rows, key=lambda r: (Decimal(r['Start_Unix']), int(r['SourceRow'])))
    result = []
    previous = None
    for order, original in enumerate(ordered, 1):
        row = dict(original)
        start, end = Decimal(row['Start_Unix']), Decimal(row['End_Unix'])
        gap = start - Decimal(previous['End_Unix']) if previous else None
        row.update(FixationOrder=str(order),
                   StartSinceSceneStart_s=str(start - scene_start),
                   EndSinceSceneStart_s=str(end - scene_start),
                   CueCategory=classify(row['ObjectName'], row['ObjectTag']),
                   PreviousObjectName=previous['ObjectName'] if previous else '',
                   PreviousCueCategory=previous['CueCategory'] if previous else '',
                   GapSincePreviousFixation_s=str(gap) if gap is not None else '',
                   SameStartAsPrevious=str(start == Decimal(previous['Start_Unix'])) if previous else '',
                   OverlapsPrevious=str(gap < 0) if gap is not None else '')
        result.append(row)
        previous = row
    return result
