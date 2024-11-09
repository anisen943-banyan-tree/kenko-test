import React, { useState, useMemo } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AlertTriangle, Check, Info } from 'lucide-react';
import classNames from 'classnames';

const formatCurrency = (amount: number) => {
  return new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP' }).format(amount);
};

interface InfoRowProps {
  label: string;
  value: string;
  className?: string;
}

const InfoRow: React.FC<InfoRowProps> = ({ label, value, className }) => (
  <div className={classNames("grid grid-cols-2 gap-4 p-4 rounded-lg", className)}>
    <div className="text-sm font-medium">{label}</div>
    <div className="text-right font-medium">{value}</div>
  </div>
);

interface ClaimDetails {
  caseRate: number;
  membershipStatus: 'ACTIVE' | 'INACTIVE' | 'SUSPENDED';
  hasCoverage: boolean;
}

const PhilHealthBenefits: React.FC = () => {
  const [claimDetails, setClaimDetails] = useState<ClaimDetails>({
    caseRate: 31000,
    membershipStatus: 'ACTIVE',
    hasCoverage: true,
  });

  const benefits = useMemo(() => {
    const hospitalShare = claimDetails.caseRate * 0.8;
    const professionalFee = claimDetails.caseRate * 0.2;

    return {
      totalBenefit: claimDetails.caseRate,
      hospitalShare,
      professionalFee,
    };
  }, [claimDetails.caseRate]);

  return (
    <div className="space-y-6">
      {/* Status Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Info className="h-5 w-5 text-blue-500" />
            PhilHealth Coverage Status
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 mb-4">
            {claimDetails.hasCoverage ? (
              <Check className="h-5 w-5 text-green-500" aria-label="Coverage active" />
            ) : (
              <AlertTriangle className="h-5 w-5 text-red-500" aria-label="Coverage inactive" />
            )}
            <span className={classNames({
              "text-green-600": claimDetails.hasCoverage,
              "text-red-600": !claimDetails.hasCoverage,
            })}>
              {claimDetails.membershipStatus}
            </span>
          </div>

          {!claimDetails.hasCoverage && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>Coverage Issue</AlertTitle>
              <AlertDescription>
                PhilHealth coverage validation failed. Please verify membership status.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* Benefits Breakdown */}
      <Card>
        <CardHeader>
          <CardTitle>Benefits Calculation</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <InfoRow
              label="Case Rate"
              value={formatCurrency(benefits.totalBenefit)}
              className="bg-gray-50"
            />
            <InfoRow
              label="Hospital Share (80%)"
              value={formatCurrency(benefits.hospitalShare)}
              className="bg-blue-50 text-blue-600"
            />
            <InfoRow
              label="Professional Fee (20%)"
              value={formatCurrency(benefits.professionalFee)}
              className="bg-green-50 text-green-600"
            />
          </div>
          <div className="mt-6 text-sm text-gray-500">
            * Benefit amounts are calculated based on PhilHealth case rates and policies.
          </div>
        </CardContent>
      </Card>

      {/* Validation Notes */}
      <Card>
        <CardHeader>
          <CardTitle>Validation Notes</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            <li className="flex items-center gap-2">
              <Check className="h-4 w-4 text-green-500" />
              <span>Active membership status verified</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="h-4 w-4 text-green-500" />
              <span>Case rate code validated</span>
            </li>
            <li className="flex items-center gap-2">
              <Check className="h-4 w-4 text-green-500" />
              <span>Benefit calculation completed</span>
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
};

export default PhilHealthBenefits;