/**
 * Inventory add-by-barcode SPA page: camera scan + manual entry, then inline form (same fields as add manual) with API lookup.
 * Logic mirrored from core2.html barcode scan modal (BarcodeDetector + ZXing fallback).
 */
(function () {
  'use strict';

  var barcodeStream = null;
  var lastBarcodeValue = null;
  var barcodeScanLoopId = null;
  var barcodeConfidenceCounter = 0;
  var decodeInProgress = false;
  var barcodeConsecutiveFailures = 0;
  var lastBarcodeDecodeTime = 0;
  var barcodeCandidateHistory = [];
  var lastFrameQualityScore = null;
  var lastFrameStabilityScore = null;
  var BARCODE_SCAN_INTERVAL_MS = 250;
  var DECODE_TIMEOUT_MS = 800;
  var BARCODE_QUALITY_MIN_VARIANCE = 30;
  var BARCODE_STABILITY_DIFF_THRESHOLD = 40;
  var BARCODE_EXPOSURE_STABILITY_MAX = 60;
  var BARCODE_HISTORY_LENGTH = 10;
  var BARCODE_VOTE_QUORUM = 5;
  var BARCODE_EDGE_VOLATILITY_MAX = 0.45;
  var BARCODE_CENTER_BORDER_MAX = 90;
  var lastFrameEdgeScore = null;
  var lowLightViolationCounter = 0;
  var motionViolationCounter = 0;
  var HYSTERESIS_LIMIT = 5;
  var lastBarcodeStatusMessage = '';
  var scannerStateEnterTime = Date.now();
  var STATE_MIN_DWELL_MS = 900;

  var SCANNER_STATE = { SCANNING: 0, VERIFYING: 1, LOW_LIGHT_WARNING: 2, HOLD_STEADY: 3, CONFIRMED: 4 };
  var scannerState = SCANNER_STATE.SCANNING;

  function transitionScannerState(newState, message) {
    if (scannerState === newState) return;
    var now = Date.now();
    if (now - scannerStateEnterTime < STATE_MIN_DWELL_MS) {
      return;
    }
    scannerState = newState;
    scannerStateEnterTime = now;
    setBarcodeStatusDebounced(message);
  }

  function clampConfidence(score) {
    return Math.max(0.15, Math.min(1, score));
  }

  function getFrameQualityScore(canvas) {
    var ctx = canvas.getContext('2d');
    var w = Math.min(canvas.width, 160);
    var h = Math.min(canvas.height, 120);
    var data = ctx.getImageData(0, 0, w, h).data;
    var sum = 0, sumSq = 0, n = 0;
    for (var i = 0; i < data.length; i += 4) {
      var g = (data[i] + data[i + 1] + data[i + 2]) / 3;
      sum += g;
      sumSq += g * g;
      n++;
    }
    if (n === 0) return 0;
    var mean = sum / n;
    return (sumSq / n) - (mean * mean);
  }

  function frameStabilityScore(canvas) {
    var ctx = canvas.getContext('2d');
    var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
    var d = img.data;
    var cx = 0, cy = 0, total = 0;
    for (var y = 0; y < canvas.height; y++) {
      for (var x = 0; x < canvas.width; x++) {
        var idx = (y * canvas.width + x) * 4;
        var g = (d[idx] + d[idx + 1] + d[idx + 2]) / 3;
        cx += x * g;
        cy += y * g;
        total += g;
      }
    }
    if (!total) return 0;
    cx /= total;
    cy /= total;
    return Math.sqrt(cx * cx + cy * cy);
  }

  function exposureStabilityScore(canvas) {
    var ctx = canvas.getContext('2d');
    var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
    var d = img.data;
    var brightnessSamples = [];
    for (var i = 0; i < d.length; i += 4) {
      brightnessSamples.push((d[i] + d[i + 1] + d[i + 2]) / 3);
    }
    if (!brightnessSamples.length) return 0;
    var mean = brightnessSamples.reduce(function (a, b) { return a + b; }, 0) / brightnessSamples.length;
    var variance = brightnessSamples.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / brightnessSamples.length;
    return Math.sqrt(variance);
  }

  function centerBorderLuminanceDiff(canvas) {
    var ctx = canvas.getContext('2d');
    var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
    var d = img.data;
    var w = canvas.width;
    var h = canvas.height;
    var margin = Math.floor(Math.min(w, h) * 0.15);
    var cx1 = margin;
    var cx2 = w - margin;
    var cy1 = margin;
    var cy2 = h - margin;
    var centerSum = 0, centerN = 0;
    var borderSum = 0, borderN = 0;
    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        var idx = (y * w + x) * 4;
        var g = (d[idx] + d[idx + 1] + d[idx + 2]) / 3;
        if (x >= cx1 && x < cx2 && y >= cy1 && y < cy2) {
          centerSum += g;
          centerN++;
        } else {
          borderSum += g;
          borderN++;
        }
      }
    }
    var centerMean = centerN ? centerSum / centerN : 128;
    var borderMean = borderN ? borderSum / borderN : 128;
    return Math.abs(centerMean - borderMean);
  }

  function sobelEdgeDensity(canvas) {
    var ctx = canvas.getContext('2d');
    var w = canvas.width;
    var h = canvas.height;
    var img = ctx.getImageData(0, 0, w, h);
    var d = img.data;
    var step = 4;
    var sum = 0, n = 0;
    for (var y = 1; y < h - 1; y += step) {
      for (var x = 1; x < w - 1; x += step) {
        var idx = (y * w + x) * 4;
        var g = function (xx, yy) {
          var i = (yy * w + xx) * 4;
          return (d[i] + d[i + 1] + d[i + 2]) / 3;
        };
        var gx = g(x + 1, y) - g(x - 1, y);
        var gy = g(x, y + 1) - g(x, y - 1);
        sum += Math.sqrt(gx * gx + gy * gy);
        n++;
      }
    }
    return n ? sum / n : 0;
  }

  function stopBarcodeScanLoop() {
    if (barcodeScanLoopId != null) {
      cancelAnimationFrame(barcodeScanLoopId);
      barcodeScanLoopId = null;
    }
  }

  function safeSet(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function getCodeForContinue() {
    var manual = document.getElementById('barcode-manual-input');
    var typed = manual && (manual.value || '').trim();
    if (typed) return typed;
    if (lastBarcodeValue) return String(lastBarcodeValue).trim();
    var rv = document.getElementById('barcode-result-value');
    return rv ? (rv.textContent || '').trim() : '';
  }

  function syncContinueButtonState() {
    var btn = document.getElementById('barcode-continue-btn');
    if (!btn) return;
    btn.disabled = !getCodeForContinue();
  }

  function applyLookupToForm(code, res) {
    var bi = document.getElementById('barcode-inv-barcode-input');
    var bdw = document.getElementById('barcode-inv-barcode-display-wrap');
    var bd = document.getElementById('barcode-inv-barcode-display');
    var nameEl = document.getElementById('barcode-inv-name');
    var unitEl = document.getElementById('barcode-inv-unit');
    var supplierEl = document.getElementById('barcode-inv-supplier');
    var qtyEl = document.getElementById('barcode-inv-quantity');
    if (bi) bi.value = code;
    if (bdw) bdw.style.display = 'block';
    if (bd) bd.textContent = code;
    if (res && res.exists && res.product) {
      var p = res.product;
      if (nameEl) nameEl.value = p.name || '';
      if (unitEl) unitEl.value = p.unit || 'kg';
      if (supplierEl) supplierEl.value = (p.supplier || '').trim();
      if (qtyEl && p.quantity != null && String(p.quantity).trim() !== '') {
        var qn = parseFloat(String(p.quantity).replace(',', '.'));
        qtyEl.value = !isNaN(qn) ? String(qn) : '';
      } else if (qtyEl) {
        qtyEl.value = '';
      }
    } else {
      if (nameEl) nameEl.value = '';
      if (unitEl) unitEl.value = 'kg';
      if (supplierEl) supplierEl.value = '';
      if (qtyEl) qtyEl.value = '';
    }
    var pd = document.getElementById('barcode-inv-purchase');
    var bn = document.getElementById('barcode-inv-batch');
    var ed = document.getElementById('barcode-inv-expiry');
    if (pd) pd.value = '';
    if (bn) bn.value = '';
    if (ed) ed.value = '';
  }

  function showFormAfterLookup(code, res) {
    var scan = document.getElementById('barcode-step-scan');
    var formWrap = document.getElementById('barcode-step-form');
    if (scan) scan.style.display = 'none';
    if (formWrap) formWrap.style.display = 'block';
    applyLookupToForm(code, res);
    var q = document.getElementById('barcode-inv-quantity');
    if (q) q.focus();
  }

  function proceedToItemForm() {
    var code = getCodeForContinue();
    if (!code) {
      if (typeof window.showNotification === 'function') {
        window.showNotification('error', 'Barcode required', 'Enter or scan a barcode first.');
      }
      return;
    }
    closeBarcodeCamera();
    var btn = document.getElementById('barcode-continue-btn');
    if (!window.CoreAPI || !window.CoreAPI.lookupBarcode) {
      showFormAfterLookup(code, { exists: false });
      return;
    }
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Looking up…';
    }
    window.CoreAPI.lookupBarcode(code).then(function (res) {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Continue';
      }
      showFormAfterLookup(code, res || { exists: false });
    }).catch(function () {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Continue';
      }
      showFormAfterLookup(code, { exists: false });
    });
  }

  function backToScanStep() {
    var scan = document.getElementById('barcode-step-scan');
    var formWrap = document.getElementById('barcode-step-form');
    var form = document.getElementById('barcode-add-inventory-form');
    if (formWrap) formWrap.style.display = 'none';
    if (scan) scan.style.display = 'block';
    if (form) form.reset();
    var bdw = document.getElementById('barcode-inv-barcode-display-wrap');
    if (bdw) bdw.style.display = 'none';
    lastBarcodeValue = null;
    var manual = document.getElementById('barcode-manual-input');
    if (manual) manual.value = '';
    var prev = document.getElementById('barcode-result-preview');
    if (prev) prev.style.display = 'none';
    safeSet('barcode-result-value', '');
    syncContinueButtonState();
    var cameraPanel = document.getElementById('barcode-camera-panel');
    if (cameraPanel && cameraPanel.style.display !== 'none') {
      startBarcodeCamera();
    }
  }

  function bindInventoryFormSubmit() {
    var form = document.getElementById('barcode-add-inventory-form');
    if (!form || form.getAttribute('data-barcode-inv-bound') === '1') return;
    form.setAttribute('data-barcode-inv-bound', '1');
    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      e.stopPropagation();
      var formData = new FormData(this);
      var name = (formData.get('name') || '').trim();
      var quantity = parseFloat(formData.get('quantity'));
      var unit = (formData.get('unit') || '').trim();
      if (!name) {
        if (window.showNotification) window.showNotification('error', 'Validation Error', 'Please enter an item name');
        return false;
      }
      if (!quantity || isNaN(quantity) || quantity <= 0) {
        if (window.showNotification) window.showNotification('error', 'Validation Error', 'Please enter a quantity greater than 0');
        return false;
      }
      if (!unit) {
        if (window.showNotification) window.showNotification('error', 'Validation Error', 'Please select a unit');
        return false;
      }
      var payload = {
        name: name,
        quantity: quantity,
        unit: unit,
        inventory_type: 'raw_material',
        supplier: (formData.get('supplier') || '').trim() || null,
        purchase_date: formData.get('purchaseDate') || null,
        supplier_batch_number: (formData.get('batchNumber') || '').trim() || null,
        expiry_date: formData.get('expiryDate') || null,
        barcode: (formData.get('barcode') || '').trim() || null,
        source_method: 'barcode_scan',
      };
      try {
        if (!window.CoreAPI || !window.CoreAPI.createInventoryItem) {
          console.error('CoreAPI.createInventoryItem is not available.', payload);
          return false;
        }
        await window.CoreAPI.createInventoryItem(payload);
        if (window.showNotification) {
          window.showNotification('success', 'Inventory Item Added', 'The item has been added to inventory.');
        }
        this.reset();
        window.location.href = '/core';
      } catch (err) {
        console.error('Failed to create inventory item', err);
        if (window.showNotification) {
          window.showNotification('error', 'Failed to Add Item', 'There was a problem saving this inventory item.');
        }
      }
      return false;
    });
  }

  function setBarcodeStatus(msg) {
    safeSet('barcode-capture-status', msg);
  }

  function setBarcodeStatusDebounced(msg) {
    if (msg === lastBarcodeStatusMessage) return;
    lastBarcodeStatusMessage = msg;
    setBarcodeStatus(msg);
  }

  function isBarcodeScanMobile() {
    return /Mobile|Android|iPhone|iPad|iPod|webOS|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent || '');
  }

  function startBarcodeScanLoop() {
    stopBarcodeScanLoop();
    var video = document.getElementById('barcode-video');
    var statusEl = document.getElementById('barcode-capture-status');
    if (!video || !statusEl) return;
    setBarcodeStatus('Scanning…');
    function scheduleNext() {
      if (barcodeScanLoopId != null) cancelAnimationFrame(barcodeScanLoopId);
      barcodeScanLoopId = requestAnimationFrame(tick);
    }
    function tick() {
      if (barcodeScanLoopId != null) {
        cancelAnimationFrame(barcodeScanLoopId);
        barcodeScanLoopId = null;
      }
      if (lastBarcodeValue) return;
      if (!video.videoWidth || !video.readyState || video.readyState < 2) {
        scheduleNext();
        return;
      }
      if (decodeInProgress) {
        scheduleNext();
        return;
      }
      var now = Date.now();
      var intervalMs = barcodeConsecutiveFailures >= 5 ? 600 : (barcodeConfidenceCounter >= 1 ? 300 : BARCODE_SCAN_INTERVAL_MS);
      if (now - lastBarcodeDecodeTime < intervalMs) {
        scheduleNext();
        return;
      }
      lastBarcodeDecodeTime = now;

      var canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext('2d').drawImage(video, 0, 0);

      var qualityThreshold = Math.max(15, BARCODE_QUALITY_MIN_VARIANCE - Math.min(barcodeConsecutiveFailures, 10) * 2);
      var currentQuality = getFrameQualityScore(canvas);
      if (currentQuality <= qualityThreshold) {
        scheduleNext();
        return;
      }
      lastFrameQualityScore = currentQuality;

      var currentStability = frameStabilityScore(canvas);
      if (lastFrameStabilityScore != null && Math.abs(currentStability - lastFrameStabilityScore) > BARCODE_STABILITY_DIFF_THRESHOLD) {
        motionViolationCounter += 0.2;
        if (motionViolationCounter >= HYSTERESIS_LIMIT) transitionScannerState(SCANNER_STATE.HOLD_STEADY, 'Hold camera steady');
      } else {
        motionViolationCounter = Math.max(0, motionViolationCounter - 0.3);
      }
      lastFrameStabilityScore = currentStability;

      var exposureScore = exposureStabilityScore(canvas);
      var exposureUpper = BARCODE_EXPOSURE_STABILITY_MAX * 1.5;
      var exposureLower = BARCODE_EXPOSURE_STABILITY_MAX * 0.8;

      if (exposureScore > exposureUpper) {
        lowLightViolationCounter++;
      } else if (exposureScore < exposureLower) {
        lowLightViolationCounter = Math.max(0, lowLightViolationCounter - 1);
      }

      if (lowLightViolationCounter >= HYSTERESIS_LIMIT && scannerState !== SCANNER_STATE.LOW_LIGHT_WARNING) {
        transitionScannerState(SCANNER_STATE.LOW_LIGHT_WARNING, 'Move to brighter area');
        var hintEl = document.getElementById('barcode-low-light-hint');
        if (hintEl) hintEl.style.display = 'block';
      }
      if (centerBorderLuminanceDiff(canvas) > BARCODE_CENTER_BORDER_MAX) {
        lowLightViolationCounter++;
        if (lowLightViolationCounter >= HYSTERESIS_LIMIT && scannerState !== SCANNER_STATE.LOW_LIGHT_WARNING) {
          transitionScannerState(SCANNER_STATE.LOW_LIGHT_WARNING, 'Move to brighter area');
          var hintEl2 = document.getElementById('barcode-low-light-hint');
          if (hintEl2) hintEl2.style.display = 'block';
        }
      } else {
        lowLightViolationCounter = Math.max(0, lowLightViolationCounter - 0.5);
      }
      var currentEdge = sobelEdgeDensity(canvas);
      var edgeVolatility = lastFrameEdgeScore != null
        ? Math.abs(currentEdge - lastFrameEdgeScore) / (lastFrameEdgeScore + 1)
        : 0;
      if (edgeVolatility > BARCODE_EDGE_VOLATILITY_MAX) {
        motionViolationCounter += 0.2;
        if (motionViolationCounter >= HYSTERESIS_LIMIT) transitionScannerState(SCANNER_STATE.HOLD_STEADY, 'Hold camera steady');
      } else {
        motionViolationCounter = Math.max(0, motionViolationCounter - 0.3);
      }
      lastFrameEdgeScore = currentEdge;

      decodeInProgress = true;
      var frameQualityForConfidence = currentQuality;
      decodeBarcodeFromCanvas(canvas).then(function (value) {
        decodeInProgress = false;
        if (value && !lastBarcodeValue) {
          barcodeCandidateHistory.push(value);
          if (barcodeCandidateHistory.length > BARCODE_HISTORY_LENGTH) barcodeCandidateHistory.shift();
          var counts = {};
          for (var i = 0; i < barcodeCandidateHistory.length; i++) {
            var v = barcodeCandidateHistory[i];
            counts[v] = (counts[v] || 0) + 1;
          }
          var accepted = null;
          for (var k in counts) { if (counts[k] >= BARCODE_VOTE_QUORUM) { accepted = k; break; } }
          if (accepted) {
            var voteRatio = counts[accepted] / barcodeCandidateHistory.length;
            var qualityComponent = Math.max(0, Math.min(1, frameQualityForConfidence / 100));
            var confidenceScore = clampConfidence(voteRatio * qualityComponent);
            var confidenceThreshold = isBarcodeScanMobile() ? 0.35 : 0.5;
            if (confidenceScore >= confidenceThreshold) {
              lastBarcodeValue = accepted;
              barcodeCandidateHistory = [];
              barcodeConsecutiveFailures = 0;
              safeSet('barcode-result-value', accepted);
              var preview = document.getElementById('barcode-result-preview');
              if (preview) preview.style.display = 'block';
              syncContinueButtonState();
              transitionScannerState(SCANNER_STATE.CONFIRMED, 'Barcode confirmed.');
              stopBarcodeScanLoop();
            } else {
              transitionScannerState(SCANNER_STATE.VERIFYING, 'Verifying barcode');
            }
          } else {
            transitionScannerState(SCANNER_STATE.VERIFYING, 'Verifying barcode');
          }
        } else {
          barcodeCandidateHistory = [];
          if (value) { barcodeConsecutiveFailures = 0; }
          else {
            barcodeConsecutiveFailures++;
            if (barcodeConsecutiveFailures >= 8) {
              transitionScannerState(SCANNER_STATE.LOW_LIGHT_WARNING, 'Move to brighter area');
              var hintEl3 = document.getElementById('barcode-low-light-hint');
              if (hintEl3) hintEl3.style.display = 'block';
            } else {
              transitionScannerState(SCANNER_STATE.SCANNING, 'Scanning…');
            }
          }
        }
      }).catch(function () {
        decodeInProgress = false;
        barcodeConsecutiveFailures++;
      });
      scheduleNext();
    }
    scheduleNext();
  }

  function closeBarcodeCamera() {
    stopBarcodeScanLoop();
    if (barcodeStream) {
      barcodeStream.getTracks().forEach(function (t) { t.stop(); });
      barcodeStream = null;
    }
    var vid = document.getElementById('barcode-video');
    if (vid) vid.srcObject = null;
  }

  function resetScannerUi() {
    lastBarcodeValue = null;
    barcodeConfidenceCounter = 0;
    barcodeConsecutiveFailures = 0;
    barcodeCandidateHistory = [];
    lastFrameQualityScore = null;
    lastFrameStabilityScore = null;
    lastFrameEdgeScore = null;
    lowLightViolationCounter = 0;
    motionViolationCounter = 0;
    lastBarcodeStatusMessage = '';
    scannerState = SCANNER_STATE.SCANNING;
    stopBarcodeScanLoop();
    var resultPreview = document.getElementById('barcode-result-preview');
    if (resultPreview) resultPreview.style.display = 'none';
    syncContinueButtonState();
    var manualInput = document.getElementById('barcode-manual-input');
    if (manualInput) manualInput.value = '';
    var lowLightHint = document.getElementById('barcode-low-light-hint');
    if (lowLightHint) lowLightHint.style.display = 'none';
    transitionScannerState(SCANNER_STATE.SCANNING, 'Point camera at barcode');
  }

  function startBarcodeCamera() {
    resetScannerUi();
    var cam = document.getElementById('barcode-camera-viewport');
    var video = document.getElementById('barcode-video');
    if (!video) return;
    if (cam) cam.style.display = 'block';
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      var constraints = { video: { facingMode: 'environment', width: { ideal: 1280, min: 640 }, height: { ideal: 720, min: 480 } }, audio: false };
      navigator.mediaDevices.getUserMedia(constraints).then(function (stream) {
        barcodeStream = stream;
        video.srcObject = stream;
        video.onloadedmetadata = function () {
          video.play().then(function () { startBarcodeScanLoop(); }).catch(function () { startBarcodeScanLoop(); });
        };
      }).catch(function () {
        navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false }).then(function (stream) {
          barcodeStream = stream;
          video.srcObject = stream;
          video.onloadedmetadata = function () {
            video.play().then(function () { startBarcodeScanLoop(); }).catch(function () { startBarcodeScanLoop(); });
          };
        }).catch(function () {
          navigator.mediaDevices.getUserMedia({ video: true, audio: false }).then(function (stream) {
            barcodeStream = stream;
            video.srcObject = stream;
            video.onloadedmetadata = function () {
              video.play().then(function () { startBarcodeScanLoop(); }).catch(function () { startBarcodeScanLoop(); });
            };
          }).catch(function () {
            if (cam) cam.style.display = 'none';
          });
        });
      });
    } else {
      if (cam) cam.style.display = 'none';
    }
  }

  function resizeCanvas(canvas, scale) {
    var temp = document.createElement('canvas');
    temp.width = Math.max(1, Math.floor(canvas.width * scale));
    temp.height = Math.max(1, Math.floor(canvas.height * scale));
    temp.getContext('2d').drawImage(canvas, 0, 0, temp.width, temp.height);
    return temp;
  }

  function adaptiveContrastEnhance(canvas) {
    var ctx = canvas.getContext('2d');
    var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
    var d = img.data;
    var block = 32;
    var w = canvas.width;
    var h = canvas.height;

    function blockMean(x, y) {
      var sum = 0, n = 0;
      for (var yy = y; yy < Math.min(y + block, h); yy++) {
        for (var xx = x; xx < Math.min(x + block, w); xx++) {
          var idx = (yy * w + xx) * 4;
          sum += (d[idx] + d[idx + 1] + d[idx + 2]) / 3;
          n++;
        }
      }
      return n ? sum / n : 128;
    }

    for (var y = 0; y < h; y += block) {
      for (var x = 0; x < w; x += block) {
        var localMean = blockMean(x, y);
        var gain = 128 / (localMean + 1);
        for (var yy2 = y; yy2 < Math.min(y + block, h); yy2++) {
          for (var xx2 = x; xx2 < Math.min(x + block, w); xx2++) {
            var i = (yy2 * w + xx2) * 4;
            d[i] = Math.min(255, d[i] * gain);
            d[i + 1] = Math.min(255, d[i + 1] * gain);
            d[i + 2] = Math.min(255, d[i + 2] * gain);
          }
        }
      }
    }

    ctx.putImageData(img, 0, 0);
    return canvas;
  }

  function decodeBarcodeFromCanvas(canvas) {
    canvas = adaptiveContrastEnhance(canvas);
    var formats = ['qr_code', 'ean_13', 'ean_8', 'code_128', 'code_39', 'code_93', 'upc_a', 'upc_e', 'itf', 'codabar', 'pdf417', 'aztec', 'data_matrix'];
    function tryBarcodeDetector(targetCanvas) {
      if (typeof BarcodeDetector === 'undefined') return Promise.resolve(null);
      var detector;
      try {
        detector = new BarcodeDetector({ formats: formats });
      } catch (e) {
        try { detector = new BarcodeDetector(); } catch (e2) { return Promise.resolve(null); }
      }
      return detector.detect(targetCanvas).then(function (results) {
        return results.length ? results[0].rawValue : null;
      }).catch(function () { return null; });
    }
    function tryZxing(targetCanvas) {
      return new Promise(function (resolve) {
        targetCanvas.toBlob(function (blob) {
          if (!blob) { resolve(null); return; }
          var url = URL.createObjectURL(blob);
          var img = new Image();
          img.onload = function () {
            URL.revokeObjectURL(url);
            import('https://cdn.jsdelivr.net/npm/@zxing/library@0.19.1/+esm').then(function (zxing) {
              var reader = new zxing.BrowserMultiFormatReader();
              reader.decodeFromImageElement(img).then(function (result) {
                resolve(result ? result.getText() : null);
              }).catch(function () { resolve(null); });
            }).catch(function () { resolve(null); });
          };
          img.onerror = function () { URL.revokeObjectURL(url); resolve(null); };
          img.src = url;
        }, 'image/png');
      });
    }
    function decodeOne(c) {
      return tryBarcodeDetector(c).then(function (value) {
        if (value) return value;
        return tryZxing(c);
      });
    }
    function withTimeout(p) {
      return new Promise(function (resolve) {
        var done = false;
        var t = setTimeout(function () {
          if (done) return;
          done = true;
          resolve(null);
        }, DECODE_TIMEOUT_MS);
        p.then(function (v) {
          if (done) return;
          done = true;
          clearTimeout(t);
          resolve(v);
        }).catch(function () {
          if (done) return;
          done = true;
          clearTimeout(t);
          resolve(null);
        });
      });
    }
    return withTimeout(decodeOne(canvas)).then(function (value) {
      if (value) return value;
      return withTimeout(decodeOne(resizeCanvas(canvas, 0.75)));
    }).then(function (value) {
      if (value) return value;
      return withTimeout(decodeOne(resizeCanvas(canvas, 0.5)));
    });
  }

  function attachHandlers() {
    var captureBtn = document.getElementById('barcode-capture-btn');
    if (captureBtn) {
      captureBtn.addEventListener('click', function () {
        if (lastBarcodeValue) return;
        var video = document.getElementById('barcode-video');
        if (!video || !video.videoWidth) return;
        transitionScannerState(SCANNER_STATE.SCANNING, 'Scanning…');
        var canvas = document.createElement('canvas');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0);
        decodeBarcodeFromCanvas(canvas).then(function (value) {
          if (value) {
            lastBarcodeValue = value;
            safeSet('barcode-result-value', value);
            var prev = document.getElementById('barcode-result-preview');
            if (prev) prev.style.display = 'block';
            syncContinueButtonState();
            transitionScannerState(SCANNER_STATE.CONFIRMED, 'Barcode confirmed.');
            stopBarcodeScanLoop();
          } else {
            transitionScannerState(SCANNER_STATE.SCANNING, 'Point camera at barcode');
            if (typeof window.showNotification === 'function') {
              window.showNotification('info', 'No barcode in shot', 'Hold the barcode in view or tap Capture again.');
            }
          }
        }).catch(function (err) {
          transitionScannerState(SCANNER_STATE.SCANNING, 'Point camera at barcode');
          if (typeof window.showNotification === 'function') {
            window.showNotification('error', 'Decode failed', err && err.message ? err.message : 'Try manual entry.');
          }
        });
      });
    }

    var manualInput = document.getElementById('barcode-manual-input');
    if (manualInput) {
      manualInput.addEventListener('input', function () {
        syncContinueButtonState();
      });
      manualInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          var v = (this.value || '').trim();
          if (v) {
            lastBarcodeValue = v;
            safeSet('barcode-result-value', v);
            var resPrev = document.getElementById('barcode-result-preview');
            if (resPrev) resPrev.style.display = 'block';
            syncContinueButtonState();
          }
        }
      });
    }

    var continueBtn = document.getElementById('barcode-continue-btn');
    if (continueBtn) {
      continueBtn.addEventListener('click', function () {
        proceedToItemForm();
      });
    }

    var changeCodeBtn = document.getElementById('barcode-change-code-btn');
    if (changeCodeBtn) {
      changeCodeBtn.addEventListener('click', function () {
        backToScanStep();
      });
    }

    bindInventoryFormSubmit();

    window.addEventListener('pagehide', closeBarcodeCamera);

    if (!window.__barcodeSpaHtmxCleanupBound) {
      window.__barcodeSpaHtmxCleanupBound = true;
      document.body.addEventListener('htmx:afterSwap', function () {
        if (!document.getElementById('barcode-spa-root')) closeBarcodeCamera();
      });
    }
  }

  function isBarcodeCameraAvailable() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
      return Promise.resolve(false);
    }
    var CAMERA_CHECK_TIMEOUT_MS = 3000;
    return new Promise(function (resolve) {
      var settled = false;
      var timer = setTimeout(function () {
        if (settled) return;
        settled = true;
        resolve(false);
      }, CAMERA_CHECK_TIMEOUT_MS);
      try {
        navigator.mediaDevices.enumerateDevices()
          .then(function (devices) {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            resolve(devices.some(function (d) { return d && d.kind === 'videoinput'; }));
          })
          .catch(function () {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            resolve(false);
          });
      } catch (e) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(false);
      }
    });
  }

  function initPage() {
    var root = document.getElementById('barcode-spa-root');
    if (!root || root.getAttribute('data-barcode-spa-init') === '1') return;
    root.setAttribute('data-barcode-spa-init', '1');

    attachHandlers();
    syncContinueButtonState();

    var cameraPanel = document.getElementById('barcode-camera-panel');
    var noCamMsg = document.getElementById('barcode-no-camera-msg');

    isBarcodeCameraAvailable().then(function (hasCamera) {
      if (hasCamera && cameraPanel) {
        cameraPanel.style.display = 'block';
        startBarcodeCamera();
      } else {
        if (cameraPanel) cameraPanel.style.display = 'none';
        if (noCamMsg) noCamMsg.style.display = 'block';
      }
    }).catch(function () {
      if (cameraPanel) cameraPanel.style.display = 'none';
      if (noCamMsg) noCamMsg.style.display = 'block';
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPage);
  } else {
    initPage();
  }
})();
