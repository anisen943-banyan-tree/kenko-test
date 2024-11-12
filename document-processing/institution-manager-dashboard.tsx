import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Plus, Settings, Users, Building, AlertTriangle } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

const InstitutionManager = () => {
  const [institutions, setInstitutions] = useState([]);
  const [selectedInstitution, setSelectedInstitution] = useState(null);
  const [isAddingInstitution, setIsAddingInstitution] = useState(false);
  const [isAddingUser, setIsAddingUser] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Form states
  const [newInstitution, setNewInstitution] = useState({
    name: '',
    code: '',
    contact_email: '',
    contact_phone: '',
    subscription_tier: 'STANDARD'
  });

  const [newUser, setNewUser] = useState({
    full_name: '',
    email: '',
    role: 'STANDARD',
    access_level: 'STANDARD'
  });

  // Fetch institutions
  useEffect(() => {
    const fetchInstitutions = async () => {
      setLoading(true);
      try {
        const response = await fetch('/api/admin/institutions');
        const data = await response.json();
        setInstitutions(data);
      } catch (err) {
        setError('Failed to fetch institutions');
      }
      setLoading(false);
    };

    fetchInstitutions();
  }, []);

  // Create new institution
  const handleCreateInstitution = async () => {
    try {
      const response = await fetch('/api/admin/institutions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newInstitution)
      });
      
      if (!response.ok) throw new Error('Failed to create institution');
      
      const created = await response.json();
      setInstitutions([...institutions, created]);
      setIsAddingInstitution(false);
      setNewInstitution({ name: '', code: '', contact_email: '', contact_phone: '', subscription_tier: 'STANDARD' });
    } catch (err) {
      setError('Failed to create institution');
    }
  };

  // Create new user for institution
  const handleCreateUser = async () => {
    try {
      const response = await fetch(`/api/admin/institutions/${selectedInstitution.id}/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newUser)
      });
      
      if (!response.ok) throw new Error('Failed to create user');
      
      setIsAddingUser(false);
      setNewUser({ full_name: '', email: '', role: 'STANDARD', access_level: 'STANDARD' });
    } catch (err) {
      setError('Failed to create user');
    }
  };

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Institution Management</h1>
        <Button onClick={() => setIsAddingInstitution(true)} className="flex items-center gap-2">
          <Plus className="h-4 w-4" />
          Add Institution
        </Button>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Institutions List */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building className="h-5 w-5" />
              Institutions
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {institutions.map((institution) => (
                <div
                  key={institution.id}
                  className={`p-4 rounded-lg border cursor-pointer transition-colors ${
                    selectedInstitution?.id === institution.id
                      ? 'bg-blue-50 border-blue-200'
                      : 'hover:bg-gray-50'
                  }`}
                  onClick={() => setSelectedInstitution(institution)}
                >
                  <div className="font-medium">{institution.name}</div>
                  <div className="text-sm text-gray-600">Code: {institution.code}</div>
                  <div className="text-sm text-gray-600">
                    Status: {institution.status}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Institution Details */}
        {selectedInstitution && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 justify-between">
                <div className="flex items-center gap-2">
                  <Settings className="h-5 w-5" />
                  Institution Details
                </div>
                <Button onClick={() => setIsAddingUser(true)} size="sm">
                  Add User
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div>
                  <h3 className="font-medium">Contact Information</h3>
                  <div className="text-sm text-gray-600">
                    Email: {selectedInstitution.contact_email}
                  </div>
                  <div className="text-sm text-gray-600">
                    Phone: {selectedInstitution.contact_phone}
                  </div>
                </div>
                <div>
                  <h3 className="font-medium">Subscription</h3>
                  <div className="text-sm text-gray-600">
                    Tier: {selectedInstitution.subscription_tier}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Add Institution Dialog */}
      <Dialog open={isAddingInstitution} onOpenChange={setIsAddingInstitution}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add New Institution</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="inst-name">Institution Name</Label>
              <Input
                id="inst-name"
                value={newInstitution.name}
                onChange={(e) => setNewInstitution({ ...newInstitution, name: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="inst-code">Institution Code</Label>
              <Input
                id="inst-code"
                value={newInstitution.code}
                onChange={(e) => setNewInstitution({ ...newInstitution, code: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="inst-email">Contact Email</Label>
              <Input
                id="inst-email"
                type="email"
                value={newInstitution.contact_email}
                onChange={(e) => setNewInstitution({ ...newInstitution, contact_email: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="inst-phone">Contact Phone</Label>
              <Input
                id="inst-phone"
                value={newInstitution.contact_phone}
                onChange={(e) => setNewInstitution({ ...newInstitution, contact_phone: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="inst-tier">Subscription Tier</Label>
              <Select
                value={newInstitution.subscription_tier}
                onValueChange={(value) => setNewInstitution({ ...newInstitution, subscription_tier: value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select tier" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="STANDARD">Standard</SelectItem>
                  <SelectItem value="PREMIUM">Premium</SelectItem>
                  <SelectItem value="ENTERPRISE">Enterprise</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button onClick={handleCreateInstitution} className="w-full">
              Create Institution
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Add User Dialog */}
      <Dialog open={isAddingUser} onOpenChange={setIsAddingUser}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add New User</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="user-name">Full Name</Label>
              <Input
                id="user-name"
                value={newUser.full_name}
                onChange={(e) => setNewUser({ ...newUser, full_name: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="user-email">Email</Label>
              <Input
                id="user-email"
                type="email"
                value={newUser.email}
                onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
              />
            </div>
            <div>
              <Label htmlFor="user-role">Role</Label>
              <Select
                value={newUser.role}
                onValueChange={(value) => setNewUser({ ...newUser, role: value })}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select role" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ADMIN">Admin</SelectItem>
                  <SelectItem value="MANAGER">Manager</SelectItem>
                  <SelectItem value="STANDARD">Standard User</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button onClick={handleCreateUser} className="w-full">
              Create User
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default InstitutionManager;