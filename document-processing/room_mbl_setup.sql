-- Part 1: Core Tables and Structure
-- Comprehensive Benefits Schema with Edge Conditions for Claims Adjudication

-- Core Categories and Base Structure
CREATE TABLE benefit_categories (
    id SERIAL PRIMARY KEY,
    category_code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    parent_category_id INTEGER REFERENCES benefit_categories(id),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE benefits (
    id SERIAL PRIMARY KEY,
    category_id INTEGER REFERENCES benefit_categories(id),
    benefit_code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    coverage_type VARCHAR(50) NOT NULL,
    limit_type VARCHAR(50) NOT NULL,
    limit_value NUMERIC,
    limit_period VARCHAR(50),
    requires_preauth BOOLEAN DEFAULT false,
    philhealth_eligible BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_coverage CHECK (coverage_type IN ('FULL', 'PARTIAL', 'UP_TO_LIMIT', 'NOT_COVERED'))
);

-- Benefit Conditions Table
CREATE TABLE benefit_conditions (
    id SERIAL PRIMARY KEY,
    benefit_id INTEGER REFERENCES benefits(id),
    condition_type VARCHAR(50) NOT NULL,
    operator VARCHAR(20) NOT NULL,
    value JSONB NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Benefit Sublimits Table
CREATE TABLE benefit_sublimits (
    id SERIAL PRIMARY KEY,
    benefit_id INTEGER REFERENCES benefits(id),
    sublimit_type VARCHAR(50) NOT NULL,
    amount NUMERIC NOT NULL,
    period VARCHAR(50),
    max_occurrences INTEGER,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Benefit Exclusions Table
CREATE TABLE benefit_exclusions (
    id SERIAL PRIMARY KEY,
    benefit_id INTEGER REFERENCES benefits(id),
    exclusion_code VARCHAR(50),
    description TEXT,
    is_absolute BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Cumulative Limits Table
CREATE TABLE cumulative_limits (
    id SERIAL PRIMARY KEY,
    limit_name VARCHAR(50),
    total_limit NUMERIC,
    period VARCHAR(20), -- ANNUAL, LIFETIME, etc.
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE benefit_cumulative_link (
    id SERIAL PRIMARY KEY,
    cumulative_limit_id INTEGER REFERENCES cumulative_limits(id),
    benefit_id INTEGER REFERENCES benefits(id)
);

-- Hospital Access Tiers
CREATE TABLE hospital_access_tiers (
    id SERIAL PRIMARY KEY,
    tier_name VARCHAR(50) NOT NULL,
    includes_major_hospitals BOOLEAN DEFAULT false,
    includes_slmc BOOLEAN DEFAULT false, -- St. Luke's Medical Center access
    includes_healthway BOOLEAN DEFAULT false,
    premium_adjustment_pct NUMERIC,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Room Categories Table
CREATE TABLE room_categories (
    id SERIAL PRIMARY KEY,
    category_code VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    room_class VARCHAR(50) NOT NULL,
    default_mbl_amount NUMERIC(12,2),
    description TEXT,
    philhealth_eligible BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_room_class CHECK (room_class IN ('SUITE', 'PRIVATE', 'SEMI_PRIVATE', 'WARD'))
);

-- Location-Based Adjustments Table
CREATE TABLE location_based_adjustments (
    id SERIAL PRIMARY KEY,
    benefit_id INTEGER REFERENCES benefits(id),
    region VARCHAR(50),
    adjustment_percentage NUMERIC,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Co-payment Adjustments Table
CREATE TABLE benefit_copayments (
    id SERIAL PRIMARY KEY,
    benefit_id INTEGER REFERENCES benefits(id),
    hospital_tier_id INTEGER REFERENCES hospital_access_tiers(id),
    copay_amount NUMERIC,
    copay_type VARCHAR(20), -- FIXED, PERCENTAGE
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Room Rate History Table
CREATE TABLE room_rate_history (
    id SERIAL PRIMARY KEY,
    room_category_id INTEGER REFERENCES room_categories(id),
    hospital_id VARCHAR(50) NOT NULL,
    rate_amount NUMERIC(12,2) NOT NULL,
    effective_date DATE NOT NULL,
    end_date DATE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT valid_rate CHECK (rate_amount >= 0)
);
-- Part 2: Base Data Population
-- Initial Categories from your script
INSERT INTO benefit_categories (category_code, name) VALUES 
('ROOM_BOARD', 'Room and Board'),
('EMERGENCY', 'Emergency Care'),
('MATERNITY', 'Maternity Benefits'),
('DENTAL', 'Dental Benefits'),
('OPD_MED', 'Outpatient Prescribed Medicines');

-- Hospital Access Tiers from your script
INSERT INTO hospital_access_tiers (
    tier_name,
    includes_major_hospitals,
    includes_slmc,
    includes_healthway,
    premium_adjustment_pct
) VALUES
('SET_A', true, true, true, 1.2), -- With access to major hospitals, 20% premium adjustment
('SET_B', false, false, true, 1.0); -- Without major hospitals, standard premium

-- Room Categories with MBL Tiers from your script
INSERT INTO room_categories (
    category_code,
    name,
    room_class,
    default_mbl_amount
) VALUES
('SUITE_SM', 'Small Suite', 'SUITE', 500000),
('PRIV_OPEN', 'Open Private', 'PRIVATE', 300000),
('PRIV_LG', 'Large Private', 'PRIVATE', 250000),
('SEMI_PRIV', 'Semi-Private', 'SEMI_PRIVATE', 80000),
('WARD', 'Ward', 'WARD', 25000);

-- Room & Board Benefits with Policy-Specific MBL Tiers
INSERT INTO benefits (
    category_id,
    benefit_code,
    name,
    coverage_type,
    limit_type,
    limit_value
) VALUES
((SELECT id FROM benefit_categories WHERE category_code = 'ROOM_BOARD'),
 'RB_SMALL_SUITE', 'Small Suite', 'UP_TO_LIMIT', 'MBL', 500000),
((SELECT id FROM benefit_categories WHERE category_code = 'ROOM_BOARD'),
 'RB_OPEN_PRIVATE', 'Open Private', 'UP_TO_LIMIT', 'MBL', 300000),
((SELECT id FROM benefit_categories WHERE category_code = 'ROOM_BOARD'),
 'RB_LARGE_PRIVATE', 'Large Private', 'UP_TO_LIMIT', 'MBL', 250000),
((SELECT id FROM benefit_categories WHERE category_code = 'ROOM_BOARD'),
 'RB_SEMI_PRIVATE', 'Semi-Private', 'UP_TO_LIMIT', 'MBL', 80000),
((SELECT id FROM benefit_categories WHERE category_code = 'ROOM_BOARD'),
 'RB_WARD', 'Ward', 'UP_TO_LIMIT', 'MBL', 25000);
-- Part 3: Emergency and Maternity Benefits

-- Emergency Care Benefits from your script
INSERT INTO benefits (
    category_id,
    benefit_code,
    name,
    description,
    coverage_type,
    limit_type
) VALUES
((SELECT id FROM benefit_categories WHERE category_code = 'EMERGENCY'), 
 'ER_ACCREDITED',
 'Emergency Care - Accredited',
 'Emergency care in accredited hospitals',
 'UP_TO_LIMIT',
 'MBL'),
((SELECT id FROM benefit_categories WHERE category_code = 'EMERGENCY'),
 'ER_NON_ACCREDITED',
 'Emergency Care - Non-Accredited',
 'Emergency care in non-accredited hospitals',
 'PARTIAL',
 'PERCENTAGE');

-- Non-Accredited Hospital Coverage Condition
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'ER_NON_ACCREDITED'), 
 'COVERAGE_PERCENTAGE',
 '=',
 '{"hospital_bill_pct": 80, "pf_pct": 100}',
 'Reimbursable up to 80% of hospital bill and 100% of PF based on ICARE rates');

-- Maternity Benefits from your script
INSERT INTO benefits (
    category_id,
    benefit_code,
    name,
    description,
    coverage_type,
    limit_type,
    limit_value,
    limit_period,
    requires_preauth,
    philhealth_eligible
) VALUES
((SELECT id FROM benefit_categories WHERE category_code = 'MATERNITY'),
 'MATERNITY_NORMAL',
 'Normal Delivery',
 'Coverage for normal delivery',
 'UP_TO_LIMIT',
 'MBL',
 15000,
 'PER_INCIDENT',
 true,
 true),
((SELECT id FROM benefit_categories WHERE category_code = 'MATERNITY'),
 'MATERNITY_C_SECTION',
 'Cesarean Section',
 'Coverage for Cesarean delivery',
 'UP_TO_LIMIT',
 'MBL',
 30000,
 'PER_INCIDENT',
 true,
 true),
((SELECT id FROM benefit_categories WHERE category_code = 'MATERNITY'),
 'MATERNITY_PRENATAL',
 'Prenatal Checkups',
 'Coverage for prenatal care visits',
 'UP_TO_LIMIT',
 'PER_YEAR',
 5000,
 'ANNUAL',
 false,
 true),
((SELECT id FROM benefit_categories WHERE category_code = 'MATERNITY'),
 'MATERNITY_POSTNATAL',
 'Postnatal Checkups',
 'Coverage for postnatal care visits',
 'UP_TO_LIMIT',
 'PER_YEAR',
 3000,
 'ANNUAL',
 false,
 true);

-- Special Hospital Conditions for Maternity
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'MATERNITY_C_SECTION'),
 'HOSPITAL_REQUIREMENT',
 'IN',
 '{"required_facilities": ["NICU", "OB_SPECIALIST", "ANESTHESIOLOGIST"]}',
 'Must be performed in hospital with required facilities and specialists');

-- Maternity Age Limits
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'MATERNITY_NORMAL'),
 'AGE_LIMIT',
 'BETWEEN',
 '{"min_age": 18, "max_age": 45}',
 'Maternity coverage available between ages 18-45');
-- Part 4: Dental Benefits with All Edge Cases

-- Dental Benefits Package from your script
INSERT INTO benefits (
    category_id,
    benefit_code,
    name,
    description,
    coverage_type,
    limit_type,
    limit_value,
    limit_period,
    requires_preauth,
    philhealth_eligible
) VALUES
((SELECT id FROM benefit_categories WHERE category_code = 'DENTAL'),
 'DENTAL_CLEANING',
 'Dental Cleaning',
 'Coverage for routine dental cleaning',
 'FULL',
 'PER_YEAR',
 2000,
 'ANNUAL',
 false,
 false),
((SELECT id FROM benefit_categories WHERE category_code = 'DENTAL'),
 'DENTAL_FILLING',
 'Dental Filling',
 'Coverage for dental fillings',
 'PARTIAL',
 'PER_VISIT',
 1000,
 'PER_VISIT',
 false,
 false),
((SELECT id FROM benefit_categories WHERE category_code = 'DENTAL'),
 'DENTAL_EXTRACTION',
 'Tooth Extraction',
 'Coverage for tooth extraction',
 'PARTIAL',
 'PER_VISIT',
 1500,
 'PER_VISIT',
 false,
 false),
((SELECT id FROM benefit_categories WHERE category_code = 'DENTAL'),
 'DENTAL_SURGERY',
 'Oral Surgery',
 'Coverage for oral surgery procedures',
 'UP_TO_LIMIT',
 'MBL',
 10000,
 'PER_INCIDENT',
 true,
 false),
((SELECT id FROM benefit_categories WHERE category_code = 'DENTAL'),
 'DENTAL_ORTHODONTICS',
 'Orthodontic Treatment',
 'Coverage for orthodontic procedures',
 'UP_TO_LIMIT',
 'LIFETIME',
 30000,
 'LIFETIME',
 true,
 false);

-- Dental Sublimits
INSERT INTO benefit_sublimits (
    benefit_id,
    sublimit_type,
    amount,
    period,
    max_occurrences,
    notes
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'DENTAL_FILLING'),
 'PER_TOOTH',
 1000,
 'PER_VISIT',
 3,
 'Maximum of 3 fillings per visit'),
((SELECT id FROM benefits WHERE benefit_code = 'DENTAL_CLEANING'),
 'FREQUENCY',
 NULL,
 'ANNUAL',
 2,
 'Maximum of 2 cleanings per year');

-- Dental Surgery Special Conditions
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'DENTAL_SURGERY'),
 'SPECIALIST_REQUIRED',
 '=',
 '{"specialist_type": "oral_surgeon", "years_experience": 5}',
 'Must be performed by qualified oral surgeon with 5+ years experience');

