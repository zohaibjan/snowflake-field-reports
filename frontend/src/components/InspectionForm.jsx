import React, { useState, useEffect, useCallback, useRef } from 'react';
import { sendTelemetry } from '../utils/telemetry';
import { Upload, FileAudio, Image, CheckCircle, AlertCircle, Loader, Download, Edit2, Save, X, Plus, Trash2, ChevronDown, Mic, Square, Play, Pause } from 'lucide-react';

// Use relative URL for production (nginx will proxy to backend)
const API_BASE_URL = import.meta.env.VITE_API_URL || '';

// central axios instance now lives in utils/axiosClient which sets withCredentials + CSRF init
import axiosInstance, { initCsrf } from '../utils/axiosClient';

// helper: attempt request with simple retry loop
async function withRetry(fn, retries = 2, delayMs = 1000) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      if (attempt === retries) break;
      await new Promise((r) => setTimeout(r, delayMs * Math.pow(2, attempt)));
    }
  }
  throw lastError;
}

// helper: upload files with concurrency limit
async function uploadFilesConcurrently(files, endpoint, formFieldName = 'image_file', options = {}) {
  const concurrency = options.concurrency || 3;
  const timeout = options.timeout || 120000; // 2 minutes per file as default

  const results = [];
  const queue = files.slice();

  async function worker() {
    while (queue.length > 0) {
      const file = queue.shift();
      const formData = new FormData();
      formData.append(formFieldName, file);

      const res = await withRetry(() => axiosInstance.post(endpoint, formData, { timeout }), 2, 1000);
      results.push(res.data.stage_filename);
    }
  }

  const workers = [];
  for (let i = 0; i < concurrency; i++) workers.push(worker());
  await Promise.all(workers);
  return results;
}

