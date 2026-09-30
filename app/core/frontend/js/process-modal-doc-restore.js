(function() {
  'use strict';

  function createDocRestorer(helpers) {
    return function restoreDocFields(data) {
      const docInlineTitleRestore = document.getElementById('guided-doc-inline-title');
      const docInlineContentRestore = document.getElementById('guided-doc-inline-content');
      if (docInlineTitleRestore) {
        docInlineTitleRestore.value = data.docInlineTitle != null ? data.docInlineTitle : '';
      }
      if (docInlineContentRestore) {
        docInlineContentRestore.value = data.docInlineContent != null ? data.docInlineContent : '';
      }
      if (typeof helpers.syncDocInlineDisabledState === 'function') {
        helpers.syncDocInlineDisabledState();
      }
      helpers.setPendingGuidedDocFileUpload(null);
      if (data.docFileUpload && data.docFileUpload.base64) {
        helpers.setPendingGuidedDocFileUpload({
          fileName: data.docFileUpload.fileName,
          mime: data.docFileUpload.mime,
          base64: data.docFileUpload.base64
        });
      }
    };
  }

  window.ProcessModalDocRestore = Object.freeze({ create: createDocRestorer });
})();
