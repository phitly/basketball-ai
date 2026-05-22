-- =============================================================================
-- Basketball Analytics Engine — PostgreSQL Schema
-- Phase 1: Data Foundation
-- =============================================================================
-- Design notes:
--   • NBA native IDs are used throughout (team_id/player_id are integers from
--     the NBA API; game_id is a 10-char string like '0022300001').
--   • possessions is a DERIVED table — rows are computed from play_events,
--     not ingested directly from the API.
--   • defender_distance on shots is only available for SportVU-era data
--     (2013-14 onward) and is nullable for older seasons.
--   • All timestamps are stored in UTC.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Extensions
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- =============================================================================
-- Reference / Dimension Tables
-- =============================================================================

-- -----------------------------------------------------------------------------
-- teams
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teams (
    team_id         INTEGER         PRIMARY KEY,   -- NBA native team ID
    abbreviation    VARCHAR(5)      NOT NULL,
    name            VARCHAR(100)    NOT NULL,       -- e.g. "Boston Celtics"
    city            VARCHAR(100)    NOT NULL,
    conference      VARCHAR(10)     NOT NULL CHECK (conference IN ('East', 'West')),
    division        VARCHAR(50)     NOT NULL,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_teams_abbreviation ON teams(abbreviation);


-- -----------------------------------------------------------------------------
-- players
-- NOTE: team_id reflects the player's CURRENT team as of last ingest.
--       Historical team affiliations are captured via play_events and lineups.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS players (
    player_id       INTEGER         PRIMARY KEY,   -- NBA native player ID
    first_name      VARCHAR(100)    NOT NULL,
    last_name       VARCHAR(100)    NOT NULL,
    full_name       VARCHAR(200)    GENERATED ALWAYS AS (first_name || ' ' || last_name) STORED,
    position        VARCHAR(20),                   -- PG, SG, SF, PF, C, G, F, G-F, F-C ...
    height_inches   SMALLINT,
    weight_lbs      SMALLINT,
    birth_date      DATE,
    team_id         INTEGER         REFERENCES teams(team_id) ON DELETE SET NULL,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_players_team_id   ON players(team_id);
CREATE INDEX IF NOT EXISTS idx_players_last_name ON players(last_name);
CREATE INDEX IF NOT EXISTS idx_players_is_active ON players(is_active);


-- =============================================================================
-- Fact Tables
-- =============================================================================

-- -----------------------------------------------------------------------------
-- games
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS games (
    game_id         VARCHAR(12)     PRIMARY KEY,   -- NBA game ID, e.g. '0022300001'
    game_date       DATE            NOT NULL,
    season          VARCHAR(10)     NOT NULL,       -- e.g. '2023-24'
    season_type     VARCHAR(20)     NOT NULL DEFAULT 'Regular Season',
                                                    -- 'Regular Season' | 'Playoffs' | 'Pre Season'
    home_team_id    INTEGER         NOT NULL REFERENCES teams(team_id),
    away_team_id    INTEGER         NOT NULL REFERENCES teams(team_id),
    home_score      SMALLINT,                       -- NULL until game is final
    away_score      SMALLINT,
    status          VARCHAR(20)     NOT NULL DEFAULT 'Final',
    arena           VARCHAR(100),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_different_teams CHECK (home_team_id <> away_team_id)
);

CREATE INDEX IF NOT EXISTS idx_games_season       ON games(season);
CREATE INDEX IF NOT EXISTS idx_games_game_date    ON games(game_date);
CREATE INDEX IF NOT EXISTS idx_games_home_team_id ON games(home_team_id);
CREATE INDEX IF NOT EXISTS idx_games_away_team_id ON games(away_team_id);


-- -----------------------------------------------------------------------------
-- play_events
-- Raw play-by-play rows from NBA API (PlayByPlayV2 / PlayByPlayV3).
-- This table is the source of truth; possessions are derived from it.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS play_events (
    event_id        BIGSERIAL       PRIMARY KEY,
    game_id         VARCHAR(12)     NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    event_num       INTEGER         NOT NULL,       -- original sequence number from NBA API
    period          SMALLINT        NOT NULL CHECK (period BETWEEN 1 AND 10),
    game_clock      VARCHAR(10)     NOT NULL,       -- e.g. '05:32' (MM:SS remaining in period)
    wall_clock      TIMESTAMPTZ,                    -- real-world timestamp if available
    event_type      VARCHAR(50)     NOT NULL,       -- FIELD_GOAL_MADE, TURNOVER, FOUL, etc.
    event_subtype   VARCHAR(50),
    player1_id      INTEGER         REFERENCES players(player_id),
    player1_team_id INTEGER         REFERENCES teams(team_id),
    player2_id      INTEGER         REFERENCES players(player_id),   -- e.g. assister
    player2_team_id INTEGER         REFERENCES teams(team_id),
    player3_id      INTEGER         REFERENCES players(player_id),   -- e.g. fouled player
    player3_team_id INTEGER         REFERENCES teams(team_id),
    description     TEXT,
    home_score      SMALLINT,                       -- running score at time of event
    away_score      SMALLINT,
    score_margin    SMALLINT        GENERATED ALWAYS AS (home_score - away_score) STORED,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_play_events_game_event UNIQUE (game_id, event_num)
);

CREATE INDEX IF NOT EXISTS idx_play_events_game_id    ON play_events(game_id);
CREATE INDEX IF NOT EXISTS idx_play_events_player1    ON play_events(player1_id);
CREATE INDEX IF NOT EXISTS idx_play_events_event_type ON play_events(event_type);
CREATE INDEX IF NOT EXISTS idx_play_events_period     ON play_events(game_id, period);


-- -----------------------------------------------------------------------------
-- shots
-- One row per shot attempt. Source: ShotChartDetail endpoint.
-- NOTE: defender_distance requires SportVU / tracking data (2013-14+).
--       It is NULL for seasons where tracking was unavailable.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shots (
    shot_id             BIGSERIAL       PRIMARY KEY,
    game_id             VARCHAR(12)     NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    player_id           INTEGER         NOT NULL REFERENCES players(player_id),
    team_id             INTEGER         NOT NULL REFERENCES teams(team_id),
    period              SMALLINT        NOT NULL CHECK (period BETWEEN 1 AND 10),
    game_clock          VARCHAR(10)     NOT NULL,   -- MM:SS remaining
    shot_type           VARCHAR(10)     NOT NULL CHECK (shot_type IN ('2PT', '3PT')),
    action_type         VARCHAR(100),               -- e.g. 'Jump Shot', 'Layup', 'Dunk'
    shot_zone_basic     VARCHAR(50),                -- e.g. 'Mid-Range', 'Restricted Area'
    shot_zone_area      VARCHAR(50),                -- e.g. 'Left Side', 'Center'
    shot_zone_range     VARCHAR(50),                -- e.g. '8-16 ft.', '24+ ft.'
    shot_distance       SMALLINT,                   -- in feet
    x_coord             SMALLINT,                   -- court coordinates (tenths of a foot)
    y_coord             SMALLINT,
    made                BOOLEAN         NOT NULL,
    defender_distance   NUMERIC(4,1),               -- feet; NULL pre-tracking era — see NOTE above
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_shots_game_id    ON shots(game_id);
CREATE INDEX IF NOT EXISTS idx_shots_player_id  ON shots(player_id);
CREATE INDEX IF NOT EXISTS idx_shots_team_id    ON shots(team_id);
CREATE INDEX IF NOT EXISTS idx_shots_made       ON shots(made);
CREATE INDEX IF NOT EXISTS idx_shots_zone       ON shots(shot_zone_basic);


-- -----------------------------------------------------------------------------
-- possessions
-- DERIVED TABLE — rows are computed by the ETL transform layer from play_events.
-- Not ingested directly from the NBA API.
-- Each row represents one offensive possession for a team.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS possessions (
    possession_id       BIGSERIAL       PRIMARY KEY,
    game_id             VARCHAR(12)     NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    team_id             INTEGER         NOT NULL REFERENCES teams(team_id),
    period              SMALLINT        NOT NULL CHECK (period BETWEEN 1 AND 10),
    start_event_id      BIGINT          REFERENCES play_events(event_id),
    end_event_id        BIGINT          REFERENCES play_events(event_id),
    start_game_clock    VARCHAR(10),    -- MM:SS at possession start
    end_game_clock      VARCHAR(10),    -- MM:SS at possession end
    duration_seconds    NUMERIC(5,1),
    outcome             VARCHAR(30)     NOT NULL,
                                        -- 'made_2', 'made_3', 'missed_shot',
                                        -- 'turnover', 'free_throw_trip', 'end_of_period'
    points_scored       SMALLINT        NOT NULL DEFAULT 0,
    is_transition       BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_possessions_game_id  ON possessions(game_id);
CREATE INDEX IF NOT EXISTS idx_possessions_team_id  ON possessions(team_id);
CREATE INDEX IF NOT EXISTS idx_possessions_outcome  ON possessions(outcome);
CREATE INDEX IF NOT EXISTS idx_possessions_period   ON possessions(game_id, period);


-- -----------------------------------------------------------------------------
-- lineups
-- Five-man unit stints. Derived from play_events by tracking substitutions.
-- player_ids is a sorted INTEGER array for consistent deduplication.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lineups (
    lineup_id           BIGSERIAL       PRIMARY KEY,
    game_id             VARCHAR(12)     NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    team_id             INTEGER         NOT NULL REFERENCES teams(team_id),
    player_ids          INTEGER[]       NOT NULL,   -- always sorted ASC for deduplication
    period              SMALLINT        NOT NULL CHECK (period BETWEEN 1 AND 10),
    start_game_clock    VARCHAR(10),
    end_game_clock      VARCHAR(10),
    time_on_seconds     NUMERIC(6,1),
    points_for          SMALLINT        NOT NULL DEFAULT 0,
    points_against      SMALLINT        NOT NULL DEFAULT 0,
    plus_minus          SMALLINT        GENERATED ALWAYS AS (points_for - points_against) STORED,
    possessions_on      SMALLINT        NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lineups_game_id  ON lineups(game_id);
CREATE INDEX IF NOT EXISTS idx_lineups_team_id  ON lineups(team_id);
CREATE INDEX IF NOT EXISTS idx_lineups_players  ON lineups USING GIN (player_ids);


-- =============================================================================
-- Pipeline Observability
-- =============================================================================

-- -----------------------------------------------------------------------------
-- pipeline_runs
-- One row per ETL execution. Use this to track what has been ingested,
-- detect gaps, and support idempotent re-runs.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_type        VARCHAR(50)     NOT NULL,   -- 'games', 'play_events', 'shots', etc.
    season          VARCHAR(10),
    game_id         VARCHAR(12),                -- NULL for season-level runs
    status          VARCHAR(20)     NOT NULL DEFAULT 'running'
                                    CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    rows_ingested   INTEGER,
    error_message   TEXT,
    started_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_run_type ON pipeline_runs(run_type);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status   ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_season   ON pipeline_runs(season);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_game_id  ON pipeline_runs(game_id);
