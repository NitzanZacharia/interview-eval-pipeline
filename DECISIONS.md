# Design Decisions Log

Ambiguous calls and deviations from SPEC.md, logged rather than expanding scope.

## Score Range: 0-4 vs 1-4

**SPEC §6** says criteria are scored 1-4. **SPEC §9.2** shows failed transcriptions use score 0. The Pydantic `DimensionScore.score` field uses `ge=0, le=4` to accommodate both: the LLM is instructed to score 1-4 for actual evaluations, while 0 is reserved for the failed-transcription/no-evaluation case. This is not a conflict — 0 is a sentinel, not a rubric score.

## analyze.py: `response.parsed_output` vs `response.output`

The SPEC references `client.messages.parse()` with `output_format=RubricAnalysis`. The current Anthropic SDK (>=0.92.0) returns the parsed Pydantic object via `response.parsed_output` when using `output_format=`. This is the correct attribute name per the SDK.

## analyze.py: Returns `Optional[RubricAnalysis]`

Rather than raising exceptions, `score_transcript()` catches all errors and returns `None`. The pipeline treats `None` as "Needs Human Review". This matches SPEC §10's per-candidate error isolation principle without requiring the pipeline to know about API-specific exception types.

## Pipeline: move-to-processed on failure

SPEC §3 says "move to processed" after output. The pipeline moves files to `processed/` even when transcription or scoring fails (after writing the zero-score JSON), because:
1. The candidate has been processed (just unsuccessfully)
2. Re-running the pipeline should not re-attempt failed candidates without manual intervention
3. The JSON output clearly marks the failure with "Needs Human Review"

If the user wants to re-process a failed candidate, they move the file back from `processed/` to the input directory.

## Unexpected pipeline errors

If an unexpected exception occurs (not transcription or scoring failure), the pipeline still writes a zero-score JSON but does NOT move the file to `processed/`. This allows automatic retry on the next run for truly transient errors.
