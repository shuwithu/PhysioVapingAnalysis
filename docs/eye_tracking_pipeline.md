# Eye-tracking processing

Source files remain immutable and outside this repository. Pair EyeFixation
and SceneEvents by participant/scene. The current SceneEvents export has four
header labels but five values: ISO time, Unix seconds, scene, elapsed time, event.

1. Select first KEY_S_PRESSED and first FADE_OUT_START, using Unix seconds.
2. Keep events fully contained within the inclusive window; do not clip.
3. Keep Duration_s >= 0.275; do not merge events.
4. Sort retained events by Start_Unix, then SourceRow for ties.
5. Add sequence fields to the original columns in FixationLineItem CSVs.
6. Aggregate by exact object name and by cue category.

## Sequence fields

| Field | Definition |
|---|---|
| SourceRow | Original 1-based data-row number, excluding header |
| FixationOrder | 1-based order within participant/scene after filtering |
| StartSinceSceneStart_s / EndSinceSceneStart_s | Unix time minus selected start marker |
| CueCategory | NonSocialVapingCue, SocialVapingCue, Other |
| PreviousObjectName / PreviousCueCategory | Previous retained fixation; blank for first |
| GapSincePreviousFixation_s | Current start minus previous end; negative indicates overlap |
| SameStartAsPrevious | Flags tied start times; source-row ordering is not a resolved temporal order |
| OverlapsPrevious | Flags overlap with immediately preceding retained event |

These are object-level sequences, not spatial trajectories. Transitions and
gaps concern qualifying fixations only; shorter excluded events or looks at
unrecorded objects may intervene. Gaps do not measure tracking loss. Original
event durations and timestamps are preserved; rounded export timestamps may
differ slightly from Duration_s.

## Categories and summaries

Non-social includes vape/tobacco objects, CigarettesAOI, PhoneScreenAOI,
PosterVape1–4, and smoke objects tagged Smoke with VapeSmoke in their names.
Social includes objects tagged Vapers. Other recognized tags default to Other;
unknown tags stop processing for review. Inspect object mappings before a batch
run, because newly named vaping objects under known tags may need explicit rules.
KeyAOI is a subtotal of social plus non-social, never a fourth exclusive group.
Percentages use all retained fixation time as denominator. First fixation is
the earliest retained event, not necessarily the first raw gaze event.

## Run

Set PHYSIOVAPING_DATA_ROOT to the external DATA directory. Use a new output
directory for each processing run. For example:

```bash
python3 src/physiovaping/process_eye_tracking.py --participants P5 P105 --output "$PHYSIOVAPING_DATA_ROOT/Interim/EyeTracking/new_pilot_run"
python3 src/physiovaping/aggregate_eye_tracking.py "$PHYSIOVAPING_DATA_ROOT/Interim/EyeTracking/new_pilot_run/"*_FixationLineItem.csv
python3 src/physiovaping/aggregate_eye_tracking_cues.py "$PHYSIOVAPING_DATA_ROOT/Interim/EyeTracking/new_pilot_run"
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_fixation_sequence.py'
```

Missing markers currently stop processing; partial-session and participant
exclusions require an explicit policy. No full-cohort batch has been authorized
by the sequence update alone.

## Version control

Track source code, documentation, nonidentifying configuration and synthetic
tests. Keep participant data, generated reports/figures, local paths/secrets,
and notebook participant outputs outside Git. Review the exact staged diff
before the initial commit; do not blindly stage the entire workspace. Begin
with a private GitHub repository and publish only the reviewed code baseline.
Git ignore rules prevent many accidental additions, but do not replace review.
