'use client';

import { useState, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';
import { Upload, File, X, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useWorkspaces } from '@/src/hooks/useWorkspaces';

interface FileUploadProps {
  onFilesSelected: (files: File[], workspaceId?: string) => void;
  isUploading?: boolean;
  acceptedTypes?: string[];
  maxSize?: number;
  multiple?: boolean;
}

export function FileUpload({
  onFilesSelected,
  isUploading = false,
  acceptedTypes = ['.pdf', '.docx', '.txt', '.md'],
  maxSize = 10 * 1024 * 1024, // 10MB
  multiple = true,
}: FileUploadProps) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<string>('');
  const { data: workspacesData } = useWorkspaces();
  
  const workspaces = workspacesData?.workspaces || [];

  const validateFile = (file: File): string | null => {
    // Check file size
    if (file.size > maxSize) {
      return `File size must be less than ${Math.round(maxSize / (1024 * 1024))}MB`;
    }

    // Check file type
    const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!acceptedTypes.includes(fileExtension)) {
      return `File type not supported. Accepted types: ${acceptedTypes.join(', ')}`;
    }

    return null;
  };

  const handleFiles = useCallback((files: FileList | null) => {
    if (!files) return;

    const fileArray = Array.from(files);
    const validFiles: File[] = [];
    const errors: string[] = [];

    fileArray.forEach((file) => {
      const error = validateFile(file);
      if (error) {
        errors.push(`${file.name}: ${error}`);
      } else {
        validFiles.push(file);
      }
    });

    if (errors.length > 0) {
      errors.forEach((error) => toast.error(error));
    }

    if (validFiles.length > 0) {
      setSelectedFiles(validFiles);
    }
  }, [acceptedTypes, maxSize]);

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    handleFiles(e.target.files);
  };

  const removeFile = (index: number) => {
    setSelectedFiles(files => files.filter((_, i) => i !== index));
  };

  const handleUpload = () => {
    if (selectedFiles.length > 0) {
      const workspaceId = selectedWorkspace === 'none' ? undefined : selectedWorkspace || undefined;
      onFilesSelected(selectedFiles, workspaceId);
      setSelectedFiles([]);
      setSelectedWorkspace('');
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  return (
    <div className="space-y-4">
      {/* Drop Zone */}
      <Card
        className={`border-2 border-dashed transition-colors ${
          dragActive
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-300 hover:border-gray-400'
        }`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        <CardContent className="p-8 text-center">
          <div className="flex flex-col items-center space-y-4">
            <div className={`p-4 rounded-full ${dragActive ? 'bg-blue-100' : 'bg-gray-100'}`}>
              <Upload className={`h-8 w-8 ${dragActive ? 'text-blue-600' : 'text-gray-600'}`} />
            </div>
            <div>
              <p className="text-lg font-medium text-gray-900">
                Drop files here or click to browse
              </p>
              <p className="text-sm text-gray-600 mt-1">
                Supports {acceptedTypes.join(', ')} up to {Math.round(maxSize / (1024 * 1024))}MB
              </p>
            </div>
            <input
              type="file"
              multiple={multiple}
              accept={acceptedTypes.join(',')}
              onChange={handleFileInput}
              className="hidden"
              id="file-upload"
              disabled={isUploading}
            />
            <Button
              variant="outline"
              onClick={() => document.getElementById('file-upload')?.click()}
              disabled={isUploading}
            >
              Browse Files
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Workspace Selection */}
      {selectedFiles.length > 0 && workspaces.length > 0 && (
        <div className="space-y-2">
          <Label htmlFor="workspace-select">Tag to Workspace (Optional)</Label>
          <Select value={selectedWorkspace} onValueChange={setSelectedWorkspace}>
            <SelectTrigger>
              <SelectValue placeholder="Select a workspace or leave untagged" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No workspace (organization-wide)</SelectItem>
              {workspaces.map((workspace) => (
                <SelectItem key={workspace.workspace_id} value={workspace.workspace_id}>
                  {workspace.team_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Selected Files */}
      {selectedFiles.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-gray-900">Selected Files:</h4>
          <div className="space-y-2">
            {selectedFiles.map((file, index) => (
              <div
                key={index}
                className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
              >
                <div className="flex items-center space-x-3">
                  <File className="h-5 w-5 text-gray-600" />
                  <div>
                    <p className="text-sm font-medium text-gray-900">{file.name}</p>
                    <p className="text-xs text-gray-600">{formatFileSize(file.size)}</p>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => removeFile(index)}
                  disabled={isUploading}
                  className="h-8 w-8 p-0"
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
          <Button
            onClick={handleUpload}
            disabled={isUploading || selectedFiles.length === 0}
            className="w-full"
          >
            {isUploading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                Uploading...
              </>
            ) : (
              <>
                <Upload className="h-4 w-4 mr-2" />
                Upload {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''}
              </>
            )}
          </Button>
        </div>
      )}
    </div>
  );
}