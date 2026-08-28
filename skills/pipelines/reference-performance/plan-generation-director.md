# Plan Generation Director - Reference Performance Pipeline

## Goal

Compile the timed performance contract and identity binding into a reviewable
MiniMax-H3 request. This stage never calls the paid API.

## Required tool

Use `reference_performance_h3_plan` with:

- target identity image URL(s)
- motion reference video URL
- `performance_analysis`
- subject mapping and camera lock
- explicit source exclusion rules

## Strategy

Prefer one-shot generation for a simple continuous performance up to 15
seconds. Use segments only when the reference contains complex changes that
cannot be held reliably in one request. Any segments must have terminal pose,
hand position, gaze, expression, and weight as a bridge contract.

Write the request and planned `GenerationAttempt`, show estimated cost, and
stop for approval.