-- Dental Frequency Limitations
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'DENTAL_CLEANING'),
 'FREQUENCY_LIMIT',
 '<=',
 '{"max_visits": 2, "period": "ANNUAL", "min_gap_days": 120}',
 'Maximum 2 cleanings per year with minimum 120 days between visits');

-- Dental Age Restrictions
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'DENTAL_ORTHODONTICS'),
 'AGE_LIMIT',
 'BETWEEN',
 '{"min_age": 12, "max_age": 25}',
 'Orthodontic coverage available only between ages 12-25');

-- Dental Pre-existing Conditions
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'DENTAL_SURGERY'),
 'WAITING_PERIOD',
 '>=',
 '{"months": 6, "pre_existing": true}',
 'Six month waiting period for pre-existing conditions');

-- Dental Annual Combined Limit
INSERT INTO cumulative_limits (
    limit_name,
    total_limit,
    period
) VALUES
('DENTAL_ANNUAL_COMBINED', 20000, 'ANNUAL');

-- Link dental benefits to cumulative limit
INSERT INTO benefit_cumulative_link (
    cumulative_limit_id,
    benefit_id
) 
SELECT 
    (SELECT id FROM cumulative_limits WHERE limit_name = 'DENTAL_ANNUAL_COMBINED'),
    id 
