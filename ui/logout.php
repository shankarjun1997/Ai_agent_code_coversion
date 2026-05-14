<?php
define('STM_SKIP_AUTH_GATE', true);
require_once __DIR__ . '/auth.php';
stm_auth_logout();
header('Location: /login.php');
exit;
