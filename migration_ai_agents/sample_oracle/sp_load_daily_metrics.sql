CREATE OR REPLACE PROCEDURE ONEFIBER.SP_LOAD_DAILY_METRICS(
    p_run_date IN DATE,
    p_status OUT VARCHAR2
)
IS
    v_row_count NUMBER := 0;
    v_err_code NUMBER;
    v_err_msg VARCHAR2(4000);
    v_start_ts TIMESTAMP := SYSTIMESTAMP;

    CURSOR c_source_data IS
        SELECT /*+ PARALLEL(4) */
            a.site_id,
            a.market_name,
            NVL(a.vendor_name, 'UNKNOWN') AS vendor_name,
            DECODE(a.status_code, 'A', 'Active', 'I', 'Inactive', 'Unknown') AS status_desc,
            TO_CHAR(a.created_date, 'YYYY-MM-DD') AS created_dt,
            TO_NUMBER(a.cost_amount) AS cost_amt,
            b.region_name,
            LISTAGG(c.task_name, ', ') WITHIN GROUP (ORDER BY c.task_seq) AS task_list
        FROM ONEFIBER_SCHEMA.SITE_MASTER a,
             ONEFIBER_SCHEMA.REGION_LOOKUP b,
             ONEFIBER_SCHEMA.TASK_DETAILS c
        WHERE a.region_id = b.region_id
          AND a.site_id = c.site_id(+)
          AND a.created_date >= ADD_MONTHS(SYSDATE, -12)
        GROUP BY a.site_id, a.market_name, a.vendor_name,
                 a.status_code, a.created_date, a.cost_amount, b.region_name;

BEGIN
    -- Truncate staging table
    EXECUTE IMMEDIATE 'TRUNCATE TABLE ONEFIBER_SCHEMA.DAILY_METRICS_STG';

    -- Load staging
    INSERT INTO ONEFIBER_SCHEMA.DAILY_METRICS_STG
    (site_id, market_name, vendor_name, status_desc, created_dt, cost_amt, region_name, task_list)
    SELECT site_id, market_name, vendor_name, status_desc, created_dt, cost_amt, region_name, task_list
    FROM TABLE(c_source_data);

    v_row_count := SQL%ROWCOUNT;
    DBMS_OUTPUT.PUT_LINE('Staging loaded: ' || v_row_count || ' rows');

    -- Merge into target
    MERGE INTO ONEFIBER_SCHEMA.DAILY_METRICS_FINAL t
    USING ONEFIBER_SCHEMA.DAILY_METRICS_STG s
    ON (t.site_id = s.site_id)
    WHEN MATCHED THEN
        UPDATE SET
            t.market_name = s.market_name,
            t.vendor_name = s.vendor_name,
            t.status_desc = s.status_desc,
            t.cost_amt = s.cost_amt,
            t.region_name = s.region_name,
            t.task_list = s.task_list,
            t.updated_date = SYSDATE
    WHEN NOT MATCHED THEN
        INSERT (site_id, market_name, vendor_name, status_desc, created_dt,
                cost_amt, region_name, task_list, created_date)
        VALUES (s.site_id, s.market_name, s.vendor_name, s.status_desc, s.created_dt,
                s.cost_amt, s.region_name, s.task_list, SYSDATE);

    v_row_count := SQL%ROWCOUNT;

    COMMIT;

    p_status := 'SUCCESS';
    DBMS_OUTPUT.PUT_LINE('Merge complete: ' || v_row_count || ' rows affected');

EXCEPTION
    WHEN OTHERS THEN
        v_err_code := SQLCODE;
        v_err_msg := SQLERRM;
        ROLLBACK;
        p_status := 'FAILED: ' || v_err_msg;
        DBMS_OUTPUT.PUT_LINE('Error: ' || v_err_code || ' - ' || v_err_msg);
        RAISE;
END SP_LOAD_DAILY_METRICS;
/
