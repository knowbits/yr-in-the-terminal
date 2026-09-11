#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
}

@test "every radar-touched row uses overlapping radar samples" {
    run uv run --project "$REPO_ROOT" python "$REPO_ROOT/tests/test_yr_today.py" \
        RadarRainRangesTest.test_all_radar_touched_rows_use_their_overlapping_samples

    [ "$status" -eq 0 ]
}

@test "partially radar-covered third row includes its hourly tail" {
    run uv run --project "$REPO_ROOT" python "$REPO_ROOT/tests/test_yr_today.py" \
        RadarRainRangesTest.test_third_row_combines_radar_with_hourly_uncovered_tail

    [ "$status" -eq 0 ]
}

@test "rows beyond radar use the hourly forecast" {
    run uv run --project "$REPO_ROOT" python "$REPO_ROOT/tests/test_yr_today.py" \
        RadarRainRangesTest.test_table_uses_hourly_forecast_for_rows_without_radar

    [ "$status" -eq 0 ]
}

@test "headline distinguishes a strong shower from lingering light rain" {
    run uv run --project "$REPO_ROOT" python "$REPO_ROOT/tests/test_yr_today.py" \
        RadarRainRangesTest.test_headline_separates_strong_shower_from_lingering_light_rain

    [ "$status" -eq 0 ]
}
