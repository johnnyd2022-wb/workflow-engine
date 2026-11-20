(function() {
  'use strict';

  function createPromptRestorer(helpers) {
    function restorePromptList(prompts) {
      const promptsList = document.getElementById('guided-prompts-list');
      if (!promptsList) return;
      promptsList.innerHTML = '';
      for (const p of prompts || []) {
        window.addGuidedPrompt();
        const promptEls = document.querySelectorAll('#guided-prompts-list > div');
        const lastP = promptEls[promptEls.length - 1];
        if (lastP) {
          const labelIn = lastP.querySelector('.guided-prompt-label');
          const typeSel = lastP.querySelector('.guided-prompt-type');
          const unitSel = lastP.querySelector('.guided-prompt-unit');
          const reqSel = lastP.querySelector('.guided-prompt-required');
          if (labelIn) labelIn.value = p.label || '';
          if (typeSel) {
            typeSel.value = p.type || 'text';
            typeSel.dispatchEvent(new Event('change'));
          }
          if (unitSel) unitSel.value = p.unit || '';
          if (reqSel) reqSel.value = p.required ? 'true' : 'false';
          const optionsIn = lastP.querySelector('.guided-prompt-options');
          if (optionsIn) optionsIn.value = helpers.normalisePromptOptions(p.options).join('\n');
        }
      }
    }

    return restorePromptList;
  }

  window.ProcessModalPromptRestore = Object.freeze({ create: createPromptRestorer });
})();
