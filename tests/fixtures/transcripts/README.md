# Transcript Fixtures

Place raw transcript text files here before running `scripts/compare_prompts.py`.

## Files expected

| Filename | Airtable record | Candidate |
|:---|:---|:---|
| `leslie_doucet.txt` | `reczTlPSTM2sPwUlT` | Leslie Doucet |
| `maria_ferrara.txt` | `recsVfgqIxNs9Kh56` | Maria Ferrara |
| `emily_kobelenz.txt` | `recGANQTpkdi3lIkG` | Emily Kobelenz-DiRienzo |

## How to generate

Run the simulation script with `--save-transcript` (if that flag exists) or extract
transcript text from `sim_output/<candidate_id>.json` under the `transcript_metadata`
field after a normal simulation run.

Alternatively, run the pipeline with `--record-id <id>` for each record and copy the
transcript text from the JSON output.
