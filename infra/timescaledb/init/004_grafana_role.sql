\getenv grafana_password DB_PASS_GRAFANA

SELECT format('CREATE ROLE wlm_grafana LOGIN PASSWORD %L', :'grafana_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wlm_grafana')
\gexec

ALTER ROLE wlm_grafana
  WITH LOGIN PASSWORD :'grafana_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

SELECT format('GRANT CONNECT ON DATABASE %I TO wlm_grafana', current_database())
\gexec
GRANT USAGE ON SCHEMA public TO wlm_grafana;
GRANT SELECT ON measurements, device_status, devices, ground_truth_events TO wlm_grafana;
