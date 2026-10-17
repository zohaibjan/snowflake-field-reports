import React, { useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, X, Check } from 'lucide-react';

function FileUploader({ label, icon: Icon, acceptedTypes, multiple, onFileSelect, file, disabled = false, disabledMessage = 'This uploader is temporarily disabled.' }) {
  const onDrop = useCallback((acceptedFiles) => {
    if (multiple) {
      onFileSelect(acceptedFiles);
    } else {
      onFileSelect(acceptedFiles[0]);
    }
  }, [multiple, onFileSelect]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: acceptedTypes,
    multiple,
    disabled
  });

  const handleRemoveFile = (e, index = null) => {
    e.stopPropagation();
    if (multiple && index !== null) {
      const newFiles = file.filter((_, i) => i !== index);
      onFileSelect(newFiles);
    } else {
      onFileSelect(multiple ? [] : null);
    }
  };

  const hasFiles = multiple ? (file && file.length > 0) : file;

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        {label}
      </label>
      
      <div
        {...getRootProps()}
        className={`
          border-2 border-dashed rounded-lg p-6 text-center transition-all
          ${disabled ? 'cursor-not-allowed opacity-70 border-gray-300 bg-gray-100' : 'cursor-pointer'}
          ${!disabled && isDragActive ? 'border-REFERENCE-navy bg-blue-50' : ''}
          ${!disabled && hasFiles ? 'bg-green-50 border-green-300' : 'bg-gray-50'}
        `}
      >
        <input {...getInputProps()} disabled={disabled} />
        
        <div className="flex flex-col items-center gap-2">
          {disabled ? (
            <>
              <Upload className="h-8 w-8 text-gray-400" />
              <p className="text-sm text-gray-600 text-center">
                {disabledMessage}
              </p>
            </>
          ) : hasFiles ? (
            <>
              <Check className="h-8 w-8 text-green-600" />
              {multiple && file ? (
                <div className="w-full">
                  <p className="text-sm font-semibold text-green-700 mb-2">
                    {file.length} file(s) selected
                  </p>
                  {file.map((f, idx) => (
                    <div key={idx} className="flex items-center justify-between bg-white p-2 rounded mb-1">
                      <span className="text-xs text-gray-700 truncate flex-1">{f.name}</span>
                      <button
                        onClick={(e) => handleRemoveFile(e, idx)}
                        className="ml-2 p-1 hover:bg-red-100 rounded"
                      >
                        <X className="h-3 w-3 text-red-600" />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="w-full">
                  <p className="text-sm font-semibold text-green-700">{file.name}</p>
                  <p className="text-xs text-gray-600">
                    {(file.size / (1024 * 1024)).toFixed(2)} MB
                  </p>
                  <button
                    onClick={handleRemoveFile}
                    className="mt-2 text-xs text-red-600 hover:text-red-800 flex items-center gap-1 mx-auto"
                  >
                    <X className="h-3 w-3" />
                    Remove
                  </button>
                </div>
              )}
            </>
          ) : (
            <>
              <Icon className="h-8 w-8 text-gray-400" />
              <p className="text-sm text-gray-600">
                {isDragActive ? 'Drop here' : 'Drag & drop or click'}
              </p>
              <p className="text-xs text-gray-500">{acceptedTypes}</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default FileUploader;
