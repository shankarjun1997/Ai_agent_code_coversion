<?php
/**
 * Session/auth helper for PHP pages.
 *
 * stm_auth_require()       — redirect to /login.php if no valid session
 * stm_auth_user()          — return ['user_id','tenant_id','tenant_slug','role','email'] or null
 * stm_auth_token()         — return raw JWT or empty string
 * stm_auth_logout()        — clear session
 */
require_once __DIR__ . '/config.php';

if (session_status() === PHP_SESSION_NONE) {
    session_start();
}

function stm_auth_token(): string {
    return $_SESSION['jwt'] ?? '';
}

function stm_auth_user(): ?array {
    if (empty($_SESSION['user'])) return null;
    return $_SESSION['user'];
}

function stm_auth_require(): void {
    if (empty($_SESSION['jwt']) || empty($_SESSION['user'])) {
        // Preserve intended destination
        $next = $_SERVER['REQUEST_URI'] ?? '/index.php';
        header('Location: /login.php?next=' . urlencode($next));
        exit;
    }
}

function stm_auth_logout(): void {
    $_SESSION = [];
    session_destroy();
}

function stm_auth_login_with_token(string $jwt, array $userPayload): void {
    $_SESSION['jwt']  = $jwt;
    $_SESSION['user'] = $userPayload;
}