FROM benefits 
WHERE benefit_code IN (
    'DENTAL_CLEANING',
    'DENTAL_FILLING',
    'DENTAL_EXTRACTION'
);
-- Part 5: OPD Medicines with All Conditions

-- Outpatient Prescribed Medicines from your script
INSERT INTO benefits (
    category_id,
    benefit_code,
    name,
    description,
    coverage_type,
    limit_type,
    limit_value,
    limit_period,
    requires_preauth,
    philhealth_eligible
) VALUES
((SELECT id FROM benefit_categories WHERE category_code = 'OPD_MED'),
 'OPD_MED_GENERAL',
 'General Prescription Medicines',
 'Coverage for general outpatient prescription medicines',
 'UP_TO_LIMIT',
 'PER_YEAR',
 10000,
 'ANNUAL',
 false,
 true),
((SELECT id FROM benefit_categories WHERE category_code = 'OPD_MED'),
 'OPD_MED_SPECIFIC',
 'Specialized Medicines',
 'Coverage for specified outpatient prescription medicines',
 'PARTIAL',
 'PER_INCIDENT',
 5000,
 'PER_INCIDENT',
 true,
 true);

-- OPD Medicine Prescription Requirements
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'OPD_MED_SPECIFIC'),
 'PRESCRIPTION_REQUIRED',
 '=',
 '{"prescribing_doctor": "accredited", "validity_days": 30}',
 'Requires prescription from accredited doctor, valid for 30 days'),
