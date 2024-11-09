import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AlertTriangle, Check, Info, Clock, RefreshCw } from 'lucide-react';
import classNames from 'classnames';

// Enhanced interfaces for more detailed PhilHealth information
interface PhilHealthPolicy {
  policyNumber: string;
  validityPeriod: {
    start: string;
    end: string;
  };
  coverageType: string;
  dependents: number;
  customLimits?: {
    hospital: number;
    outpatient: number;
  };
}

interface BatchBenefit {
  id: string;
  caseRate: number;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  result?: {
    hospitalShare: number;
    professionalFeeShare: number;
  };
  error?: string;
  retryCount: number;
}

interface MembershipInfo {
  membershipNumber: string;
  status: 'ACTIVE' | 'INACTIVE' | 'SUSPENDED';
  coverageValid: boolean;
  validityPeriod: {
    start: string;
    end: string;
  };
}

const MAX_RETRIES = 3;
const RETRY_DELAY = 2000;

const EnhancedPhilHealthCalculator: React.FC = () => {
  const [membershipInfo, setMembershipInfo] = useState<MembershipInfo | null>(null);
  const [policyDetails, setPolicyDetails] = useState<PhilHealthPolicy | null>(null);
  const [batchBenefits, setBatchBenefits] = useState<BatchBenefit[]>([]);
  const [loading, setLoading] = useState({
    membership: false,
    policy: false,
    calculation: false
  });
  const [errors, setErrors] = useState<{ [key: string]: string }>({});

  // Enhanced retry logic with exponential backoff
  const fetchWithRetry = useCallback(async (url: string, options = {}, retryCount = 0): Promise<any> => {
    try {
      const response = await fetch(url, options);
      if (!response.ok) throw new Error('Request failed');
      return await response.json();
    } catch (error) {
      if (retryCount < MAX_RETRIES) {
        await new Promise(resolve => 
          setTimeout(resolve, RETRY_DELAY * Math.pow(2, retryCount))
        );
        return fetchWithRetry(url, options, retryCount + 1);
      }
      throw error;
    }
  }, []);

  // Enhanced validation rules
  const validateMembershipData = useCallback((data: MembershipInfo): string[] => {
    const validationErrors: string[] = [];
    
    if (!data.membershipNumber?.match(/^PH\d{10}$/)) {
      validationErrors.push('Invalid membership number format');
    }
    
    if (!data.coverageValid || data.status !== 'ACTIVE') {
      validationErrors.push('Coverage is not active');
    }
    
    const today = new Date();
    const validityEnd = new Date(data.validityPeriod?.end);
    if (validityEnd < today) {
      validationErrors.push('Coverage has expired');
    }

    return validationErrors;
  }, []);

  // Batch processing logic
  const processBatch = async (benefits: BatchBenefit[]) => {
    setBatchBenefits(benefits.map(b => ({
      ...b,
      status: 'pending',
      retryCount: 0
    })));

    const processBenefit = async (benefit: BatchBenefit) => {
      try {
        const result = await fetchWithRetry('/api/philhealth/calculate-benefits', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(benefit)
        });

        setBatchBenefits(prev => 
          prev.map(b => 
            b.id === benefit.id 
              ? { ...b, status: 'completed', result }
              : b
          )
        );
      } catch (error) {
        setBatchBenefits(prev =>
          prev.map(b =>
            b.id === benefit.id
              ? { ...b, status: 'failed', error: error instanceof Error ? error.message : 'Processing failed' }
              : b
          )
        );
      }
    };

    // Process in chunks of 5
    const chunks = [];
    for (let i = 0; i < benefits.length; i += 5) {
      chunks.push(benefits.slice(i, i + 5));
    }

    for (const chunk of chunks) {
      await Promise.all(chunk.map(processBenefit));
    }
  };

  // Policy details card
  const PolicyCard: React.FC<{ policy: PhilHealthPolicy }> = ({ policy }) => (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Info className="h-5 w-5" />
          Policy Details
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-blue-50 p-3 rounded">
            <div className="text-sm text-blue-700">Policy Number</div>
            <div className="font-medium">{policy.policyNumber}</div>
          </div>
          <div className="bg-green-50 p-3 rounded">
            <div className="text-sm text-green-700">Coverage Type</div>
            <div className="font-medium">{policy.coverageType}</div>
          </div>
          <div className="bg-purple-50 p-3 rounded">
            <div className="text-sm text-purple-700">Validity Period</div>
            <div className="font-medium">
              {new Date(policy.validityPeriod.start).toLocaleDateString()} - 
              {new Date(policy.validityPeriod.end).toLocaleDateString()}
            </div>
          </div>
          <div className="bg-amber-50 p-3 rounded">
            <div className="text-sm text-amber-700">Dependents</div>
            <div className="font-medium">{policy.dependents}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );

  // Batch processing status card
  const BatchStatusCard: React.FC<{ benefits: BatchBenefit[] }> = ({ benefits }) => (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <RefreshCw className="h-5 w-5" />
          Batch Processing Status
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {benefits.map(benefit => (
            <div
              key={benefit.id}
              className={classNames(
                'p-3 rounded flex justify-between items-center',
                {
                  'bg-green-50': benefit.status === 'completed',
                  'bg-red-50': benefit.status === 'failed',
                  'bg-gray-50': benefit.status === 'pending' || benefit.status === 'processing'
                }
              )}
            >
              <div>
                <span className="font-medium">Case Rate: ₱{benefit.caseRate.toLocaleString()}</span>
                {benefit.result && (
                  <div className="text-sm text-gray-600">
                    Hospital: ₱{benefit.result.hospitalShare.toLocaleString()} | 
                    PF: ₱{benefit.result.professionalFeeShare.toLocaleString()}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2">
                {benefit.status === 'completed' && <Check className="h-4 w-4 text-green-500" />}
                {benefit.status === 'failed' && <AlertTriangle className="h-4 w-4 text-red-500" />}
                {benefit.status === 'processing' && <Clock className="h-4 w-4" />}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-6">
      {/* Existing membership status card */}
      {/* ... */}

      {/* Enhanced Policy Information */}
      {policyDetails && <PolicyCard policy={policyDetails} />}

      {/* Batch Processing Status */}
      {batchBenefits.length > 0 && <BatchStatusCard benefits={batchBenefits} />}

      {/* Error Alerts */}
      {Object.entries(errors).map(([key, error]) => (
        <Alert key={key} variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Error in {key}</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ))}
    </div>
  );
};

export default EnhancedPhilHealthCalculator;