/** Convert Float32Array PCM to Int16Array */
function floatTo16BitPCM(float32) {
  const len = float32.length;
  const int16 = new Int16Array(len);
  for (let i = 0; i < len; i++) {
    let s = Math.max(-1, Math.min(1, float32[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return int16;
}

// Note: iOS detection remains below; recording option removed to avoid iOS/camera issues

/**
 * Hook: client-side MP3 recorder (uses lamejs to encode)
 * - lazy loads lamejs to avoid loading encoder for users who only upload files
 */
function useMp3Recorder({ kbps = 128, maxDurationMs = 5 * 60 * 1000 } = {}) {
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState(null);
  const [durationMs, setDurationMs] = useState(0);
  const [mp3Blob, setMp3Blob] = useState(null);
  const [level, setLevel] = useState(0);

  const streamRef = useRef(null);
  const ctxRef = useRef(null);
  const sourceRef = useRef(null);
  const procRef = useRef(null);
  const analyserRef = useRef(null);
  const encoderRef = useRef(null);
  const mp3ChunksRef = useRef([]);
  const timerRef = useRef(null);
  const startedAtRef = useRef(0);
  const mediaRecorderRef = useRef(null);
  const levelTimerRef = useRef(null);

  const start = async () => {
    try {
      setError(null);
      setMp3Blob(null);
      setDurationMs(0);
      mp3ChunksRef.current = [];

      // ask for audio permission
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) throw new Error('Web Audio API not supported in this browser');
      const audioCtx = new AudioContext();
      ctxRef.current = audioCtx;

      if (audioCtx.state === 'suspended') await audioCtx.resume();

      const source = audioCtx.createMediaStreamSource(stream);
      sourceRef.current = source;

      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 2048;
      analyserRef.current = analyser;
      source.connect(analyser);

      // check for MediaRecorder
      const supportedMimeTypes = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
      let mimeType = null;
      if (window.MediaRecorder) {
        for (const mt of supportedMimeTypes) {
          if (MediaRecorder.isTypeSupported(mt)) {
            mimeType = mt;
            break;
          }
        }
      }

      if (mimeType) {
        // use MediaRecorder
        const recorder = new MediaRecorder(stream, { mimeType });
        mediaRecorderRef.current = recorder;
        const chunks = [];
        recorder.ondataavailable = (e) => {
          if (e.data.size > 0) chunks.push(e.data);
        };
        recorder.onstop = async () => {
          try {
            const blob = new Blob(chunks, { type: mimeType });
            // decode to PCM
            const arrayBuffer = await blob.arrayBuffer();
            const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
            const pcm = audioBuffer.getChannelData(0);
            const pcm16 = floatTo16BitPCM(pcm);
            // lazy load lamejs
            const lameModule = await import('lamejs');
            const lamejs = lameModule.default || lameModule;
            const encoder = new lamejs.Mp3Encoder(1, audioBuffer.sampleRate, kbps);
            const mp3buf = encoder.encodeBuffer(pcm16);
            const mp3flush = encoder.flush();
            const mp3Blob = new Blob([mp3buf, mp3flush], { type: 'audio/mpeg' });
            setMp3Blob(mp3Blob);
          } catch (err) {
            console.error('MP3 encoding error', err);
            setError('Failed to encode MP3');
          }
        };
        recorder.start();
        // level meter for MediaRecorder
        levelTimerRef.current = setInterval(() => {
          if (analyserRef.current) {
            const bufferLength = analyserRef.current.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);
            analyserRef.current.getByteFrequencyData(dataArray);
            let peak = 0;
            for (let i = 0; i < bufferLength; i++) {
              peak = Math.max(peak, dataArray[i] / 255);
            }
            setLevel(peak);
          }
        }, 100);
      } else {
        // use ScriptProcessor method
        // lazy load encoder
        const lameModule = await import('lamejs');
        const lamejs = lameModule.default || lameModule;
        const sampleRate = audioCtx.sampleRate || 44100;
        const encoder = new lamejs.Mp3Encoder(1, sampleRate, kbps);
        encoderRef.current = encoder;
        // process audio via ScriptProcessor
        const bufferSize = 4096;
        const processor = audioCtx.createScriptProcessor(bufferSize, 1, 1);
        procRef.current = processor;
        source.connect(processor);
        try { processor.connect(audioCtx.destination); } catch (e) { /* ignore */ }
        processor.onaudioprocess = (e) => {
          const input = e.inputBuffer.getChannelData(0);
          // level meter
          let peak = 0;
          for (let i = 0; i < input.length; i++) peak = Math.max(peak, Math.abs(input[i]));
          setLevel(peak);
          // encode
          const pcm16 = floatTo16BitPCM(input);
          try {
            const mp3buf = encoderRef.current.encodeBuffer(pcm16);
            if (mp3buf && mp3buf.length > 0) mp3ChunksRef.current.push(new Uint8Array(mp3buf));
          } catch (err) {
            console.warn('MP3 encode error', err);
          }
        };
      }

      startedAtRef.current = Date.now();
      timerRef.current = setInterval(() => {
        const d = Date.now() - startedAtRef.current;
        setDurationMs(d);
        if (maxDurationMs && d >= maxDurationMs) {
          stop();
        }
      }, 200);

      setIsRecording(true);
    } catch (err) {
      console.error('Recorder start failure', err);
      setError(err?.message || String(err));
      stop(true);
    }
  };

  const stop = (silent = false) => {
    try {
      if (mediaRecorderRef.current) {
        mediaRecorderRef.current.stop();
      } else {
        // flush encoder
        if (encoderRef.current) {
          const mp3buf = encoderRef.current.flush();
          if (mp3buf && mp3buf.length > 0) mp3ChunksRef.current.push(new Uint8Array(mp3buf));
        }

        if (!silent && mp3ChunksRef.current.length > 0) {
          const blob = new Blob(mp3ChunksRef.current, { type: 'audio/mpeg' });
          setMp3Blob(blob);
        }
      }
    } catch (err) {
      console.error('Recorder stop error', err);
      setError(err?.message || String(err));
    } finally {
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = null;
      if (levelTimerRef.current) clearInterval(levelTimerRef.current);
      levelTimerRef.current = null;

      try { procRef.current?.disconnect(); } catch (e) {}
      try { sourceRef.current?.disconnect(); } catch (e) {}
      try { analyserRef.current?.disconnect(); } catch (e) {}
      try { ctxRef.current?.close(); } catch (e) {}
      try { streamRef.current?.getTracks()?.forEach(t => t.stop()); } catch (e) {}

      procRef.current = null;
      sourceRef.current = null;
      analyserRef.current = null;
      encoderRef.current = null;
      mp3ChunksRef.current = [];
      ctxRef.current = null;
      streamRef.current = null;
      mediaRecorderRef.current = null;
      setLevel(0);
      setIsRecording(false);
    }
  };

  return { isRecording, start, stop, error, durationMs, mp3Blob, level };
}

function InspectionForm() {
  // Form state
  const [inspectorName, setInspectorName] = useState('');
  const [contractorName, setContractorName] = useState('');
  const [siteAddress, setSiteAddress] = useState('');
  const [otherContractors, setOtherContractors] = useState('');
  
  // File state
  const [audioFile, setAudioFile] = useState(null);
  const [conversationFile, setConversationFile] = useState(null); // optional builder conversation
  const [conversationTranscriptionError, setConversationTranscriptionError] = useState(null);
  const [mainSiteImage, setMainSiteImage] = useState(null);
  const [generalPhotos, setGeneralPhotos] = useState([]); // General site photos (separate from defect photos)
  // UI: selected preview indices
  const [selectedGeneralPreviewIndex, setSelectedGeneralPreviewIndex] = useState(null);
  const [selectedDefectPreview, setSelectedDefectPreview] = useState({}); // { defectId: index }
  
  // Workflow state
  const [currentSection, setCurrentSection] = useState('basic'); // basic, transcript, defects, generate
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState(null);
  
  // Transcript state
  const [transcript, setTranscript] = useState('');
  const [isEditingTranscript, setIsEditingTranscript] = useState(false);
  const [conversationTranscript, setConversationTranscript] = useState('');
  const [isEditingConversationTranscript, setIsEditingConversationTranscript] = useState(false);
  
  // Defects state
  const [defects, setDefects] = useState([]); // [{id, code, category, subcategory, standard, defect_found, non_compliance, evidence_quote, photos: []}]
  
  // Report state
  const [reportReady, setReportReady] = useState(false);
  const [reportData, setReportData] = useState(null);
  
  // Backend readiness
  const [backendReady, setBackendReady] = useState(false);
  const [backendStatusMessage, setBackendStatusMessage] = useState('Checking backend readiness...');
  const [isCheckingBackend, setIsCheckingBackend] = useState(true);
  const [showOptional, setShowOptional] = useState(false); // collapse optional inputs
  // Refs for file inputs so we can programmatically trigger the native picker on mobile devices
  const audioInputRef = useRef(null);
  const mainSiteInputRef = useRef(null);
  const generalPhotosInputRef = useRef(null);
  const convInputRef = useRef(null);
  // Detect iOS/iPad â€” used to show helpful hints about file picker behavior
  const [isIOS, setIsIOS] = useState(false);
  const [isSafari, setIsSafari] = useState(false);
  const [fileSelectFailed, setFileSelectFailed] = useState(false);
  // Recorder hook (lazy-loads encoder only when needed)
  const recorder = useMp3Recorder({ kbps: 128, maxDurationMs: 5 * 60 * 1000 });

  // Preview and playback state for recorded or uploaded audio
  const [audioPreviewUrl, setAudioPreviewUrl] = useState(null);
  const [isPreviewPlaying, setIsPreviewPlaying] = useState(false);
  const audioElemRef = useRef(null);
  // audioMode removed â€” we always use upload-only control to avoid iOS recording issues

  // When recorder produces a blob, turn it into a File and show preview
  useEffect(() => {
    if (recorder.mp3Blob) {
      const f = new File([recorder.mp3Blob], `inspection-recording-${Date.now()}.mp3`, { type: 'audio/mpeg' });
      setAudioFile(f);
      if (audioPreviewUrl) URL.revokeObjectURL(audioPreviewUrl);
      const url = URL.createObjectURL(recorder.mp3Blob);
      setAudioPreviewUrl(url);
    }
    // cleanup on unmount
    return () => {
      if (audioPreviewUrl) URL.revokeObjectURL(audioPreviewUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recorder.mp3Blob]);

  const checkBackendStatus = useCallback(async () => {
    setIsCheckingBackend(true);
    try {
      const base = (API_BASE_URL || '').replace(/\/$/, '');
      const healthUrl = `${base}/health` || '/health';
      const response = await axiosInstance.get(healthUrl, { timeout: 5000 });
      if (response.data?.status === 'healthy') {
        setBackendReady(true);
        setBackendStatusMessage('Backend is ready. You can start your report.');
      } else {
        setBackendReady(false);
        setBackendStatusMessage(response.data?.message || 'Backend is starting up.');
      }
    } catch (err) {
      setBackendReady(false);
      setBackendStatusMessage(err.response?.data?.message || err.message || 'Unable to reach backend service.');
    } finally {
      setIsCheckingBackend(false);
    }
  }, []);

  useEffect(() => {
    checkBackendStatus();
    // Initialize CSRF token for state-changing requests (double-submit cookie pattern)
    initCsrf().catch(() => {});
  }, [checkBackendStatus]);

  useEffect(() => {
    // Running in browser only
    if (typeof navigator !== 'undefined' && navigator) {
      const ua = navigator.userAgent || '';
      const iOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
      setIsIOS(iOS);
      const isSafariUA = /Safari/.test(ua) && !/CriOS|FxiOS|OPiOS|EdgiOS|Chrome|Chromium/.test(ua);
      setIsSafari(Boolean(isSafariUA));
      // keep simple iOS detection only; audio is upload-only for all Apple platforms
    }
  }, []);
  
  // File handlers
  const handleAudioFileChange = (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) {
      setAudioFile(file);
      setError(null);
      setFileSelectFailed(false);
      if (audioPreviewUrl) URL.revokeObjectURL(audioPreviewUrl);
      setAudioPreviewUrl(URL.createObjectURL(file));
    } else {
      // Some iOS/webview environments return no files when selection fails â€” surface a helpful hint
      console.warn('No file was selected (empty FileList). This commonly occurs in embedded webviews / iOS contexts.');
      setFileSelectFailed(true);
      try { sendTelemetry('file_select_failed', { element: 'audioFile', isIOS, isSafari, ua: navigator?.userAgent }); } catch (e) {}
    }
  };

  const handleConversationFileChange = (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) {
      setConversationFile(file);
      setError(null);
      setFileSelectFailed(false);
    } else {
      console.warn('No conversation file was selected (empty FileList). This commonly occurs in embedded webviews / iOS contexts.');
      setFileSelectFailed(true);
      try { sendTelemetry('file_select_failed', { element: 'conversationFile', isIOS, isSafari, ua: navigator?.userAgent }); } catch (e) {}
    }
  };
  
  const handleMainSiteImageChange = (e) => {
    const file = e.target.files && e.target.files[0];
    if (mainSiteImage) {
      // Revoke previous object URL if any
      URL.revokeObjectURL(mainSiteImage.previewUrl);
    }
    if (file) {
      // Attach preview URL for cleanup
      file.previewUrl = URL.createObjectURL(file);
      setMainSiteImage(file);
      setError(null);
      setFileSelectFailed(false);
    } else {
      console.warn('Main site image selection returned no file (empty FileList).');
      setFileSelectFailed(true);
      try { sendTelemetry('file_select_failed', { element: 'mainSiteImage', isIOS, isSafari, ua: navigator?.userAgent }); } catch (e) {}
    }
  };
  
  const handleGeneralPhotosAdd = (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length > 0) {
      // Attach preview URLs for cleanup
      files.forEach(file => { file.previewUrl = URL.createObjectURL(file); });
      setGeneralPhotos(prev => [...prev, ...files]);
      setFileSelectFailed(false);
    } else {
      console.warn('General photos selection returned no files (empty FileList).');
      setFileSelectFailed(true);
      try { sendTelemetry('file_select_failed', { element: 'generalPhotos', isIOS, isSafari, ua: navigator?.userAgent }); } catch (e) {}
    }
    setError(null);
  };
  
  const handleGeneralPhotoRemove = (photoIndex) => {
    setGeneralPhotos(prev => {
      // Revoke object URL for removed photo
      if (prev[photoIndex]?.previewUrl) {
        URL.revokeObjectURL(prev[photoIndex].previewUrl);
      }
      const next = prev.filter((_, idx) => idx !== photoIndex);
      if (selectedGeneralPreviewIndex !== null) {
        if (photoIndex === selectedGeneralPreviewIndex) {
          setSelectedGeneralPreviewIndex(null);
        } else if (photoIndex < selectedGeneralPreviewIndex) {
          setSelectedGeneralPreviewIndex(i => (i === null ? null : i - 1));
        }
      }
      return next;
    });
  };
  
  const handleDefectPhotoAdd = (defectId, e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) {
      console.warn('No defect photos selected (empty FileList).');
      setFileSelectFailed(true);
      try { sendTelemetry('file_select_failed', { element: 'defectPhoto', defectId, isIOS, isSafari, ua: navigator?.userAgent }); } catch (e) {}
      return;
    }
    // Attach preview URLs for cleanup
    files.forEach(file => { file.previewUrl = URL.createObjectURL(file); });
    setFileSelectFailed(false);
    setDefects(prev => prev.map(defect => {
      if (defect.id === defectId) {
        return {
          ...defect,
          photos: [...(defect.photos || []), ...files]
        };
      }
      return defect;
    }));
  };
  
  const handleDefectPhotoRemove = (defectId, photoIndex) => {
    setDefects(prev => prev.map(defect => {
      if (defect.id === defectId) {
        // Revoke object URL for removed photo
        if (defect.photos[photoIndex]?.previewUrl) {
          URL.revokeObjectURL(defect.photos[photoIndex].previewUrl);
        }
        return {
          ...defect,
          photos: defect.photos.filter((_, idx) => idx !== photoIndex)
        };
      }
      return defect;
    }));
  };

  const toggleGeneralPreview = (index) => {
    setSelectedGeneralPreviewIndex(prev => (prev === index ? null : index));
  };

  const toggleDefectPreview = (defectId, index) => {
    setSelectedDefectPreview(prev => {
      const existing = prev[defectId];
      const next = { ...prev };
      if (existing === index) {
        delete next[defectId];
      } else {
        next[defectId] = index;
      }
      return next;
    });
  };
  
  const handleDefectUpdate = (defectId, field, value) => {
    setDefects(prev => prev.map(defect => {
      if (defect.id === defectId) {
        return { ...defect, [field]: value };
      }
      return defect;
    }));
  };
  
  const handleDefectRemove = (defectId) => {
    setDefects(prev => prev.filter(defect => defect.id !== defectId));
  };
  
  // Section 1: Process Basic Info and Audio
  const handleProcessAudio = async () => {
    if (!inspectorName || !contractorName || !siteAddress) {
      setError('Please fill in Reviewer Name, Supplier Name, and Site Address');
      return;
    }
    
    if (!mainSiteImage) {
      setError('Please upload a main site photo');
      return;
    }
    
    if (!audioFile) {
      setError('Please upload an audio recording of the inspection');
      return;
    }
    
    if (!backendReady) {
      setError('Backend is still starting up. Please wait.');
      return;
    }
    
    setError(null);
    setIsProcessing(true);
    
    try {
      // Step 1: Upload audio (inspection) and optional builder conversation audio
      const audioFormData = new FormData();
      audioFormData.append('audio_file', audioFile);
      const audioResponse = await withRetry(() => axiosInstance.post('/api/upload-audio', audioFormData, { timeout: 180000 }), 2, 1000);
      const stageFilename = audioResponse.data.stage_filename;
      
      // Step 2: Transcribe inspection audio
      const transcribeFormData = new FormData();
      transcribeFormData.append('stage_filename', stageFilename);
      const transcribeResponse = await axiosInstance.post('/api/transcribe', transcribeFormData, {
        timeout: 600000  // 10 minutes for AI transcription
      });
      
      setTranscript(transcribeResponse.data.transcript);

      // If user provided a builder conversation file, upload & transcribe it as well
      if (conversationFile) {
        try {
          const convFormData = new FormData();
          convFormData.append('audio_file', conversationFile);
          const convUpload = await axiosInstance.post('/api/upload-conversation', convFormData, { timeout: 180000 });
          const convStage = convUpload.data.stage_filename;

          const convTransForm = new FormData();
          convTransForm.append('stage_filename', convStage);
          const convTransResponse = await axiosInstance.post('/api/transcribe-conversation', convTransForm, { timeout: 600000 });
          setConversationTranscript(convTransResponse.data.transcript);
          setConversationTranscriptionError(null);
        } catch (convErr) {
          const errorMsg = convErr?.response?.data?.detail || convErr?.message || String(convErr)
          console.warn('Conversation transcription failed or manual input needed:', errorMsg);
          setConversationTranscriptionError(errorMsg?.message || errorMsg || 'Conversation transcription failed. You can type it manually in the transcript section.');
          // Allow the user to manually input the conversation transcript later
        }
      }
      
      // Extract defects and add IDs
      const detectedDefects = (transcribeResponse.data.defects || []).map((defect, idx) => ({
        ...defect,
        id: `defect-${Date.now()}-${idx}`,
        photos: []
      }));
      
      setDefects(detectedDefects);
      setCurrentSection('transcript');
      
    } catch (err) {
      console.error('Error processing audio:', err);
      const errorDetail = err.response?.data?.detail;
      const errorMessage = typeof errorDetail === 'object' 
        ? errorDetail.message || JSON.stringify(errorDetail)
        : errorDetail || err.message || 'An error occurred';
      setError(errorMessage);
    } finally {
      setIsProcessing(false);
    }
  };
  
  // Section 2: Confirm Transcript
  const handleConfirmTranscript = () => {
    if (!transcript || transcript.trim().length === 0) {
      setError('Transcript cannot be empty');
      return;
    }
    setError(null);
    setCurrentSection('defects');
  };
  
  // Section 3: Generate Report
  const handleGenerateReport = async () => {
    if (defects.length === 0) {
      setError('No defects detected. Cannot generate report.');
      return;
    }
    
    setError(null);
    setIsProcessing(true);
    
    try {
      // Upload main site image if provided
      let mainSiteStageFile = null;
      if (mainSiteImage) {
        const mainImageFormData = new FormData();
        mainImageFormData.append('image_file', mainSiteImage);
        const mainImageResponse = await withRetry(() => axiosInstance.post('/api/upload-image', mainImageFormData, { timeout: 180000 }), 2, 1000);
        mainSiteStageFile = mainImageResponse.data.stage_filename;
      }
      
      // Upload general site photos if provided
      const generalPhotoStageFiles = [];
      if (generalPhotos.length > 0) {
        // Upload general photos concurrently with limited concurrency
        const stageFiles = await uploadFilesConcurrently(generalPhotos, '/api/upload-image', 'image_file', { concurrency: 3, timeout: 180000 });
        generalPhotoStageFiles.push(...stageFiles);
      }
      
      // Upload defect photos and organize by defect
      const defectsWithStageFiles = [];
      for (const defect of defects) {
        const stageFiles = [];
        if ((defect.photos || []).length > 0) {
          const stageFilesForDefect = await uploadFilesConcurrently(defect.photos || [], '/api/upload-image', 'image_file', { concurrency: 2, timeout: 180000 });
          stageFiles.push(...stageFilesForDefect);
        }
        
        defectsWithStageFiles.push({
          defect_code: defect.defect_code || defect.code,
          category: defect.category,
          subcategory: defect.subcategory,
          standard: defect.standard,
          defect_found: defect.defect_found,
          non_compliance: defect.non_compliance,
          evidence_quote: defect.evidence_quote,
          caption: defect.defect_found, // Use defect description as caption
          photos: stageFiles
        });
      }
      
      // Generate report
      const reportFormData = new FormData();
      reportFormData.append('inspector_name', inspectorName);
      reportFormData.append('contractor_name', contractorName);
      reportFormData.append('site_address', siteAddress);
      reportFormData.append('other_contractors', otherContractors || 'N/A');
      reportFormData.append('inspection_date', new Date().toISOString().split('T')[0]);
      reportFormData.append('transcript', transcript);
      reportFormData.append('audio_filename', audioFile?.name || '');
      reportFormData.append('is_compliant', 'false'); // Always non-compliant if we have defects
      reportFormData.append('defects_with_photos', JSON.stringify(defectsWithStageFiles));
      // Optional builder conversation transcript
      if (conversationTranscript) {
        reportFormData.append('conversation_transcript', conversationTranscript);
      }
      
      if (mainSiteStageFile) {
        reportFormData.append('main_site_image', mainSiteStageFile);
      }
      
      if (generalPhotoStageFiles.length > 0) {
        reportFormData.append('general_photos', JSON.stringify(generalPhotoStageFiles));
      }
      
      const reportResponse = await axiosInstance.post('/api/generate-report', reportFormData, {
        responseType: 'blob',
        timeout: 600000  // 10 minutes
      });
      
      setReportReady(true);
      setReportData(reportResponse.data);
      try { sendTelemetry('generate_report_success', { app_name: 'field_reporting_app', report_bytes: (reportResponse.data && reportResponse.data.size) || null }); } catch (e) {}
      setCurrentSection('generate');
      
    } catch (err) {
      console.error('Error generating report:', err);
      const errorDetail = err.response?.data?.detail;
      const errorMessage = typeof errorDetail === 'object' 
        ? errorDetail.message || JSON.stringify(errorDetail)
        : errorDetail || err.message || 'An error occurred';
      setError(errorMessage);
      try { sendTelemetry('generate_report_failed', { app_name: 'field_reporting_app', error: String(errorMessage) }); } catch (e) {}
    } finally {
      setIsProcessing(false);
    }
  };
  
  const handleDownloadReport = () => {
    if (reportData) {
      const url = window.URL.createObjectURL(new Blob([reportData]));
      const link = document.createElement('a');
      link.href = url;
      const timestamp = new Date().toISOString().split('T')[0];
      const sanitizedAddress = siteAddress.replace(/[^a-zA-Z0-9]/g, '_').substring(0, 30);
      link.setAttribute('download', `${contractorName.replace(/[^a-zA-Z0-9]/g, '_')}_${sanitizedAddress}_${timestamp}.docx`);
      document.body.appendChild(link);
      link.click();
      link.parentNode.removeChild(link);
    }
  };
  
  const handleStartNewInspection = () => {
    setInspectorName('');
    setContractorName('');
    setSiteAddress('');
    setOtherContractors('');
    setAudioFile(null);
    if (audioPreviewUrl) {
      URL.revokeObjectURL(audioPreviewUrl);
      setAudioPreviewUrl(null);
    }
    if (mainSiteImage?.previewUrl) {
      URL.revokeObjectURL(mainSiteImage.previewUrl);
    }
    setMainSiteImage(null);
    // Revoke all general photo URLs
    generalPhotos.forEach(photo => { if (photo.previewUrl) URL.revokeObjectURL(photo.previewUrl); });
    setGeneralPhotos([]);
    setTranscript('');
    // Revoke all defect photo URLs
    defects.forEach(defect => { (defect.photos || []).forEach(photo => { if (photo.previewUrl) URL.revokeObjectURL(photo.previewUrl); }); });
    setDefects([]);
    setReportReady(false);
    setReportData(null);
    setCurrentSection('basic');
    setError(null);
  };
  
  // Cleanup all object URLs on unmount
  useEffect(() => {
    return () => {
      if (audioPreviewUrl) URL.revokeObjectURL(audioPreviewUrl);
      if (mainSiteImage?.previewUrl) URL.revokeObjectURL(mainSiteImage.previewUrl);
      generalPhotos.forEach(photo => { if (photo.previewUrl) URL.revokeObjectURL(photo.previewUrl); });
      defects.forEach(defect => { (defect.photos || []).forEach(photo => { if (photo.previewUrl) URL.revokeObjectURL(photo.previewUrl); }); });
    };
  }, []);

  return (
    <div className="bg-white rounded-lg shadow-lg p-8 max-w-6xl mx-auto" role="main" aria-label="Report Form">
      {/* Header */}
      <div className="text-center mb-8">
        <h1 className="text-4xl font-bold text-REFERENCE-navy mb-2">Field Notes Studio</h1>
      </div>
      
      {/* Backend Status */}
      {isCheckingBackend && (
        <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-3">
          <Loader className="w-5 h-5 text-blue-600 animate-spin" />
          <span className="text-blue-800">{backendStatusMessage}</span>
        </div>
      )}
      
      {!backendReady && !isCheckingBackend && (
        <div className="mb-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-600" />
          <span className="text-yellow-800">{backendStatusMessage}</span>
        </div>
      )}
      
      {/* Error Display */}
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-600" />
          <span className="text-red-800">{error}</span>
        </div>
      )}
      
      {/* Progress Indicator */}
      <div className="mb-8 flex items-center justify-between">
        <div className={`flex items-center gap-2 ${currentSection === 'basic' ? 'text-REFERENCE-navy font-semibold' : 'text-gray-400'}`}>
          <div className={`w-8 h-8 rounded-full flex items-center justify-center ${currentSection === 'basic' ? 'bg-REFERENCE-navy text-white' : 'bg-gray-200'}`}>1</div>
          <span>Basic Info</span>
        </div>
        <div className={`flex-1 h-1 mx-4 ${['transcript', 'defects', 'generate'].includes(currentSection) ? 'bg-REFERENCE-navy' : 'bg-gray-200'}`}></div>
        
        <div className={`flex items-center gap-2 ${currentSection === 'transcript' ? 'text-REFERENCE-navy font-semibold' : currentSection === 'basic' ? 'text-gray-400' : 'text-gray-600'}`}>
          <div className={`w-8 h-8 rounded-full flex items-center justify-center ${currentSection === 'transcript' ? 'bg-REFERENCE-navy text-white' : ['defects', 'generate'].includes(currentSection) ? 'bg-green-500 text-white' : 'bg-gray-200'}`}>
            {['defects', 'generate'].includes(currentSection) ? <CheckCircle className="w-5 h-5" /> : '2'}
          </div>
          <span>Transcript</span>
        </div>
        <div className={`flex-1 h-1 mx-4 ${['defects', 'generate'].includes(currentSection) ? 'bg-REFERENCE-navy' : 'bg-gray-200'}`}></div>
        
        <div className={`flex items-center gap-2 ${currentSection === 'defects' ? 'text-REFERENCE-navy font-semibold' : ['basic', 'transcript'].includes(currentSection) ? 'text-gray-400' : 'text-gray-600'}`}>
          <div className={`w-8 h-8 rounded-full flex items-center justify-center ${currentSection === 'defects' ? 'bg-REFERENCE-navy text-white' : currentSection === 'generate' ? 'bg-green-500 text-white' : 'bg-gray-200'}`}>
            {currentSection === 'generate' ? <CheckCircle className="w-5 h-5" /> : '3'}
          </div>
          <span>Defects</span>
        </div>
        <div className={`flex-1 h-1 mx-4 ${currentSection === 'generate' ? 'bg-REFERENCE-navy' : 'bg-gray-200'}`}></div>
        
        <div className={`flex items-center gap-2 ${currentSection === 'generate' ? 'text-REFERENCE-navy font-semibold' : 'text-gray-400'}`}>
          <div className={`w-8 h-8 rounded-full flex items-center justify-center ${currentSection === 'generate' ? 'bg-REFERENCE-navy text-white' : 'bg-gray-200'}`}>4</div>
          <span>Report</span>
        </div>
      </div>
      
      {/* Section 1: Basic Info */}
      {currentSection === 'basic' && (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-REFERENCE-navy border-l-4 border-REFERENCE-navy pl-4 mb-6">Basic Information</h2>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Reviewer Name *</label>
              <input
                type="text"
                value={inspectorName}
                onChange={(e) => setInspectorName(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-REFERENCE-navy focus:border-transparent"
                placeholder="John Smith"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Supplier Name *</label>
              <input
                type="text"
                value={contractorName}
                onChange={(e) => setContractorName(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-REFERENCE-navy focus:border-transparent"
                placeholder="ABC Construction Pty Ltd"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Site Address *</label>
              <textarea
                value={siteAddress}
                onChange={(e) => setSiteAddress(e.target.value)}
                rows="3"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-REFERENCE-navy focus:border-transparent"
                placeholder="123 Main Street, Suburb, QLD 4000"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Other Contractors</label>
              <textarea
                value={otherContractors}
                onChange={(e) => setOtherContractors(e.target.value)}
                rows="3"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-REFERENCE-navy focus:border-transparent"
                placeholder="Contractor 2, Contractor 3"
              />
            </div>
          </div>
          
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Main Site Photo *</label>
              <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-REFERENCE-navy transition-colors">
                <input
                  ref={mainSiteInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleMainSiteImageChange}
                  className="hidden"
                  id="mainSiteImage"
                />
                <label htmlFor="mainSiteImage" className="cursor-pointer">
                  <Image className="w-12 h-12 mx-auto text-gray-400 mb-2" />
                  <p className="text-sm text-gray-600">
                    {mainSiteImage ? mainSiteImage.name : 'Click to upload main site photo'}
                  </p>
                </label>
                <div className="mt-2 md:hidden">
                  <button type="button" onClick={(e) => { e.preventDefault(); if (mainSiteInputRef && mainSiteInputRef.current) mainSiteInputRef.current.click(); }} className="px-3 py-1 bg-REFERENCE-navy text-white rounded text-xs">Choose</button>
                </div>
                {fileSelectFailed && (
                  <p className="text-xs text-yellow-700 mt-2">No file was selected — if you're in an embedded webview try opening this page in a full browser or choose the image from the Files or Photos app.</p>
                )}
              </div>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Audio Recording *</label>
              <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-REFERENCE-navy transition-colors">
                {/* Upload-only UI: simple file input + preview */}






                <>
                    <input
                      ref={audioInputRef}
                      type="file"
                      accept="audio/*,.mp3,.m4a,.wav"
                      onChange={handleAudioFileChange}
                      className="hidden"
                      id="audioFile"
                    />
                    <label htmlFor="audioFile" className="cursor-pointer">
                      <FileAudio className="w-12 h-12 mx-auto text-gray-400 mb-2" />
                      <p className="text-sm text-gray-600">{audioFile ? audioFile.name : 'Click to upload audio recording (required)'}</p>
                    </label>
                    {/* shared preview for uploaded or recorded audio */}
                    {audioPreviewUrl && (
                      <div className="mt-3 flex items-center gap-3 justify-center">
                        <audio ref={audioElemRef} src={audioPreviewUrl} controls onPlay={() => setIsPreviewPlaying(true)} onPause={() => setIsPreviewPlaying(false)} />
                        <button onClick={() => {
                          const el = audioElemRef.current; if (!el) return; if (isPreviewPlaying) { el.pause(); setIsPreviewPlaying(false); } else { el.play().then(() => setIsPreviewPlaying(true)).catch(() => setIsPreviewPlaying(false)); }
                        }} className="px-3 py-2 border border-gray-300 rounded-lg text-sm flex items-center gap-2">{isPreviewPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />} {isPreviewPlaying ? 'Pause' : 'Play'}</button>
                        <span className="text-xs text-gray-500">{audioFile?.name}</span>
                      </div>
                    )}
                    <div className="mt-2 md:hidden">
                      <button type="button" onClick={(e) => { e.preventDefault(); if (audioInputRef && audioInputRef.current) audioInputRef.current.click(); }} className="px-3 py-1 bg-REFERENCE-navy text-white rounded text-xs">Choose</button>
                      <p className="text-xs text-gray-600 mt-2">Audio recording is required for report generation.</p>
                    </div>
                    {/* On some embedded browsers the picker may be limited — try the device Files app if the picker doesn't show audio files. */}

                    {fileSelectFailed && (
                      <div className="mt-3 p-3 bg-yellow-50 border border-yellow-200 rounded text-sm text-yellow-800">
                        File selection returned no file. On iPad / embedded browsers this can happen if the webview blocks the file picker — try opening this page in a full browser or use the device Files app to choose the file. If the problem persists, please capture console logs and share them with the dev team.
                      </div>
                    )}
                  </>
              </div>
            </div>
            {/* Builder conversation input moved into optional block below */}
          </div>
          
          <div className="mt-6">
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-gray-700">Optional Inputs</label>
              <button
                onClick={() => setShowOptional(!showOptional)}
                aria-expanded={showOptional}
                className="flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-100 focus:outline-none"
              >
                <span className="sr-only">{showOptional ? 'Hide optional inputs' : 'Show optional inputs'}</span>
                <ChevronDown className={`w-4 h-4 text-REFERENCE-navy transform transition-transform duration-200 ${showOptional ? 'rotate-180' : ''}`} />
              </button>
            </div>

            {showOptional && (
              <>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 hover:border-REFERENCE-navy transition-colors h-64 flex flex-col justify-between overflow-hidden">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">General Site Photos (Optional)</label>
                      <p className="text-xs text-gray-500 mb-3">Upload additional site overview/context photos (separate from defect-specific photos)</p>
                    </div>

                    {/* Keep thumbnail area scrollable but contained inside the dashed box */}
                    <div className="flex-1 overflow-hidden">
                      <input
                        ref={generalPhotosInputRef}
                        type="file"
                        accept="image/*"
                        multiple
                        onChange={handleGeneralPhotosAdd}
                        className="hidden"
                        id="generalPhotos"
                      />
                      <label htmlFor="generalPhotos" className="cursor-pointer block text-center mb-4">
                        <Image className="w-12 h-12 mx-auto text-gray-400 mb-2" />
                        <p className="text-sm text-gray-600">Click to upload general site photos (can select multiple)</p>
                      </label>
                      <div className="mt-2 md:hidden text-center">
                        <button type="button" onClick={(e) => { e.preventDefault(); if (generalPhotosInputRef && generalPhotosInputRef.current) generalPhotosInputRef.current.click(); }} className="px-3 py-1 bg-REFERENCE-navy text-white rounded text-xs">Choose</button>
                        {fileSelectFailed && <p className="text-xs text-yellow-700 mt-2">No files selected — try opening this page in a full browser or use the Files app if you're in an embedded webview.</p>}
                      </div>

                      {generalPhotos.length > 0 && (
                        <div className="mt-4 max-h-36 overflow-hidden">
                          {/* Mobile-first horizontal scroller */}
                          <div className="flex gap-3 overflow-x-auto photo-scroller hide-scrollbar py-1 md:hidden max-h-28">
                            {generalPhotos.map((photo, idx) => (
                              <div key={idx} className="flex-none w-36 sm:w-44 relative group">
                                <button
                                  onClick={() => toggleGeneralPreview(idx)}
                                  className="w-full h-28 rounded-lg overflow-hidden focus:outline-none thumbnail-preview"
                                  aria-label={`Preview ${photo.name}`}
                                >
                                  <img src={URL.createObjectURL(photo)} alt={`General ${idx + 1}`} className="w-full h-full object-cover" />
                                </button>

                                <button onClick={() => handleGeneralPhotoRemove(idx)} className="absolute top-1 right-1 bg-red-500 text-white p-1 rounded-full opacity-0 group-hover:opacity-100 transition-opacity">
                                  <X className="w-4 h-4" />
                                </button>
                                <p className="text-xs text-gray-600 mt-1 truncate text-center">{photo.name}</p>
                              </div>
                            ))}
                          </div>

                          {/* Desktop / larger screens use a 3-column grid for denser layouts */}
                          <div className="hidden md:grid md:grid-cols-3 md:gap-4 max-h-36 overflow-auto">
                            {generalPhotos.map((photo, idx) => (
                              <div key={idx} className="relative group">
                                <button
                                  onClick={() => toggleGeneralPreview(idx)}
                                  className="w-full h-32 rounded-lg overflow-hidden focus:outline-none thumbnail-preview"
                                  aria-label={`Preview ${photo.name}`}
                                >
                                  <img src={URL.createObjectURL(photo)} alt={`General ${idx + 1}`} className="w-full h-full object-cover" />
                                </button>
                                <button onClick={() => handleGeneralPhotoRemove(idx)} className="absolute top-2 right-2 bg-red-500 text-white p-1 rounded-full opacity-0 group-hover:opacity-100 transition-opacity">
                                  <X className="w-4 h-4" />
                                </button>
                                <p className="text-xs text-gray-600 mt-1 truncate">{photo.name}</p>
                              </div>
                            ))}
                          </div>

                          {/* Inline preview pane (one view kept inline under the scroller/grid) */}
                          {selectedGeneralPreviewIndex !== null && generalPhotos[selectedGeneralPreviewIndex] && (
                            <div className="mt-3 rounded-lg border border-gray-200 p-3 bg-gray-50 max-h-44 overflow-auto">
                              <div className="flex items-start justify-between gap-3">
                                <div className="flex-1">
                                  <img src={URL.createObjectURL(generalPhotos[selectedGeneralPreviewIndex])} alt={generalPhotos[selectedGeneralPreviewIndex].name} className="w-full h-40 object-contain rounded-lg bg-white" />
                                  <p className="text-xs text-gray-600 mt-2 truncate">{generalPhotos[selectedGeneralPreviewIndex].name}</p>
                                </div>
                                <div className="ml-3 flex-shrink-0">
                                  <button onClick={() => setSelectedGeneralPreviewIndex(null)} className="px-3 py-1 border border-gray-300 rounded-lg text-xs text-gray-700 hover:bg-gray-100">Close</button>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 hover:border-REFERENCE-navy transition-colors h-64 flex flex-col justify-between">
                    <label className="block text-sm font-medium text-gray-700 mb-2">Review Conversation (Optional)</label>
                    <p className="text-xs text-gray-500 mb-2">If you recorded a short discussion with a participant (context / clarifications), upload it here and we'll include a transcript in the report.</p>

                    <div className="text-center mt-4">
                      <input
                        ref={convInputRef}
                        type="file"
                        accept=".mp3,.m4a,.wav,audio/*"
                        onChange={handleConversationFileChange}
                        className="hidden"
                        id="conversationFile"
                      />
                      <label htmlFor="conversationFile" className="cursor-pointer inline-block">
                        <FileAudio className="w-12 h-12 mx-auto text-gray-400 mb-2" />
                        <p className="text-sm text-gray-600">{conversationFile ? conversationFile.name : 'Click to upload conversation recording (optional)'}</p>
                        <div className="mt-2 md:hidden">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.preventDefault();
                              if (convInputRef && convInputRef.current) convInputRef.current.click();
                            }}
                            className="px-3 py-1 bg-REFERENCE-navy text-white rounded text-xs"
                          >
                            Choose
                          </button>
                        </div>
                        {/* On some embedded browsers the picker may be limited — try the device Files app or Voice Memos if needed. */}
                      </label>

                      {conversationFile && (
                        <div className="mt-2 text-xs text-gray-500">
                          <p>We will transcribe this and include the conversation transcript in the final report. You can edit it later.</p>
                          {conversationTranscriptionError && (
                            <p className="text-xs text-red-600 mt-2">Conversation transcription failed: {conversationTranscriptionError}</p>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
          
          <div className="flex justify-end mt-8">
            <button
              onClick={handleProcessAudio}
              disabled={isProcessing || !backendReady}
              className="px-8 py-3 bg-REFERENCE-navy text-white rounded-lg hover:bg-REFERENCE-navy-dark disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center gap-2 transition-colors"
            >
              {isProcessing ? (
                <>
                  <Loader className="w-5 h-5 animate-spin" />
                  Processing Audio...
                </>
              ) : (
                <>
                  Process Audio & Continue
                  <CheckCircle className="w-5 h-5" />
                </>
              )}
            </button>
          </div>
        </div>
      )}
      
      {/* Section 2: Transcript Review */}
      {currentSection === 'transcript' && (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-REFERENCE-navy border-l-4 border-REFERENCE-navy pl-4 mb-6">Review Transcript</h2>
          
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
            <p className="text-sm text-blue-800">Review the transcript below. You can edit it if needed, then click "Confirm & Continue" to proceed to defect items.</p>
          </div>
          
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-gray-700">Transcript</label>
              <button
                onClick={() => setIsEditingTranscript(!isEditingTranscript)}
                className="text-sm text-REFERENCE-navy hover:underline flex items-center gap-1"
              >
                {isEditingTranscript ? <Save className="w-4 h-4" /> : <Edit2 className="w-4 h-4" />}
                {isEditingTranscript ? 'Done Editing' : 'Edit Transcript'}
              </button>
            </div>
            
            {isEditingTranscript ? (
              <textarea
                value={transcript}
                onChange={(e) => setTranscript(e.target.value)}
                rows="12"
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-REFERENCE-navy focus:border-transparent font-mono text-sm"
              />
            ) : (
              <div className="w-full px-4 py-3 border border-gray-300 rounded-lg bg-gray-50 whitespace-pre-wrap font-mono text-sm max-h-96 overflow-y-auto">
                {transcript}
              </div>
              
            )}

            {/* Conversation transcript (optional) */}
            <div className="mt-6">
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm font-medium text-gray-700">Review Conversation (Optional)</label>
                <button
                  onClick={() => setIsEditingConversationTranscript(!isEditingConversationTranscript)}
                  className="text-sm text-REFERENCE-navy hover:underline flex items-center gap-1"
                >
                  {isEditingConversationTranscript ? <Save className="w-4 h-4" /> : <Edit2 className="w-4 h-4" />}
                  {isEditingConversationTranscript ? 'Done Editing' : (conversationTranscript ? 'Edit Conversation' : 'Add Conversation Transcript')}
                </button>
              </div>

              {isEditingConversationTranscript ? (
                <textarea
                  value={conversationTranscript}
                  onChange={(e) => setConversationTranscript(e.target.value)}
                  rows="6"
                  className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-REFERENCE-navy focus:border-transparent font-mono text-sm"
                  placeholder="Paste or type the review conversation here (this will be included in the final report)."
                />
              ) : (
                <div className="w-full px-4 py-3 border border-gray-300 rounded-lg bg-gray-50 whitespace-pre-wrap font-mono text-sm max-h-48 overflow-y-auto">
                  {conversationTranscript || <span className="text-gray-400">No conversation transcript provided.</span>}
                </div>
              )}
            </div>
          </div>
          
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <p className="text-sm text-green-800 font-medium mb-2">Detected {defects.length} defect{defects.length !== 1 ? 's' : ''}</p>
            <p className="text-sm text-green-700">Continue to the next section to attach photos to each defect.</p>
          </div>
          
          <div className="flex justify-between mt-8">
            <button
              onClick={() => setCurrentSection('basic')}
              className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Back to Basic Info
            </button>
            
            <button
              onClick={handleConfirmTranscript}
              className="px-8 py-3 bg-REFERENCE-navy text-white rounded-lg hover:bg-REFERENCE-navy-dark flex items-center gap-2 transition-colors"
            >
              Confirm & Continue to Defects
              <CheckCircle className="w-5 h-5" />
            </button>
          </div>
        </div>
      )}
      
      {/* Section 3: Defect Items */}
      {currentSection === 'defects' && (
        <div className="space-y-6">
          <h2 className="text-2xl font-bold text-REFERENCE-navy border-l-4 border-REFERENCE-navy pl-4 mb-6">
            Defect Items ({defects.length})
          </h2>
          
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
            <p className="text-sm text-blue-800">Review each defect below. You can edit details and attach one or more photos per defect. Photos will use the defect description as the caption in the report.</p>
          </div>
          
          {defects.length === 0 ? (
            <div className="text-center py-12 border-2 border-dashed border-gray-300 rounded-lg">
              <AlertCircle className="w-12 h-12 mx-auto text-gray-400 mb-3" />
              <p className="text-gray-600">No defects detected. Go back to edit the transcript or start a new report.</p>
            </div>
          ) : (
            <div className="space-y-6">
              {defects.map((defect, index) => (
                <div key={defect.id} className="border border-gray-300 rounded-lg p-6 bg-white shadow-sm">
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl font-bold text-REFERENCE-navy">#{index + 1}</span>
                      <div>
                        <span className="inline-block px-3 py-1 bg-REFERENCE-navy text-white text-sm rounded-full">
                          {defect.defect_code || defect.code}
                        </span>
                        <p className="text-sm text-gray-600 mt-1">{defect.category} â€º {defect.subcategory}</p>
                      </div>
                    </div>
                    
                    <button
                      onClick={() => handleDefectRemove(defect.id)}
                      className="text-red-600 hover:text-red-800 flex items-center gap-1 text-sm"
                    >
                      <Trash2 className="w-4 h-4" />
                      Remove
                    </button>
                  </div>
                  
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Defect Found</label>
                      <input
                        type="text"
                        value={defect.defect_found}
                        onChange={(e) => handleDefectUpdate(defect.id, 'defect_found', e.target.value)}
                        className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-REFERENCE-navy focus:border-transparent"
                      />
                    </div>
                    
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Standard</label>
                      <input
                        type="text"
                        value={defect.standard}
                        onChange={(e) => handleDefectUpdate(defect.id, 'standard', e.target.value)}
                        className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-REFERENCE-navy focus:border-transparent"
                      />
                    </div>
                  </div>
                  
                  <div className="mb-4">
                    <label className="block text-xs font-medium text-gray-600 mb-1">Non-Compliance Details</label>
                    <textarea
                      value={defect.non_compliance}
                      onChange={(e) => handleDefectUpdate(defect.id, 'non_compliance', e.target.value)}
                      rows="2"
                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded focus:ring-2 focus:ring-REFERENCE-navy focus:border-transparent"
                    />
                  </div>
                  
                  {/* Photos Section */}
                  <div className="border-t border-gray-200 pt-4">
                    <label className="block text-sm font-medium text-gray-700 mb-3">
                      Photos ({defect.photos?.length || 0})
                      <span className="text-xs text-gray-500 ml-2">Add 1 or more photos for this defect</span>
                    </label>
                    
                    <div className="mb-3">
                      {/* Mobile-first horizontal scroller for defect photos */}
                      <div className="flex gap-3 overflow-x-auto photo-scroller hide-scrollbar py-1 md:hidden">
                        {(defect.photos || []).map((photo, photoIdx) => (
                          <div key={photoIdx} className="flex-none w-36 sm:w-44 relative group">
                            <button
                              onClick={() => toggleDefectPreview(defect.id, photoIdx)}
                              className="w-full h-28 rounded-lg overflow-hidden focus:outline-none thumbnail-preview"
                              aria-label={`Preview defect ${index + 1} photo ${photoIdx + 1}`}
                            >
                              <img
                                src={URL.createObjectURL(photo)}
                                alt={`Defect ${index + 1} Photo ${photoIdx + 1}`}
                                className="w-full h-full object-cover rounded border border-gray-300"
                              />
                            </button>

                            <button
                              onClick={() => handleDefectPhotoRemove(defect.id, photoIdx)}
                              className="absolute top-1 right-1 bg-red-600 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
                            >
                              <X className="w-4 h-4" />
                            </button>
                            <p className="text-xs text-gray-600 mt-1 truncate text-center">{photo.name}</p>
                          </div>
                        ))}
                      </div>

                      {/* Desktop / larger screens: denser grid */}
                      <div className="hidden md:grid md:grid-cols-4 md:gap-3">
                        {(defect.photos || []).map((photo, photoIdx) => (
                          <div key={photoIdx} className="relative group">
                            <button
                              onClick={() => toggleDefectPreview(defect.id, photoIdx)}
                              className="w-full h-32 rounded overflow-hidden focus:outline-none thumbnail-preview"
                              aria-label={`Preview defect ${index + 1} photo ${photoIdx + 1}`}
                            >
                              <img
                                src={URL.createObjectURL(photo)}
                                alt={`Defect ${index + 1} Photo ${photoIdx + 1}`}
                                className="w-full h-full object-cover rounded border border-gray-300"
                              />
                            </button>
                            <button
                              onClick={() => handleDefectPhotoRemove(defect.id, photoIdx)}
                              className="absolute top-1 right-1 bg-red-600 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
                            >
                              <X className="w-4 h-4" />
                            </button>
                            <p className="text-xs text-gray-600 mt-1 truncate">{photo.name}</p>
                          </div>
                        ))}
                      </div>

                      {/* Inline preview for defect photos (kept inline under the scroller/grid) */}
                      {selectedDefectPreview[defect.id] !== undefined && (defect.photos || [])[selectedDefectPreview[defect.id]] && (
                        <div className="mt-3 rounded-lg border border-gray-200 p-3 bg-gray-50">
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex-1">
                              <img src={URL.createObjectURL((defect.photos || [])[selectedDefectPreview[defect.id]])} alt={(defect.photos || [])[selectedDefectPreview[defect.id]].name} className="w-full h-56 object-contain rounded-lg bg-white" />
                              <p className="text-xs text-gray-600 mt-2 truncate">{(defect.photos || [])[selectedDefectPreview[defect.id]].name}</p>
                            </div>
                            <div className="ml-3 flex-shrink-0">
                              <button onClick={() => toggleDefectPreview(defect.id, selectedDefectPreview[defect.id])} className="px-3 py-1 border border-gray-300 rounded-lg text-xs text-gray-700 hover:bg-gray-100">Close</button>
                            </div>
                          </div>
                        </div>
                      )}
                      
                      {/* Add Photo Button */}
                      <div className="border-2 border-dashed border-gray-300 rounded hover:border-REFERENCE-navy transition-colors">
                        <input
                          type="file"
                          accept="image/*"
                          multiple
                          onChange={(e) => handleDefectPhotoAdd(defect.id, e)}
                          className="hidden"
                          id={`defect-photo-${defect.id}`}
                        />
                        <label
                          htmlFor={`defect-photo-${defect.id}`}
                          className="cursor-pointer flex flex-col items-center justify-center h-32 text-gray-400 hover:text-REFERENCE-navy"
                        >
                          <Plus className="w-8 h-8" />
                          <span className="text-xs mt-1">Add Photos</span>
                        </label>
                        <div className="mt-2 md:hidden text-center">
                          <button type="button" onClick={(e) => { e.preventDefault(); const el = document.getElementById(`defect-photo-${defect.id}`); if (el) el.click(); }} className="px-3 py-1 bg-REFERENCE-navy text-white rounded text-xs">Choose</button>
                          {fileSelectFailed && <p className="text-xs text-yellow-700 mt-2">No files selected — try a different browser or open the page outside an embedded app if you're on iOS.</p>}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          
          <div className="flex justify-between mt-8">
            <button
              onClick={() => setCurrentSection('transcript')}
              className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Back to Transcript
            </button>
            
            <button
              onClick={handleGenerateReport}
              disabled={isProcessing || defects.length === 0}
              className="px-8 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center gap-2 transition-colors"
            >
              {isProcessing ? (
                <>
                  <Loader className="w-5 h-5 animate-spin" />
                  Generating Report...
                </>
              ) : (
                <>
                  Generate Report
                  <Download className="w-5 h-5" />
                </>
              )}
            </button>
          </div>
        </div>
      )}
      
      {/* Section 4: Report Ready */}
      {currentSection === 'generate' && reportReady && (
        <div className="text-center py-12">
          <CheckCircle className="w-20 h-20 mx-auto text-green-600 mb-6" />
          <h2 className="text-3xl font-bold text-REFERENCE-navy mb-4">Report Generated Successfully!</h2>
          <p className="text-gray-600 mb-8">Your report is ready to download.</p>
          
          <div className="flex justify-center gap-4">
            <button
              onClick={handleDownloadReport}
              className="px-8 py-3 bg-REFERENCE-navy text-white rounded-lg hover:bg-REFERENCE-navy-dark flex items-center gap-2 transition-colors"
            >
              <Download className="w-5 h-5" />
              Download Report
            </button>
            
            <button
              onClick={handleStartNewInspection}
              className="px-8 py-3 border border-REFERENCE-navy text-REFERENCE-navy rounded-lg hover:bg-gray-50 transition-colors"
            >
              Start New Report
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default InspectionForm;