((SELECT id FROM benefits WHERE benefit_code = 'OPD_MED_SPECIFIC'),
 'MEDICINE_CATEGORY',
 'IN',
 '{"categories": ["antibiotics", "maintenance", "specialized"]}',
 'Limited to specified medicine categories');

-- OPD Seasonal Conditions
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'OPD_MED_SPECIFIC'),
 'SEASONAL_LIMIT',
 'BETWEEN',
 '{"start_month": 9, "end_month": 3, "description": "Flu Season"}',
 'Flu vaccination covered only during specified months');

-- Location Based Adjustments for OPD
INSERT INTO location_based_adjustments (
    benefit_id,
    region,
    adjustment_percentage
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'OPD_MED_SPECIFIC'),
 'NCR',
 1.2),
((SELECT id FROM benefits WHERE benefit_code = 'OPD_MED_SPECIFIC'),
 'LUZON',
 1.0),
((SELECT id FROM benefits WHERE benefit_code = 'OPD_MED_SPECIFIC'),
 'VISAYAS',
 0.9),
((SELECT id FROM benefits WHERE benefit_code = 'OPD_MED_SPECIFIC'),
 'MINDANAO',
 0.85);

-- OPD Medicine Sublimits
INSERT INTO benefit_sublimits (
    benefit_id,
    sublimit_type,
    amount,
    period,
    max_occurrences,
    notes
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'OPD_MED_SPECIFIC'),
 'PER_PRESCRIPTION',
 2500,
 'PER_INCIDENT',
 NULL,
 'Maximum amount per prescription'),
((SELECT id FROM benefits WHERE benefit_code = 'OPD_MED_GENERAL'),
 'MONTHLY_CAP',
 3000,
 'MONTHLY',
 NULL,
 'Monthly cap for general medications');
-- Part 6: Room Enhancements and MBL Calculations

