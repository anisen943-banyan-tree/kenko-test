-- 1. Create new version for room rate updates
DO $$ 
DECLARE
    v_version_id INTEGER;
    v_category_id INTEGER;
    v_affected_rows INTEGER;
BEGIN
    -- Create new version
    SELECT create_config_version('2024.2', '2024-07-01', 'Mid-year update', 'admin') 
    INTO v_version_id;
    
    IF v_version_id IS NULL THEN
        RAISE EXCEPTION 'Failed to create version';
    END IF;

    -- Log version creation
    INSERT INTO audit_logs (
        action, 
        table_name, 
        record_id, 
        executed_by, 
        reason_code,
        reference_data,
        version_id
    ) VALUES (
        'Create Version',
        'config_versions',
        v_version_id,
        'admin',
        'ANNUAL_UPDATE',
        jsonb_build_object(
            'notes', 'Mid-year benefit adjustment',
            'effective_date', '2024-07-01'
        ),
        v_version_id
    );

    -- Validate and get room category
    SELECT id INTO v_category_id 
    FROM room_categories 
    WHERE category_code = 'SUITE';
    
    IF v_category_id IS NULL THEN
        RAISE EXCEPTION 'Room category SUITE not found or invalid';
    END IF;

    -- Update room rates
    UPDATE room_types 
    SET standard_rate = standard_rate * 1.1
    WHERE category_id = v_category_id;
    
    GET DIAGNOSTICS v_affected_rows = ROW_COUNT;
    
    IF v_affected_rows = 0 THEN
        RAISE WARNING 'No room rates were updated for category %', v_category_id;
    END IF;

EXCEPTION
    WHEN others THEN
        INSERT INTO error_logs (
            error_message, 
            action, 
            timestamp,
            context_data
        ) VALUES (
            SQLERRM, 
            'Room Rate Update', 
            CURRENT_TIMESTAMP AT TIME ZONE 'UTC',
            jsonb_build_object(
                'version_id', COALESCE(v_version_id, -1),
                'category_id', COALESCE(v_category_id, -1),
                'affected_rows', COALESCE(v_affected_rows, 0),
                'error_context', to_json(SQLSTATE)
            )
        );
        RAISE NOTICE 'Error occurred: % (Version: %, Category: %, State: %)', 
            SQLERRM, 
            COALESCE(v_version_id, 'NULL'), 
            COALESCE(v_category_id, 'NULL'),
            SQLSTATE;
        RAISE;
END $$;

-- Success notification
DO $$
BEGIN 
    RAISE NOTICE 'Room rate update completed successfully. % rows affected.', v_affected_rows;
END $$;

-- 2. View changes made in this version
SELECT * FROM compare_version_changes(
    (SELECT id FROM config_versions WHERE version_number = '2024.1'),
    (SELECT id FROM config_versions WHERE version_number = '2024.2')
);

-- 3. Generate summary report
SELECT * FROM vw_change_summaries 
WHERE version_number = '2024.2';

-- 4. Approve version if changes are acceptable
SELECT approve_config_version(
    (SELECT id FROM config_versions WHERE version_number = '2024.2'),
    'supervisor'
);

-- Function to generate summary report of changes
CREATE OR REPLACE FUNCTION generate_change_summary(p_version_id INTEGER) RETURNS TABLE (
    table_name TEXT,
    field_name TEXT,
    old_value TEXT,
    new_value TEXT,
    modified_by TEXT,
    modification_date TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT table_name, field_name, old_value, new_value, modified_by, modification_date
    FROM change_logs
    WHERE version_id = p_version_id;
END $$ LANGUAGE plpgsql;

-- Comparison function for versions
CREATE OR REPLACE FUNCTION compare_version_changes(v1_id INTEGER, v2_id INTEGER) RETURNS TABLE (
    table_name TEXT,
    field_name TEXT,
    v1_value TEXT,
    v2_value TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT c1.table_name, c1.field_name, c1.value AS v1_value, c2.value AS v2_value
    FROM change_logs c1
    JOIN change_logs c2 ON c1.table_name = c2.table_name AND c1.field_name = c2.field_name
    WHERE c1.version_id = v1_id AND c2.version_id = v2_id AND c1.value IS DISTINCT FROM c2.value;
END $$ LANGUAGE plpgsql;

-- Approval function
CREATE OR REPLACE FUNCTION approve_config_version(version_id INTEGER, approver TEXT) RETURNS VOID AS $$
BEGIN
    UPDATE config_versions
    SET status = 'Approved', approved_by = approver, approval_date = NOW()
    WHERE id = version_id;
    
    -- Log approval action
    INSERT INTO audit_logs (
        action, 
        table_name, 
        record_id, 
        executed_by, 
        reason_code, 
        version_id
    ) VALUES (
        'Approve Version',
        'config_versions',
        version_id,
        approver,
        'APPROVAL',
        version_id
    );
END $$ LANGUAGE plpgsql;