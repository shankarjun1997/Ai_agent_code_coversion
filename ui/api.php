<?php
/**
 * PHP form handler — proxies form submissions to the FastAPI backend.
 * Handles: trigger, approve, reject, iterate.
 */
require_once __DIR__ . '/config.php';

$action = $_POST['action'] ?? $_GET['action'] ?? '';

switch ($action) {
    case 'trigger':
        $body = [];
        if (!empty($_POST['jira_issue_key'])) $body['jira_issue_key'] = trim($_POST['jira_issue_key']);
        if (!empty($_POST['raw_input']))       $body['raw_input']      = trim($_POST['raw_input']);
        if (!empty($_POST['legacy_code']))     $body['legacy_code']    = trim($_POST['legacy_code']);
        if (!empty($_POST['legacy_dialect']))  $body['legacy_dialect'] = trim($_POST['legacy_dialect']);

        $result = api_post('/api/pipeline/trigger', $body);
        if (!empty($result['run_id'])) {
            header('Location: /pages/pipelines.php?run_id=' . urlencode($result['run_id']));
        } else {
            header('Location: /index.php?error=' . urlencode(json_encode($result)));
        }
        exit;

    case 'approve':
        $run_id   = trim($_POST['run_id'] ?? '');
        $reviewer = trim($_POST['reviewer'] ?? 'reviewer');
        $notes    = trim($_POST['notes'] ?? '');
        api_post("/api/pipeline/runs/$run_id/approve", compact('reviewer', 'notes'));
        header('Location: /pages/pipelines.php?run_id=' . urlencode($run_id) . '&msg=approved');
        exit;

    case 'reject':
        $run_id   = trim($_POST['run_id'] ?? '');
        $reviewer = trim($_POST['reviewer'] ?? 'reviewer');
        $notes    = trim($_POST['notes'] ?? '');
        api_post("/api/pipeline/runs/$run_id/reject", compact('reviewer', 'notes'));
        header('Location: /pages/pipelines.php?run_id=' . urlencode($run_id) . '&msg=rejected');
        exit;

    case 'sources_register_jira':
        $body = [
            'label'       => trim($_POST['label']       ?? ''),
            'base_url'    => trim($_POST['base_url']    ?? ''),
            'email'       => trim($_POST['email']       ?? ''),
            'api_token'   => trim($_POST['api_token']   ?? ''),
            'project_key' => trim($_POST['project_key'] ?? '') ?: null,
        ];
        $r = api_post('/api/discovery/profiles/jira', $body);
        $loc = '/pages/sources.php?tab=jira';
        if (!empty($r['id'])) {
            $loc .= '&msg=' . urlencode("Jira profile {$r['id']} registered.");
        } else {
            $loc .= '&err=' . urlencode(is_array($r) ? json_encode($r) : (string)$r);
        }
        header("Location: $loc"); exit;

    case 'sources_register_bq':
        $body = [
            'label'             => trim($_POST['label']             ?? ''),
            'project_id'        => trim($_POST['project_id']        ?? ''),
            'credentials_json'  => trim($_POST['credentials_json']  ?? '') ?: null,
        ];
        $r = api_post('/api/discovery/profiles/bigquery', $body);
        $loc = '/pages/sources.php?tab=bigquery';
        if (!empty($r['id'])) {
            $loc .= '&msg=' . urlencode("BigQuery profile {$r['id']} registered.");
        } else {
            $loc .= '&err=' . urlencode(is_array($r) ? json_encode($r) : (string)$r);
        }
        header("Location: $loc"); exit;

    case 'sources_register_db':
        $dialect = trim($_POST['dialect'] ?? 'postgres');
        $label   = trim($_POST['label'] ?? '');
        $dsn     = trim($_POST['dsn'] ?? '');
        if ($dialect === 'postgres') {
            $r = api_post('/api/discovery/profiles/postgres', compact('label','dsn'));
        } elseif ($dialect === 'oracle') {
            $r = api_post('/api/discovery/profiles/oracle', compact('label','dsn'));
        } else {
            // mysql / mssql expect host/port/db/user/password — we accept raw DSN and parse host
            $r = api_post("/api/discovery/profiles/{$dialect}", [
                'label' => $label,
                'host'  => parse_url($dsn, PHP_URL_HOST) ?: $dsn,
                'port'  => parse_url($dsn, PHP_URL_PORT) ?: ($dialect === 'mssql' ? 1433 : 3306),
                'db'    => ltrim(parse_url($dsn, PHP_URL_PATH) ?? '/', '/'),
                'user'  => parse_url($dsn, PHP_URL_USER) ?: '',
                'password' => parse_url($dsn, PHP_URL_PASS) ?: '',
            ]);
        }
        $loc = '/pages/sources.php?tab=db';
        if (!empty($r['profile']) || !empty($r['id'])) {
            $id = $r['profile']['id'] ?? $r['id'];
            $loc .= '&msg=' . urlencode("{$dialect} profile {$id} registered.");
        } else {
            $loc .= '&err=' . urlencode(is_array($r) ? json_encode($r) : (string)$r);
        }
        header("Location: $loc"); exit;

    case 'sources_ping':
        $id  = trim($_POST['id'] ?? '');
        $tab = trim($_POST['tab'] ?? 'jira');
        $r = api_post("/api/discovery/profiles/{$id}/ping", []);
        $loc = "/pages/sources.php?tab={$tab}";
        if (!empty($r['ok']) && $r['ok'] === true) {
            $msg = "Ping OK";
            if (!empty($r['latency_ms'])) $msg .= " ({$r['latency_ms']}ms)";
            if (!empty($r['message']))    $msg .= " — " . $r['message'];
            $loc .= '&msg=' . urlencode($msg);
        } else {
            $loc .= '&err=' . urlencode("Ping failed: " . ($r['detail'] ?? json_encode($r)));
        }
        header("Location: $loc"); exit;

    case 'sources_delete':
        $id  = trim($_POST['id'] ?? '');
        $tab = trim($_POST['tab'] ?? 'jira');
        $ctx = stream_context_create(['http' => [
            'method'  => 'DELETE',
            'timeout' => 10,
            'ignore_errors' => true,
        ]]);
        @file_get_contents(API_BASE . "/api/discovery/profiles/{$id}", false, $ctx);
        header("Location: /pages/sources.php?tab={$tab}&msg=" . urlencode("Profile {$id} deleted.")); exit;

    default:
        http_response_code(400);
        echo json_encode(['error' => 'Unknown action']);
}
