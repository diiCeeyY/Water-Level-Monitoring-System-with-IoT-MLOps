\getenv ingest_password DB_PASS_INGEST

SELECT format('CREATE ROLE wlm_ingest LOGIN PASSWORD %L', :'ingest_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wlm_ingest')
\gexec

ALTER ROLE wlm_ingest LOGIN PASSWORD :'ingest_password';
SELECT format('GRANT CONNECT ON DATABASE %I TO wlm_ingest', current_database())
\gexec
GRANT USAGE ON SCHEMA public TO wlm_ingest;
GRANT INSERT ON measurements, invalid_messages TO wlm_ingest;
GRANT SELECT (device_id, time, seq) ON measurements TO wlm_ingest;
GRANT INSERT, UPDATE ON device_status TO wlm_ingest;
GRANT SELECT (device_id, online, last_seen, last_seq, fw_version) ON device_status TO wlm_ingest;