-- Room Upgrade Conditions
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'RB_SEMI_PRIVATE'),
 'ROOM_UPGRADE',
 '=',
 '{"max_upgrade": 1, "difference_coverage": 0.7}',
 'One level room upgrade allowed with 70% coverage of difference');

-- Room MBL Calculation Function
CREATE OR REPLACE FUNCTION calculate_adjusted_mbl(
    p_room_category_id INTEGER,
    p_policy_id VARCHAR(50),
    p_hospital_id VARCHAR(50),
    p_admission_date DATE
)
RETURNS TABLE (
    mbl_amount NUMERIC(12,2),
    coverage_percentage INTEGER,
    adjustment_details JSONB
) AS $$
DECLARE
    v_base_mbl NUMERIC(12,2);
    v_adjustments JSONB := '{}';
    v_coverage_pct INTEGER;
BEGIN
    -- Get base MBL amount for policy and room category
    SELECT 
        rc.default_mbl_amount,
        100
    INTO v_base_mbl, v_coverage_pct
    FROM room_categories rc
    WHERE rc.id = p_room_category_id;

    -- Apply hospital tier adjustments
    SELECT 
        jsonb_build_object(
            'hospital_tier',
            jsonb_build_object(
                'adjustment', hat.premium_adjustment_pct,
                'tier', hat.tier_name
            )
        )
    INTO v_adjustments
    FROM hospital_access_tiers hat
    JOIN room_rate_history rrh ON rrh.hospital_id = p_hospital_id
    WHERE p_admission_date BETWEEN rrh.effective_date 
    AND COALESCE(rrh.end_date, 'infinity'::DATE)
    LIMIT 1;

    -- Apply location adjustments if any
    WITH location_adj AS (
        SELECT 
            adjustment_percentage,
            region
        FROM location_based_adjustments lba
        WHERE benefit_id IN (
            SELECT id FROM benefits 
            WHERE category_id = (
                SELECT id FROM benefit_categories 
                WHERE category_code = 'ROOM_BOARD'
            )
        )
        AND region = (
            -- This would be replaced with actual hospital location lookup
            'NCR'
        )
    )
    SELECT 
        v_adjustments || 
        jsonb_build_object(
            'location',
            jsonb_build_object(
                'adjustment', adjustment_percentage,
                'region', region
            )
        )
    INTO v_adjustments
    FROM location_adj;

    -- Calculate final MBL
    v_base_mbl := v_base_mbl * 
        COALESCE((v_adjustments->'hospital_tier'->>'adjustment')::numeric, 1) *
        COALESCE((v_adjustments->'location'->>'adjustment')::numeric, 1);

    RETURN QUERY 
    SELECT 
        v_base_mbl AS mbl_amount,
        v_coverage_pct AS coverage_percentage,
        v_adjustments AS adjustment_details;
END;
$$ LANGUAGE plpgsql;

-- Room Rate History Trigger
CREATE OR REPLACE FUNCTION track_room_rate_changes()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        -- Close the current rate period
        UPDATE room_rate_history 
        SET end_date = CURRENT_DATE - INTERVAL '1 day'
        WHERE room_category_id = NEW.room_category_id 
        AND hospital_id = NEW.hospital_id
        AND end_date IS NULL;
        
        -- Insert new rate record
        INSERT INTO room_rate_history (
            room_category_id,
            hospital_id,
            rate_amount,
            effective_date,
            version
        )
        SELECT 
            NEW.room_category_id,
            NEW.hospital_id,
            NEW.rate_amount,
            CURRENT_DATE,
            COALESCE(MAX(version), 0) + 1
        FROM room_rate_history
        WHERE room_category_id = NEW.room_category_id
        AND hospital_id = NEW.hospital_id;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
-- Part 7: Additional Functions and Procedures

-- Function to validate benefit eligibility
CREATE OR REPLACE FUNCTION check_benefit_eligibility(
    p_benefit_id INTEGER,
    p_member_age INTEGER,
    p_admission_date DATE,
    p_hospital_id VARCHAR(50)
) RETURNS TABLE (
    is_eligible BOOLEAN,
    message TEXT,
    applied_conditions JSONB
) AS $$
DECLARE
    v_conditions JSONB := '{}';
