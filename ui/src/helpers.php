<?php
// Internal API URL (container-to-container)
define('API_INTERNAL', getenv('API_BASE_URL') ?: 'http://api:8000');
// External API URL (browser → host port)
define('API_EXTERNAL', getenv('API_BASE_URL_EXTERNAL') ?: 'http://localhost:8000');

/**
 * Make a GET request to the internal API.
 * Returns decoded array or throws RuntimeException on failure.
 */
function api_get(string $path): array {
    $url = API_INTERNAL . $path;
    $ctx = stream_context_create(['http' => ['timeout' => 10, 'ignore_errors' => true]]);
    $body = @file_get_contents($url, false, $ctx);
    if ($body === false) {
        throw new RuntimeException("API unreachable: $path");
    }
    return json_decode($body, true) ?? [];
}

/**
 * POST JSON to the internal API.
 */
function api_post_json(string $path, array $payload): array {
    $url = API_INTERNAL . $path;
    $json = json_encode($payload);
    $ctx = stream_context_create(['http' => [
        'method'  => 'POST',
        'header'  => "Content-Type: application/json\r\nContent-Length: " . strlen($json),
        'content' => $json,
        'timeout' => 15,
        'ignore_errors' => true,
    ]]);
    $body = @file_get_contents($url, false, $ctx);
    if ($body === false) {
        throw new RuntimeException("API unreachable: $path");
    }
    return json_decode($body, true) ?? [];
}

/**
 * Render a view template inside the base layout.
 */
function render(string $view, array $data = []): string {
    extract($data, EXTR_SKIP);
    ob_start();
    include __DIR__ . '/../views/' . $view . '.php';
    $content = ob_get_clean();
    ob_start();
    include __DIR__ . '/../views/layout.php';
    return ob_get_clean();
}
