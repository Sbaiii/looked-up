"""Phase 2 analytics: automation flags, baselines, spikes and attention events.

Definitions are pre-registered in docs/prereg_phase2.md; thresholds come from
config/analytics.yml. The same SQL builders serve the dbt warehouse (batch, by day)
and the hourly production scorer, so both apply identical rules.
"""
