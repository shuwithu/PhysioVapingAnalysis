# PhysioVaping Analysis

Python and Jupyter workflows for cleaning and analyzing the PhysioVaping study.

## Data separation

Participant data are stored outside this Git repository. Set the local data path
with the `PHYSIOVAPING_DATA_ROOT` environment variable. Copy `.env.example` to
`.env` for local use; `.env` is excluded from Git.

The expected local data root is:

```text
/Users/sw2528/Documents/PhysioVaping/DATA
```

Never add participant names, email addresses, phone information, raw study data,
or identifiable notebook output to this repository.

## Project structure

```text
notebooks/          Exploratory and documented Jupyter workflows
src/physiovaping/   Reusable Python processing functions
config/             Version-controlled nonidentifiable processing settings
tests/              Automated tests
outputs/            Local generated results; contents ignored by Git
```

Notebook stages are organized by architecture, subjective data, PPG/HRV, EDA,
eye tracking, and multimodal integration.

See [the eye-tracking pipeline](docs/eye_tracking_pipeline.md) for filtering,
fixation sequences, cue classification, aggregation, and execution commands.

