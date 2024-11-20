-- Multi-Tenant Migration Script
-- Safety measures
-- Temporarily disable triggers and constraints
-- Ensure these changes are only applied in a safe environment
SET session_replication_role = 'replica';  
SET constraint_execution_limit = '0';      

-- Transaction wrapper
BEGIN;

-- Savepoint for initial setup
SAVEPOINT initial_setup;

-- 1. Create institutions table first
CREATE TABLE IF NOT EXISTS institutions (
    institution_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    address TEXT,
    contact_info JSONB,
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for institutions
CREATE INDEX idx_institutions_code ON institutions(code);
CREATE INDEX idx_institutions_status ON institutions(status) WHERE status = 'ACTIVE';

-- Savepoint after creating institutions table
SAVEPOINT institutions_created;

-- 2. Create institution_users mapping table
CREATE TABLE IF NOT EXISTS institution_users (
    id SERIAL PRIMARY KEY,
    institution_id INTEGER REFERENCES institutions(institution_id),
    user_id INTEGER REFERENCES users(user_id),
    role VARCHAR(50) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    access_level VARCHAR(20) DEFAULT 'STANDARD',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by INTEGER REFERENCES users(user_id),
    CONSTRAINT institution_users_unique UNIQUE(institution_id, user_id),
    CONSTRAINT valid_access_level CHECK (access_level IN ('STANDARD', 'ADMIN', 'RESTRICTED'))
);

-- Create indexes for institution_users
CREATE INDEX idx_institution_users_lookup ON institution_users(institution_id, user_id) WHERE is_active = true;
CREATE INDEX idx_institution_users_role ON institution_users(role);

-- Savepoint after creating institution_users table
SAVEPOINT institution_users_created;

-- 3. Add institution_id to existing tables
-- Add column with NOT NULL constraint deferred
ALTER TABLE employers 
ADD COLUMN institution_id INTEGER NOT NULL,
ADD CONSTRAINT fk_employers_institution FOREIGN KEY (institution_id) REFERENCES institutions(institution_id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE users 
ADD COLUMN institution_id INTEGER NOT NULL,
ADD CONSTRAINT fk_users_institution FOREIGN KEY (institution_id) REFERENCES institutions(institution_id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE claims 
ADD COLUMN institution_id UUID NOT NULL,
ADD CONSTRAINT fk_claims_institution FOREIGN KEY (institution_id) REFERENCES institutions(institution_id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE documents 
ADD COLUMN institution_id INTEGER NOT NULL,
ADD CONSTRAINT fk_documents_institution FOREIGN KEY (institution_id) REFERENCES institutions(institution_id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE processing_history 
ADD COLUMN institution_id INTEGER NOT NULL,
ADD CONSTRAINT fk_processing_history_institution FOREIGN KEY (institution_id) REFERENCES institutions(institution_id)
DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE philhealthbenefits 
ADD COLUMN institution_id INTEGER NOT NULL,
ADD CONSTRAINT fk_philhealthbenefits_institution FOREIGN KEY (institution_id) REFERENCES institutions(institution_id)
DEFERRABLE INITIALLY DEFERRED;

-- Savepoint after adding institution_id to existing tables
SAVEPOINT institution_id_added;

-- 4. Create a default institution for existing data
INSERT INTO institutions (name, code, status)
VALUES ('Default Institution', 'DEFAULT', 'ACTIVE')
RETURNING institution_id INTO default_institution_id;

-- Savepoint after creating default institution
SAVEPOINT default_institution_created;

-- 5. Update existing records with default institution
UPDATE employers SET institution_id = default_institution_id;
UPDATE users SET institution_id = default_institution_id;
UPDATE claims SET institution_id = default_institution_id;
UPDATE documents SET institution_id = default_institution_id;
UPDATE processing_history SET institution_id = default_institution_id;
UPDATE philhealthbenefits SET institution_id = default_institution_id;

-- Savepoint after updating records with default institution_id
SAVEPOINT default_institution_created;

-- Add default institution ID to existing records
UPDATE claims SET institution_id = 1 WHERE institution_id IS NULL;
UPDATE members SET institution_id = 1 WHERE institution_id IS NULL;
UPDATE documents SET institution_id = 1 WHERE institution_id IS NULL;

-- Savepoint after updating existing records
SAVEPOINT existing_records_updated;

-- 6. Now add foreign key constraints
-- Removed redundant constraints

-- Savepoint after adding foreign key constraints
SAVEPOINT foreign_keys_added;

-- 7. Create indexes for institutional queries
CREATE INDEX idx_employers_institution ON employers(institution_id);
CREATE INDEX idx_users_institution ON users(institution_id);
CREATE INDEX idx_claims_institution ON claims(institution_id);
CREATE INDEX idx_documents_institution ON documents(institution_id);
CREATE INDEX idx_processing_history_institution ON processing_history(institution_id);
CREATE INDEX idx_philhealthbenefits_institution ON philhealthbenefits(institution_id);

-- Additional indexes on institution_id
CREATE INDEX idx_claims_institution_id ON claims(institution_id);
CREATE INDEX idx_members_institution_id ON members(institution_id);
CREATE INDEX idx_documents_institution_id ON documents(institution_id);

-- Composite indexes for common query patterns
CREATE INDEX idx_claims_institution_id_claim_id ON claims(institution_id, claim_id);
CREATE INDEX idx_documents_institution_id_document_id ON documents(institution_id, document_id);
CREATE INDEX idx_claims_institution_status ON claims (institution_id, status);

-- Savepoint after creating indexes
SAVEPOINT indexes_created;

-- 8. Add institution-specific constraints
ALTER TABLE claims
ADD CONSTRAINT claims_institution_member_match
CHECK (
    institution_id = (
        SELECT institution_id 
        FROM members 
        WHERE members.id = claims.member_id
    )
);

-- Savepoint after adding institution-specific constraints
SAVEPOINT institution_constraints_added;

-- 9. Create audit trigger for institution changes
CREATE OR REPLACE FUNCTION audit_institution_changes()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit_logs (
        table_name,
        record_id,
        action,
        old_values,
        new_values,
        changed_by,
        institution_id
    ) VALUES (
        TG_TABLE_NAME,
        NEW.id,
        TG_OP,
        CASE WHEN TG_OP = 'UPDATE' THEN hstore(OLD) - hstore(NEW) END,
        row_to_json(NEW),
        current_user,
        NEW.institution_id
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER institutions_audit
AFTER INSERT OR UPDATE OR DELETE ON institutions
FOR EACH ROW EXECUTE FUNCTION audit_institution_changes();

-- Savepoint after creating audit trigger
SAVEPOINT audit_trigger_created;

-- 10. Create views for easier querying
CREATE OR REPLACE VIEW vw_institution_stats AS
SELECT 
    i.institution_id,
    i.name,
    i.code,
    i.status,
    COUNT(DISTINCT e.employer_id) AS employer_count,
    COUNT(DISTINCT c.claim_id) AS claim_count,
    COUNT(DISTINCT u.user_id) AS user_count
FROM institutions i
LEFT JOIN employers e ON e.institution_id = i.institution_id
LEFT JOIN claims c ON c.institution_id = i.institution_id
LEFT JOIN institution_users u ON u.institution_id = i.institution_id
GROUP BY i.institution_id, i.name, i.code, i.status;

CREATE OR REPLACE VIEW vw_active_claims_per_institution AS
SELECT 
    i.institution_id,
    i.name AS institution_name,
    COUNT(c.id) AS active_claim_count
FROM institutions i
LEFT JOIN claims c ON c.institution_id = i.institution_id AND c.status = 'ACTIVE'
GROUP BY i.institution_id, i.name;

CREATE OR REPLACE VIEW vw_user_activity_by_institution AS
SELECT 
    u.institution_id,
    i.name AS institution_name,
    u.user_id,
    u.last_login
FROM users u
LEFT JOIN institutions i ON u.institution_id = i.institution_id
WHERE u.last_login > CURRENT_DATE - INTERVAL '30 days';

-- Savepoint after creating views
SAVEPOINT views_created;

-- Verify institution_id in views
SELECT * FROM vw_institution_stats WHERE institution_id = 1;
SELECT * FROM vw_active_claims_per_institution WHERE institution_id = 1;
SELECT * FROM vw_user_activity_by_institution WHERE institution_id = 1;

-- Check for missing institution IDs
SELECT 'claims' AS table_name, COUNT(*) AS missing_institution
FROM claims WHERE institution_id IS NULL
UNION ALL
SELECT 'members', COUNT(*)
FROM members WHERE institution_id IS NULL
UNION ALL
SELECT 'documents', COUNT(*)
FROM documents WHERE institution_id IS NULL;

-- Ensure member entries are populated correctly
SELECT COUNT(*) AS invalid_members
FROM members
WHERE institution_id IS NULL;

-- Check for invalid institution references
SELECT 'claims' AS table_name, COUNT(*) AS invalid_references
FROM claims c
LEFT JOIN institutions i ON c.institution_id = i.institution_id
WHERE i.institution_id IS NULL
UNION ALL
SELECT 'members', COUNT(*)
FROM members m
LEFT JOIN institutions i ON m.institution_id = i.institution_id
WHERE i.institution_id IS NULL;

-- Check if all claims link to valid institutions through members
SELECT COUNT(*) AS mismatched_institutions
FROM claims c
JOIN members m ON c.member_id = m.id
WHERE c.institution_id <> m.institution_id;

-- Ensure all users and documents link to a valid institution
SELECT COUNT(*) AS unmapped_users
FROM users
WHERE institution_id IS NULL;

SELECT COUNT(*) AS unmapped_documents
FROM documents
WHERE institution_id IS NULL;

-- Verify audit triggers for institution changes
SELECT * FROM audit_log WHERE table_name = 'institutions' AND action IN ('INSERT', 'UPDATE', 'DELETE');

-- Verify audit entries for DELETE and INSERT actions
SELECT * FROM audit_log WHERE table_name = 'institutions' AND action IN ('INSERT', 'DELETE');

-- Validate role and access levels in institution_users
SELECT * FROM institution_users
WHERE role NOT IN ('STANDARD', 'ADMIN', 'RESTRICTED')
OR access_level NOT IN ('STANDARD', 'ADMIN', 'RESTRICTED');

-- Re-enable triggers and constraints
SET session_replication_role = 'origin';
SET constraint_execution_limit = '1';

-- Commit transaction
COMMIT;

EXPLAIN ANALYZE
SELECT * FROM claims WHERE institution_id = 1;

-- Test composite index on claims for institution and claim_id
EXPLAIN ANALYZE 
SELECT * FROM claims WHERE institution_id = 1 AND claim_id = 123;

-- Rollback script
BEGIN;

-- Remove `institution_id` columns from tables
ALTER TABLE employers DROP COLUMN IF EXISTS institution_id;
ALTER TABLE users DROP COLUMN IF EXISTS institution_id;
ALTER TABLE claims DROP COLUMN IF EXISTS institution_id;
ALTER TABLE documents DROP COLUMN IF EXISTS institution_id;
ALTER TABLE processing_history DROP COLUMN IF EXISTS institution_id;
ALTER TABLE philhealthbenefits DROP COLUMN IF EXISTS institution_id;

-- Drop `institutions` and `institution_users` tables
DROP TABLE IF EXISTS institutions;
DROP TABLE IF EXISTS institution_users;

-- Remove constraints
ALTER TABLE employers DROP CONSTRAINT IF EXISTS fk_employers_institution;
ALTER TABLE users DROP CONSTRAINT IF EXISTS fk_users_institution;
ALTER TABLE claims DROP CONSTRAINT IF EXISTS fk_claims_institution;
ALTER TABLE documents DROP CONSTRAINT IF EXISTS fk_documents_institution;
ALTER TABLE processing_history DROP CONSTRAINT IF EXISTS fk_processing_history_institution;
ALTER TABLE philhealthbenefits DROP CONSTRAINT IF EXISTS fk_philhealthbenefits_institution;

-- Remove views created during migration
DROP VIEW IF EXISTS vw_institution_stats;
DROP VIEW IF EXISTS vw_active_claims_per_institution;
DROP VIEW IF EXISTS vw_user_activity_by_institution;

-- Drop audit trigger and function
DROP TRIGGER IF EXISTS institutions_audit ON institutions;
DROP FUNCTION IF EXISTS audit_institution_changes;

-- Restore original session and constraint settings
SET session_replication_role = 'origin';
COMMIT;
