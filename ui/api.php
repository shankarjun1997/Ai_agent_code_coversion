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

    default:
        http_response_code(400);
        echo json_encode(['error' => 'Unknown action']);
}
