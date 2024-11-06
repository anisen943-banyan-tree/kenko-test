import pytest
import boto3
import psycopg2
import os
from botocore.exceptions import ClientError

class TestConnections:
    def test_aws_credentials(self):
        """Test AWS credentials are properly configured"""
        try:
            sts = boto3.client('sts')
            response = sts.get_caller_identity()
            assert response['ResponseMetadata']['HTTPStatusCode'] == 200
        except ClientError as e:
            pytest.fail(f"AWS credentials not properly configured: {str(e)}")

    def test_database_connection(self):
        """Test database connection using environment variables"""
        try:
            conn = psycopg2.connect(os.getenv('DATABASE_URL'))
            cur = conn.cursor()
            cur.execute('SELECT 1')
            result = cur.fetchone()
            assert result[0] == 1
            cur.close()
            conn.close()
        except Exception as e:
            pytest.fail(f"Database connection failed: {str(e)}")
