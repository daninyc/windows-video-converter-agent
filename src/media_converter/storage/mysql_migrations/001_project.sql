CREATE TABLE IF NOT EXISTS project_meta (name VARCHAR(64) PRIMARY KEY,value VARCHAR(128) NOT NULL);
CREATE TABLE IF NOT EXISTS technical_rules (rule_id VARCHAR(100) PRIMARY KEY,rule_kind VARCHAR(80),format_name VARCHAR(40),codec VARCHAR(80),error_code VARCHAR(80),version BIGINT NOT NULL,source_ref JSON NOT NULL,rule_json JSON NOT NULL);
CREATE TABLE IF NOT EXISTS presets (instance_id VARCHAR(64) NOT NULL,preset_id VARCHAR(64) NOT NULL,version BIGINT NOT NULL,name VARCHAR(100),container VARCHAR(16),settings_json JSON NOT NULL,PRIMARY KEY(instance_id,preset_id));
CREATE TABLE IF NOT EXISTS conversion_attempts (instance_id VARCHAR(64) NOT NULL,attempt_id VARCHAR(64) NOT NULL,asset_id VARCHAR(64),status VARCHAR(32),version BIGINT NOT NULL,payload JSON NOT NULL,updated_at VARCHAR(40),PRIMARY KEY(instance_id,attempt_id),INDEX status_time(instance_id,status,updated_at));
CREATE TABLE IF NOT EXISTS sync_events (instance_id VARCHAR(64) NOT NULL,event_id BIGINT NOT NULL,PRIMARY KEY(instance_id,event_id));
CREATE TABLE IF NOT EXISTS sync_state (instance_id VARCHAR(64) PRIMARY KEY,watermark BIGINT NOT NULL,data_time VARCHAR(40));