BEGIN
    -- Check age limits
    WITH age_check AS (
        SELECT value->>'min_age' AS min_age,
               value->>'max_age' AS max_age
        FROM benefit_conditions
        WHERE benefit_id = p_benefit_id
        AND condition_type = 'AGE_LIMIT'
    )
    SELECT 
        v_conditions || jsonb_build_object(
            'age_check',
            jsonb_build_object(
                'passed', p_member_age BETWEEN (min_age::integer) AND (max_age::integer),
                'member_age', p_member_age,
                'allowed_range', jsonb_build_object('min', min_age, 'max', max_age)
            )
        )
    INTO v_conditions
    FROM age_check;

    -- Check seasonal restrictions
    WITH season_check AS (
        SELECT value->>'start_month' AS start_month,
               value->>'end_month' AS end_month
        FROM benefit_conditions
        WHERE benefit_id = p_benefit_id
        AND condition_type = 'SEASONAL_LIMIT'
    )
    SELECT 
        v_conditions || jsonb_build_object(
            'seasonal_check',
            jsonb_build_object(
                'passed', EXTRACT(MONTH FROM p_admission_date) BETWEEN start_month::integer AND end_month::integer,
                'admission_month', EXTRACT(MONTH FROM p_admission_date),
                'allowed_months', jsonb_build_object('start', start_month, 'end', end_month)
            )
        )
    INTO v_conditions
    FROM season_check;

    -- Check waiting periods
    WITH waiting_check AS (
        SELECT value->>'months' AS waiting_months
        FROM benefit_conditions
        WHERE benefit_id = p_benefit_id
        AND condition_type = 'WAITING_PERIOD'
    )
    SELECT 
        v_conditions || jsonb_build_object(
            'waiting_period_check',
            jsonb_build_object(
                'passed', true, -- This would need actual enrollment date check
                'required_months', waiting_months
            )
        )
    INTO v_conditions
    FROM waiting_check;

    RETURN QUERY
    SELECT 
        COALESCE(
            (v_conditions->>'age_check'->>'passed')::boolean, true
        ) AND
        COALESCE(
            (v_conditions->>'seasonal_check'->>'passed')::boolean, true
        ) AND
        COALESCE(
            (v_conditions->>'waiting_period_check'->>'passed')::boolean, true
        ) as is_eligible,
        CASE 
            WHEN NOT COALESCE((v_conditions->>'age_check'->>'passed')::boolean, true)
                THEN 'Age requirement not met'
            WHEN NOT COALESCE((v_conditions->>'seasonal_check'->>'passed')::boolean, true)
                THEN 'Outside covered season'
            WHEN NOT COALESCE((v_conditions->>'waiting_period_check'->>'passed')::boolean, true)
                THEN 'Waiting period not satisfied'
            ELSE 'Eligible'
        END as message,
        v_conditions as applied_conditions;
END;
$$ LANGUAGE plpgsql;

-- Function to calculate benefit sublimits
CREATE OR REPLACE FUNCTION calculate_benefit_sublimits(
    p_benefit_id INTEGER,
    p_amount NUMERIC,
    p_incident_date DATE
) RETURNS TABLE (
    allowed_amount NUMERIC,
    remaining_limit NUMERIC,
    applied_sublimits JSONB
) AS $$
DECLARE
    v_sublimits JSONB := '{}';
    v_allowed_amount NUMERIC := p_amount;
BEGIN
    -- Check individual sublimits
    FOR v_sublimit IN (
        SELECT *
        FROM benefit_sublimits
        WHERE benefit_id = p_benefit_id
    ) LOOP
        SELECT 
            v_sublimits || jsonb_build_object(
                v_sublimit.sublimit_type,
                jsonb_build_object(
                    'original_limit', v_sublimit.amount,
                    'applied_amount', LEAST(v_allowed_amount, v_sublimit.amount),
                    'period', v_sublimit.period
                )
            )
        INTO v_sublimits;
        
        v_allowed_amount := LEAST(v_allowed_amount, v_sublimit.amount);
    END LOOP;

    -- Check cumulative limits
    FOR v_cum_limit IN (
        SELECT cl.*
        FROM cumulative_limits cl
        JOIN benefit_cumulative_link bcl ON cl.id = bcl.cumulative_limit_id
        WHERE bcl.benefit_id = p_benefit_id
    ) LOOP
        SELECT 
            v_sublimits || jsonb_build_object(
                'cumulative_' || v_cum_limit.period,
                jsonb_build_object(
                    'total_limit', v_cum_limit.total_limit,
                    'period', v_cum_limit.period,
                    'remaining', v_cum_limit.total_limit  -- This would need actual usage calculation
                )
            )
        INTO v_sublimits;
        
        v_allowed_amount := LEAST(v_allowed_amount, v_cum_limit.total_limit);
    END LOOP;

    RETURN QUERY
    SELECT 
        v_allowed_amount as allowed_amount,
        v_allowed_amount as remaining_limit,  -- This would need actual usage calculation
        v_sublimits as applied_sublimits;
