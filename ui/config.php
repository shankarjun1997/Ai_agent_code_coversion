<?php
// UI configuration — reads from environment or defaults
define('API_BASE',    getenv('API_BASE_URL') ?: 'http://api:8000');
define('APP_TITLE',   'SQL-Gen Pipeline');
define('APP_VERSION', '2.0.0');

// Auth gate: every PHP page including this config will require a session
// EXCEPT the auth pages themselves (login.php, logout.php). They include
// auth.php directly and never load this file's gate.
if (!defined('STM_SKIP_AUTH_GATE')) {
    require_once __DIR__ . '/auth.php';
    stm_auth_require();
}

function _stm_auth_header(): string {
    if (function_exists('stm_auth_token')) {
        $t = stm_auth_token();
        if ($t) return "Authorization: Bearer $t\r\n";
    }
    return '';
}

function api_get(string $path, array $params = []): array {
    $url = API_BASE . $path;
    if ($params) $url .= '?' . http_build_query($params);
    $ctx = stream_context_create(['http' => [
        'header'  => _stm_auth_header(),
        'timeout' => 30,
        'ignore_errors' => true,
    ]]);
    $raw = @file_get_contents($url, false, $ctx);
    return $raw ? (json_decode($raw, true) ?? []) : [];
}

function api_post(string $path, array $body = []): array {
    $ctx = stream_context_create(['http' => [
        'method'  => 'POST',
        'header'  => "Content-Type: application/json\r\n" . _stm_auth_header(),
        'content' => json_encode($body),
        'timeout' => 60,
        'ignore_errors' => true,
    ]]);
    $raw = @file_get_contents(API_BASE . $path, false, $ctx);
    return $raw ? (json_decode($raw, true) ?? []) : [];
}

function stage_badge(string $stage): string {
    $colors = [
        'requirements'        => 'bg-blue-100 text-blue-800',
        'requirements_review' => 'bg-yellow-100 text-yellow-800',
        'mapping'             => 'bg-purple-100 text-purple-800',
        'mapping_review'      => 'bg-yellow-100 text-yellow-800',
        'engineering'         => 'bg-indigo-100 text-indigo-800',
        'engineering_review'  => 'bg-yellow-100 text-yellow-800',
        'qa'                  => 'bg-teal-100 text-teal-800',
        'qa_review'           => 'bg-yellow-100 text-yellow-800',
        'completed'           => 'bg-green-100 text-green-800',
        'failed'              => 'bg-red-100 text-red-800',
    ];
    $c = $colors[$stage] ?? 'bg-gray-100 text-gray-800';
    return "<span class=\"inline-block px-2 py-0.5 rounded text-xs font-medium $c\">$stage</span>";
}

function status_badge(string $status): string {
    $colors = [
        'running'        => 'bg-blue-500',
        'waiting_review' => 'bg-yellow-500',
        'completed'      => 'bg-green-500',
        'failed'         => 'bg-red-500',
    ];
    $c = $colors[$status] ?? 'bg-gray-400';
    return "<span class=\"inline-block w-2 h-2 rounded-full $c mr-1\"></span>$status";
}

function time_ago(string $iso): string {
    $diff = time() - strtotime($iso);
    if ($diff < 60)   return $diff . 's ago';
    if ($diff < 3600) return intval($diff/60) . 'm ago';
    if ($diff < 86400) return intval($diff/3600) . 'h ago';
    return intval($diff/86400) . 'd ago';
}
