#!/usr/bin/env python3
import asyncio
import asyncpg
import sys
import os
from typing import List, Dict
import structlog

logger = structlog.get_logger()

class DatabaseVerifier:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.errors = []
        self.warnings = []

    async def connect(self) -> asyncpg.Connection:
        try:
            return await asyncpg.connect(self.dsn)
        except Exception as e:
            self.errors.append(f"Connection failed: {str(e)}")
            raise

    async def verify_role(self) -> bool:
        """Verify claimsuser role exists with correct permissions."""
        async with await self.connect() as conn:
            role = await conn.fetchrow("""
                SELECT rolname, rolsuper, rolcreaterole, rolcreatedb
                FROM pg_roles
                WHERE rolname = 'claimsuser'
            """)
            
            if not role:
                self.errors.append("claimsuser role does not exist")
                return False
                
            if role['rolsuper']:
                self.warnings.append("claimsuser has superuser privileges")
                
            return True

    async def verify_tables(self) -> bool:
        """Verify all required tables exist and have correct ownership."""
        required_tables = [
            'claims', 'employers', 'members', 'dependents', 'documents',
            'philhealthbenefits', 'providers', 'users'
        ]
        
        async with await self.connect() as conn:
            for table in required_tables:
                exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = $1
                    )
                """, table)
                
                if not exists:
                    self.errors.append(f"Missing table: {table}")
                else:
                    # Check ownership
                    owner = await conn.fetchval("""
                        SELECT tableowner 
                        FROM pg_tables 
                        WHERE tablename = $1
                    """, table)
                    
                    if owner != 'claimsuser':
                        self.errors.append(f"Incorrect ownership for table {table}: {owner}")

        return len(self.errors) == 0

    async def verify_permissions(self) -> bool:
        """Verify correct permissions are set on all tables."""
        async with await self.connect() as conn:
            tables = await conn.fetch("""
                SELECT tablename 
                FROM pg_tables 
                WHERE schemaname = 'public'
            """)
            
            for table in tables:
                grants = await conn.fetch("""
                    SELECT grantee, privilege_type
                    FROM information_schema.role_table_grants
                    WHERE table_name = $1
                """, table['tablename'])
                
                if not any(g['grantee'] == 'claimsuser' for g in grants):
                    self.errors.append(f"No permissions for claimsuser on {table['tablename']}")
                    
        return len(self.errors) == 0

    async def verify_indexes(self) -> bool:
        """Verify required indexes exist."""
        async with await self.connect() as conn:
            indexes = await conn.fetch("""
                SELECT tablename, indexname 
                FROM pg_indexes 
                WHERE schemaname = 'public'
            """)
            
            # Check for specific required indexes
            required_indexes = {
                'claims': ['idx_claims_status_timestamp'],
                'documents': ['idx_documents_claim_type']
            }
            
            for table, required in required_indexes.items():
                table_indexes = [idx['indexname'] for idx in indexes if idx['tablename'] == table]
                missing = set(required) - set(table_indexes)
                if missing:
                    self.errors.append(f"Missing indexes for {table}: {missing}")
                    
        return len(self.errors) == 0

    async def run_all_checks(self) -> bool:
        """Run all verification checks."""
        try:
            checks = [
                self.verify_role(),
                self.verify_tables(),
                self.verify_permissions(),
                self.verify_indexes()
            ]
            
            results = await asyncio.gather(*checks, return_exceptions=True)
            
            if any(isinstance(r, Exception) for r in results):
                self.errors.append("One or more checks failed with exceptions")
                return False
                
            return all(results)
            
        except Exception as e:
            self.errors.append(f"Verification failed: {str(e)}")
            return False

    def print_report(self):
        """Print verification report."""
        if self.errors:
            print("\nErrors:")
            for error in self.errors:
                print(f"❌ {error}")
                
        if self.warnings:
            print("\nWarnings:")
            for warning in self.warnings:
                print(f"⚠️ {warning}")
                
        if not self.errors and not self.warnings:
            print("✅ All checks passed successfully")

async def main():
    if len(sys.argv) < 2:
        print("Usage: verify_db.py <database_url>")
        sys.exit(1)
        
    verifier = DatabaseVerifier(sys.argv[1])
    success = await verifier.run_all_checks()
    verifier.print_report()
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