END;
$$ LANGUAGE plpgsql;
-- Part 8: Additional Test Scenarios

-- Test Scenario 1: Complex Room Upgrade with MBL
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'RB_SEMI_PRIVATE'),
 'FORCED_UPGRADE',
 '=',
 '{"reason": "ICU_UNAVAILABLE", "coverage": 1.0, "max_days": 3}',
 'Full coverage for forced upgrade due to ICU unavailability up to 3 days');

-- Test Scenario 2: Multiple Condition Dental Case
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'DENTAL_SURGERY'),
 'COMBINED_REQUIREMENTS',
 'ALL',
 '{"specialist_required": true, "hospital_grade": "TERTIARY", "pre_approval": true}',
 'Complex dental surgery requirements');

-- Test Scenario 3: Seasonal Medicine with Location Variance
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'OPD_MED_SPECIFIC'),
 'SEASONAL_LOCATION',
 'IN',
 '{"NCR": {"months": [6,7,8,9]}, "VISAYAS": {"months": [7,8,9,10]}}',
 'Region-specific seasonal coverage');

-- Test Scenario 4: Maternity with Pre-existing Condition
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'MATERNITY_C_SECTION'),
 'PRE_EXISTING',
 '=',
 '{"waiting_period_months": 12, "declaration_required": true}',
 'Pre-existing condition waiting period for maternity');

-- Test Scenario 5: Emergency Care with Distance Rules
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'ER_NON_ACCREDITED'),
 'DISTANCE_RULE',
 '>=',
 '{"min_distance_km": 25, "from_accredited": true}',
 'Non-accredited coverage when accredited facility is too far');

-- Test Scenario 6: Complex Benefit Combinations
INSERT INTO cumulative_limits (
    limit_name,
    total_limit,
    period
) VALUES
('COMBINED_SURGICAL', 500000, 'ANNUAL');

-- Link multiple benefits to cumulative limit
INSERT INTO benefit_cumulative_link (
    cumulative_limit_id,
    benefit_id
) 
SELECT 
    (SELECT id FROM cumulative_limits WHERE limit_name = 'COMBINED_SURGICAL'),
    id 
FROM benefits 
WHERE benefit_code IN (
    'DENTAL_SURGERY',
    'MATERNITY_C_SECTION'
);

-- Test Scenario 7: Hospital Tier Override
INSERT INTO benefit_conditions (
    benefit_id,
    condition_type,
    operator,
    value,
    error_message
) VALUES
((SELECT id FROM benefits WHERE benefit_code = 'ER_ACCREDITED'),
 'TIER_OVERRIDE',
 '=',
 '{"emergency_conditions": ["STROKE", "HEART_ATTACK", "SEVERE_TRAUMA"], "coverage": 1.0}',
 'Full coverage at any tier for specified emergency conditions');

-- Test lookup values for validations
INSERT INTO room_rate_history (
    room_category_id,
    hospital_id,
    rate_amount,
    effective_date
) VALUES
((SELECT id FROM room_categories WHERE category_code = 'SUITE_SM'),
 'HOSP001',
 8500,
 '2024-01-01'),
((SELECT id FROM room_categories WHERE category_code = 'PRIV_LG'),
 'HOSP001',
 5500,
 '2024-01-01'),
((SELECT id FROM room_categories WHERE category_code = 'SEMI_PRIV'),
 'HOSP001',
 3500,
 '2024-01-01');

-- Example test calls
DO $$
DECLARE
    v_test_result RECORD;
