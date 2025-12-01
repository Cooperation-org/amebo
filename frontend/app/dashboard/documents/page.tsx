'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { FileUpload } from '@/src/components/documents/FileUpload';
import { DocumentList } from '@/src/components/documents/DocumentList';
import { FileText, Upload, Trash2, Building2, Plus } from 'lucide-react';
import { useDocuments, useUploadDocuments, useDeleteDocument } from '@/src/hooks/useDocuments';
import { useWorkspaces } from '@/src/hooks/useWorkspaces';
import { toast } from 'sonner';
import Link from 'next/link';

export default function DocumentsPage() {
  const { data: documentsData, isLoading } = useDocuments();
  const documents = documentsData?.documents || [];
  const { data: workspacesData } = useWorkspaces();
  const uploadMutation = useUploadDocuments();
  const deleteMutation = useDeleteDocument();
  
  const workspaces = workspacesData?.workspaces || [];
  const hasWorkspaces = workspaces.length > 0;

  const handleFileUpload = async (files: File[], workspaceId?: string) => {
    try {
      await uploadMutation.mutateAsync({ files, workspaceId });
    } catch (error) {
      // Error handling is done in the hook
    }
  };

  const handleDeleteDocument = async (documentId: string) => {
    try {
      await deleteMutation.mutateAsync(documentId);
      toast.success('Document deleted successfully');
    } catch (error) {
      toast.error('Failed to delete document');
    }
  };

  const getStatusStats = () => {
    const stats = Array.isArray(documents) ? documents.reduce((acc, doc) => {
      acc[doc.status] = (acc[doc.status] || 0) + 1;
      return acc;
    }, {} as Record<string, number>) : {};
    
    return {
      total: documents.length,
      indexed: stats.indexed || 0,
      processing: stats.processing || 0,
      failed: stats.failed || 0,
    };
  };

  const stats = getStatusStats();

  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-2">
          <FileText className="h-8 w-8 text-green-600" />
          Documents
        </h1>
        <p className="mt-2 text-gray-600">
          Upload and manage documents for AI-powered search
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Total</p>
                <p className="text-2xl font-bold text-gray-900">{stats.total}</p>
              </div>
              <FileText className="h-8 w-8 text-gray-400" />
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Indexed</p>
                <p className="text-2xl font-bold text-green-600">{stats.indexed}</p>
              </div>
              <Badge variant="secondary" className="bg-green-100 text-green-800">
                Ready
              </Badge>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Processing</p>
                <p className="text-2xl font-bold text-blue-600">{stats.processing}</p>
              </div>
              <Badge variant="secondary" className="bg-blue-100 text-blue-800">
                Working
              </Badge>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Failed</p>
                <p className="text-2xl font-bold text-red-600">{stats.failed}</p>
              </div>
              <Badge variant="secondary" className="bg-red-100 text-red-800">
                Error
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Upload Section */}
        <div className="lg:col-span-1">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Upload className="h-5 w-5" />
                Upload Documents
              </CardTitle>
            </CardHeader>
            <CardContent>
              {!hasWorkspaces ? (
                <div className="text-center py-8">
                  <Building2 className="h-8 w-8 mx-auto mb-2 text-gray-400" />
                  <p className="text-sm text-gray-600 mb-4">
                    Add a workspace first to upload documents
                  </p>
                  <Button asChild size="sm">
                    <Link href="/dashboard/workspaces">
                      <Plus className="h-4 w-4 mr-2" />
                      Add Workspace
                    </Link>
                  </Button>
                </div>
              ) : (
                <>
                  <FileUpload
                    onFilesSelected={handleFileUpload}
                    isUploading={uploadMutation.isPending}
                    acceptedTypes={['.pdf', '.docx', '.txt', '.md']}
                    maxSize={10 * 1024 * 1024} // 10MB
                  />
                  <div className="mt-4 text-sm text-gray-600">
                    <p className="font-medium mb-2">Supported formats:</p>
                    <ul className="space-y-1">
                      <li>• PDF documents</li>
                      <li>• Word documents (.docx)</li>
                      <li>• Text files (.txt, .md)</li>
                      <li>• Maximum size: 10MB</li>
                    </ul>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Document List */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Your Documents</CardTitle>
                {documents.length > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      // TODO: Implement bulk delete
                      toast.info('Bulk delete coming soon');
                    }}
                    className="flex items-center gap-2"
                  >
                    <Trash2 className="h-4 w-4" />
                    Clear All
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <DocumentList
                documents={documents}
                isLoading={isLoading}
                onDelete={handleDeleteDocument}
                isDeleting={deleteMutation.isPending}
              />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}