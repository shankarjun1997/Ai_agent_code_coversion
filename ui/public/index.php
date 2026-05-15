<?php
// Health / root redirect
header('Content-Type: application/json');
echo json_encode(['status' => 'ok', 'service' => 'sqlgen-ui']);