BEGIN
    -- Test benefit eligibility
    SELECT * INTO v_test_result FROM check_benefit_eligibility(
        (SELECT id FROM benefits WHERE benefit_code = 'MATERNITY_NORMAL'),
        25,  -- age
        '2024-02-01'::DATE,  -- admission date
        'HOSP001'  -- hospital
    );
    
    RAISE NOTICE 'Eligibility Test Result: %', v_test_result;
    
    -- Test MBL calculation
    SELECT * INTO v_test_result FROM calculate_adjusted_mbl(
        (SELECT id FROM room_categories WHERE category_code = 'SUITE_SM'),
        'POL001',
        'HOSP001',
        '2024-02-01'::DATE
    );
    
    RAISE NOTICE 'MBL Calculation Result: %', v_test_result;
    
    -- Test sublimit calculation
    SELECT * INTO v_test_result FROM calculate_benefit_sublimits(
        (SELECT id FROM benefits WHERE benefit_code = 'DENTAL_SURGERY'),
        15000,  -- amount
        '2024-02-01'::DATE  -- incident date
    );
    
    RAISE NOTICE 'Sublimit Calculation Result: %', v_test_result;
END $$;

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

-- 1. Performance Indexes
CREATE INDEX IF NOT EXISTS idx_benefit_conditions_benefit_id ON benefit_conditions(benefit_id);
CREATE INDEX IF NOT EXISTS idx_room_rate_history_lookup ON room_rate_history(hospital_id, room_category_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_version ON audit_logs(version_id);

-- 2. Business Rule Functions
CREATE OR REPLACE FUNCTION validate_config_version(
    p_version_number VARCHAR,
    p_effective_date DATE
) RETURNS BOOLEAN AS $$
BEGIN
    -- Version number format check
    IF NOT p_version_number ~ '^\d{4}\.\d+$' THEN
        RAISE EXCEPTION 'Invalid version number format: %', p_version_number;
    END IF;
    
    -- Effective date validation
    IF p_effective_date <= CURRENT_DATE THEN
        RAISE EXCEPTION 'Effective date must be in the future';
    END IF;
    
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- 3. Test Cases Function
CREATE OR REPLACE FUNCTION test_room_rate_updates() RETURNS VOID AS $$
DECLARE
    v_test_version_id INTEGER;
    v_test_result RECORD;
BEGIN
    -- Test case 1: Valid version creation
    SELECT create_config_version('2024.3', '2024-08-01', 'Test update', 'test_user') 
    INTO v_test_version_id;
    
    ASSERT v_test_version_id IS NOT NULL, 
        'Version creation failed';
    
    -- Test case 2: Room rate calculation
    SELECT * INTO v_test_result 
    FROM calculate_adjusted_mbl(
        (SELECT id FROM room_categories WHERE category_code = 'SUITE'),
        'TEST_POL',
        'TEST_HOSP',
        '2024-08-01'::DATE
    );
    
    ASSERT v_test_result.mbl_amount > 0, 
        'MBL calculation failed';
        
    -- Test case 3: Invalid version format
    BEGIN
        PERFORM validate_config_version('invalid', '2024-08-01'::DATE);
        RAISE EXCEPTION 'Expected error not raised';
    EXCEPTION WHEN others THEN
        -- Expected error
    END;
    
    RAISE NOTICE 'All tests passed successfully';
END;
$$ LANGUAGE plpgsql;

-- 4. Configuration Validation
CREATE OR REPLACE FUNCTION validate_room_config() RETURNS TABLE (
    validation_type TEXT,
    status BOOLEAN,
    message TEXT
) AS $$
BEGIN
    -- Check room categories
    RETURN QUERY
    SELECT 
        'Room Categories'::TEXT,
        COUNT(*) > 0,
        CASE WHEN COUNT(*) > 0 
            THEN 'Valid' 
            ELSE 'No room categories defined' 
        END
    FROM room_categories;
    
    -- Check room rates
    RETURN QUERY
    SELECT 
        'Room Rates'::TEXT,
        COUNT(*) > 0,
        CASE WHEN COUNT(*) > 0 
            THEN 'Valid' 
            ELSE 'No room rates defined' 
        END
    FROM room_rate_history
    WHERE end_date IS NULL;
    
    -- Check benefit links
    RETURN QUERY
    SELECT 
        'Benefit Links'::TEXT,
        COUNT(*) > 0,
        CASE WHEN COUNT(*) > 0 
            THEN 'Valid' 
            ELSE 'No benefit links defined' 
        END
    FROM benefits
    WHERE category_id IN (
        SELECT id FROM benefit_categories 
        WHERE category_code = 'ROOM_BOARD'
    );
END;
$$ LANGUAGE plpgsql;

-- Execute tests
SELECT test_room_rate_updates();

-- Validate configuration
SELECT * FROM validate_room_config();