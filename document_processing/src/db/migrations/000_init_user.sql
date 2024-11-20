-- 000_init_user.sql - Part 1: Initial Setup
-- Handles role creation, database setup and base permissions

-- Run as superuser
DO $$
BEGIN
    IF NOT (SELECT usesuper FROM pg_user WHERE usename = current_user) THEN
        RAISE EXCEPTION 'Must run as superuser';
    END IF;
END
$$;

-- Create role if not exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'claimsuser') THEN
        CREATE ROLE claimsuser WITH 
            LOGIN
            PASSWORD 'Claims2024#Secure!'
            NOSUPERUSER
            INHERIT
            CREATEDB  -- Needed for test database creation
            NOCREATEROLE;
        
        -- Grant necessary permissions
        GRANT CONNECT ON DATABASE postgres TO claimsuser;
        RAISE NOTICE 'Role claimsuser created successfully';
    ELSE
        RAISE NOTICE 'Role claimsuser already exists';
    END IF;
END
$$;

-- Database creation and ownership
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'claimsdb_test') THEN
        -- Create test database owned by claimsuser
        CREATE DATABASE claimsdb_test
            WITH 
            OWNER = claimsuser
            ENCODING = 'UTF8'
            LC_COLLATE = 'en_US.utf8'
            LC_CTYPE = 'en_US.utf8'
            TEMPLATE = template0;
            
        RAISE NOTICE 'Database claimsdb_test created successfully';
    ELSE
        RAISE NOTICE 'Database claimsdb_test already exists';
        -- Ensure ownership
        ALTER DATABASE claimsdb_test OWNER TO claimsuser;
    END IF;
END
$$;
-- 000_init_user.sql - Part 2: Create Core Tables
-- Switch to test database context
\c claimsdb_test;

-- Create extension if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS hstore;

-- Create users table - prerequisite for institutions
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE tablename = 'users') THEN
        CREATE TABLE users (
            user_id SERIAL PRIMARY KEY,
            full_name VARCHAR(100) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            is_active BOOLEAN DEFAULT true,
            last_login TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        
        ALTER TABLE users OWNER TO claimsuser;
        CREATE INDEX idx_users_email ON users(email);
        
        RAISE NOTICE 'Table users created successfully';
    END IF;
END
$$;

-- Create members table - prerequisite for claims
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE tablename = 'members') THEN
        CREATE TABLE members (
            id SERIAL PRIMARY KEY,
            member_id VARCHAR(50) UNIQUE NOT NULL,
            full_name VARCHAR(100) NOT NULL,
            date_of_birth DATE NOT NULL,
            gender VARCHAR(10),
            contact_number VARCHAR(20),
            email VARCHAR(255),
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        
        ALTER TABLE members OWNER TO claimsuser;
        CREATE INDEX idx_members_member_id ON members(member_id);
        
        RAISE NOTICE 'Table members created successfully';
    END IF;
END
$$;
-- 000_init_user.sql - Part 3: Additional Core Tables

-- Create employers table
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE tablename = 'employers') THEN
        CREATE TABLE employers (
            employer_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            contact_information TEXT,
            address TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        
        ALTER TABLE employers OWNER TO claimsuser;
        CREATE INDEX idx_employers_name ON employers(name);
        
        RAISE NOTICE 'Table employers created successfully';
    END IF;
END
$$;

-- Create claims base table
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE tablename = 'claims') THEN
        CREATE TABLE claims (
            claim_id VARCHAR(50) PRIMARY KEY,
            member_id VARCHAR(50) REFERENCES members(member_id),
            claim_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            claim_type VARCHAR(50) NOT NULL,
            total_amount NUMERIC(15,2) NOT NULL,
            status VARCHAR(20) DEFAULT 'PENDING',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER REFERENCES users(user_id),
            updated_by INTEGER REFERENCES users(user_id)
        );
        
        ALTER TABLE claims OWNER TO claimsuser;
        CREATE INDEX idx_claims_member_id ON claims(member_id);
        CREATE INDEX idx_claims_status ON claims(status);
        
        RAISE NOTICE 'Table claims created successfully';
    END IF;
END
$$;

-- Create documents table
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE tablename = 'documents') THEN
        CREATE TABLE documents (
            document_id VARCHAR(50) PRIMARY KEY,
            claim_id VARCHAR(50) REFERENCES claims(claim_id),
            document_type VARCHAR(50) NOT NULL,
            storage_path TEXT NOT NULL,
            upload_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            verification_status VARCHAR(20) DEFAULT 'PENDING',
            verified_by INTEGER REFERENCES users(user_id),
            verification_notes TEXT,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        
        ALTER TABLE documents OWNER TO claimsuser;
        CREATE INDEX idx_documents_claim_id ON documents(claim_id);
        
        RAISE NOTICE 'Table documents created successfully';
    END IF;
END
$$;
-- 000_init_user.sql - Part 4: Final Tables and Permissions

-- Create processing_history table
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE tablename = 'processing_history') THEN
        CREATE TABLE processing_history (
            history_id SERIAL PRIMARY KEY,
            claim_id VARCHAR(50) REFERENCES claims(claim_id),
            stage VARCHAR(50) NOT NULL,
            action TEXT,
            actor_id INTEGER REFERENCES users(user_id),
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            result VARCHAR(50),
            details JSONB
        );
        
        ALTER TABLE processing_history OWNER TO claimsuser;
        CREATE INDEX idx_processing_history_claim_id ON processing_history(claim_id);
        
        RAISE NOTICE 'Table processing_history created successfully';
    END IF;
END
$$;

-- Create audit_logs table
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE tablename = 'audit_logs') THEN
        CREATE TABLE audit_logs (
            log_id SERIAL PRIMARY KEY,
            table_name VARCHAR(50) NOT NULL,
            record_id VARCHAR(50) NOT NULL,
            action VARCHAR(20) NOT NULL,
            old_values JSONB,
            new_values JSONB,
            changed_by VARCHAR(50),
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        
        ALTER TABLE audit_logs OWNER TO claimsuser;
        CREATE INDEX idx_audit_logs_table_action ON audit_logs(table_name, action);
        
        RAISE NOTICE 'Table audit_logs created successfully';
    END IF;
END
$$;

-- Create philhealthbenefits table
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE tablename = 'philhealthbenefits') THEN
        CREATE TABLE philhealthbenefits (
            benefit_id SERIAL PRIMARY KEY,
            claim_id VARCHAR(50) REFERENCES claims(claim_id),
            membership_number VARCHAR(50),
            membership_status VARCHAR(20),
            case_rate_code VARCHAR(50),
            total_benefit NUMERIC(15,2),
            hospital_share NUMERIC(15,2),
            professional_fee_share NUMERIC(15,2),
            calculation_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            override_notes TEXT
        );
        
        ALTER TABLE philhealthbenefits OWNER TO claimsuser;
        CREATE INDEX idx_philhealthbenefits_claim_id ON philhealthbenefits(claim_id);
        
        RAISE NOTICE 'Table philhealthbenefits created successfully';
    END IF;
END
$$;

-- Final permissions setup
DO $$
BEGIN
    -- Grant schema permissions
    GRANT USAGE, CREATE ON SCHEMA public TO claimsuser;
    
    -- Grant table permissions
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO claimsuser;
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO claimsuser;
    
    -- Grant future table permissions
    ALTER DEFAULT PRIVILEGES IN SCHEMA public 
    GRANT ALL PRIVILEGES ON TABLES TO claimsuser;
    
    ALTER DEFAULT PRIVILEGES IN SCHEMA public 
    GRANT ALL PRIVILEGES ON SEQUENCES TO claimsuser;
    
    RAISE NOTICE 'Final permissions granted successfully';
END
$$;

-- Verify setup
DO $$
DECLARE
    table_count INT;
BEGIN
    SELECT COUNT(*) INTO table_count 
    FROM pg_tables 
    WHERE schemaname = 'public' 
    AND tableowner = 'claimsuser';
    
    RAISE NOTICE 'Setup complete. Total tables owned by claimsuser: %', table_count;
END
$$;