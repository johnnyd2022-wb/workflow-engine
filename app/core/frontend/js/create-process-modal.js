(function() {
  'use strict';
  
  let currentStep = 1;
  const totalSteps = 4;
  let guidedInputs = [];
  let guidedOutputs = [];
  let guidedPrompts = [];
  let selectedInventoryItems = new Set(); // Track selected inventory items to prevent duplicates
  let createdSteps = []; // Track steps created in this session
  let editingStepId = null; // Track which step is being edited (if resuming draft)
  let isRestoringDraft = false; // Flag to prevent step reset during draft restoration
  
  // Get draft key for current process
  function getDraftKey() {
    const urlParams = new URLSearchParams(window.location.search);
    const processId = urlParams.get('id');
    return `process-draft-${processId || 'new'}`;
  }
  
  // Save draft to database
  window.saveDraft = async function() {
    const stepName = document.getElementById('guided-step-name')?.value.trim() || '';
    const stepDescription = document.getElementById('guided-step-description')?.value.trim() || '';
    
    // Get process ID from URL
    const urlParams = new URLSearchParams(window.location.search);
    let processId = urlParams.get('id');
    
    try {
      // If no process ID, create a new draft process
      if (!processId) {
        // Create a draft process with a temporary name
        const processName = stepName || 'Untitled Process';
        const newProcess = await CoreAPI.createProcess({
          name: processName,
          description: stepDescription || '',
          is_draft: true
        });
        processId = newProcess.id;
        
        // Update URL to include the new process ID
        const newUrl = new URL(window.location);
        newUrl.searchParams.set('id', processId);
        window.history.replaceState({}, '', newUrl);
      } else {
        // Mark existing process as draft
        await CoreAPI.updateProcess(processId, { is_draft: true });
      }
      
      // Collect current form data
      const inputs = collectCurrentInputs();
      const outputs = collectCurrentOutputs();
      const prompts = collectCurrentPrompts();
      
      // If we have a step name and form data, save the current step as a draft
      if (stepName && (inputs.length > 0 || outputs.length > 0 || prompts.length > 0)) {
        // Calculate step number
        let stepCount = createdSteps.length + 1;
        try {
          const processData = await CoreAPI.getProcess(processId);
          if (processData && processData.steps) {
            stepCount = processData.steps.length + 1;
          }
        } catch (err) {
          console.warn('Could not fetch process data to determine step count:', err);
        }
        
        const currentStepData = {
          step_number: stepCount,
          name: stepName,
          description: stepDescription,
          inputs: inputs || [],
          outputs: outputs || [],
          execution_prompts: prompts || []
        };
        
        // Create the step
        await CoreAPI.createStep(processId, currentStepData);
      }
      
      // Show success notification and close modal
      if (window.showNotification) {
        window.showNotification(
          'success',
          'Draft Saved',
          'Your progress has been saved as a draft. You can resume later from any device.'
        );
      }
      
      // Close modal
      closeModal();
      
      // Reload process data to show draft status
      if (window.loadProcessData) {
        await window.loadProcessData();
      }
    } catch (error) {
      console.error('Error saving draft:', error);
      const errorMessage = error.message || 'Unknown error';
      if (window.showNotification) {
        window.showNotification(
          'error',
          'Failed to Save Draft',
          `Failed to save draft: ${errorMessage}`
        );
      } else {
        alert('Failed to save draft: ' + errorMessage);
      }
    }
  };
  
  // Collect current inputs from form
  function collectCurrentInputs() {
    const inputs = [];
    const inputElements = document.querySelectorAll('#guided-inputs-list > div');
    inputElements.forEach(inputEl => {
      const nameInput = inputEl.querySelector('.guided-input-name');
      let name = '';
      if (nameInput) {
        if (nameInput.classList.contains('searchable-dropdown-input')) {
          name = nameInput.value.trim();
        } else {
          name = nameInput.value.trim();
        }
      }
      
      const quantityInput = inputEl.querySelector('.guided-input-quantity');
      const quantity = quantityInput ? (quantityInput.value || '').trim() : '';
      
      const unitSelect = inputEl.querySelector('.guided-input-unit');
      const unit = unitSelect ? unitSelect.value : '';
      
      const executionTypeSelect = inputEl.querySelector('.guided-input-execution-type');
      const executionType = executionTypeSelect ? executionTypeSelect.value : 'prompt';
      
      if (name && unit) {
        inputs.push({
          name: name,
          quantity: quantity ? parseFloat(quantity) : null,
          unit: unit,
          executionType: executionType
        });
      }
    });
    return inputs;
  }
  
  // Collect current outputs from form
  function collectCurrentOutputs() {
    const outputs = [];
    const outputElements = document.querySelectorAll('#guided-outputs-list > div');
    outputElements.forEach(outputEl => {
      const name = outputEl.querySelector('.guided-output-name')?.value.trim();
      const unitSelect = outputEl.querySelector('.guided-output-unit');
      const unit = unitSelect ? unitSelect.value : '';
      const quantityInput = outputEl.querySelector('.guided-output-quantity');
      const quantity = quantityInput ? (quantityInput.value || '').trim() : '';
      
      if (name && unit) {
        outputs.push({
          name: name,
          unit: unit,
          quantity: quantity ? parseFloat(quantity) : null
        });
      }
    });
    return outputs;
  }
  
  // Collect current prompts from form
  function collectCurrentPrompts() {
    const prompts = [];
    const promptElements = document.querySelectorAll('#guided-prompts-list > div');
    promptElements.forEach(promptEl => {
      const label = promptEl.querySelector('.guided-prompt-label')?.value.trim();
      const typeSelect = promptEl.querySelector('.guided-prompt-type');
      const type = typeSelect ? typeSelect.value : 'text';
      const unitSelect = promptEl.querySelector('.guided-prompt-unit');
      const unit = unitSelect ? (unitSelect.value || '').trim() : null;
      const requiredSelect = promptEl.querySelector('.guided-prompt-required');
      const required = requiredSelect ? requiredSelect.value === 'true' : true;
      
      if (label) {
        prompts.push({
          label: label,
          type: type,
          unit: unit || null,
          required: required
        });
      }
    });
    return prompts;
  }
  
  // Show resume draft confirmation modal (returns a promise)
  function showResumeDraftModal() {
    return new Promise((resolve) => {
      // Store the resolve function globally so buttons can call it
      window._resumeDraftResolve = resolve;
      
      // Show the modal
      const modal = document.getElementById('resume-draft-confirmation-modal');
      if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
      }
    });
  }
  
  // Confirm resume draft
  window.confirmResumeDraft = function() {
    // Hide the modal
    const modal = document.getElementById('resume-draft-confirmation-modal');
    if (modal) {
      modal.style.display = 'none';
    }
    document.body.style.overflow = 'auto';
    
    // Resolve the promise with true
    if (window._resumeDraftResolve) {
      window._resumeDraftResolve(true);
      window._resumeDraftResolve = null;
    }
  };
  
  // Cancel resume draft
  window.cancelResumeDraft = function() {
    // Hide the modal
    const modal = document.getElementById('resume-draft-confirmation-modal');
    if (modal) {
      modal.style.display = 'none';
    }
    document.body.style.overflow = 'auto';
    
    // Resolve the promise with false
    if (window._resumeDraftResolve) {
      window._resumeDraftResolve(false);
      window._resumeDraftResolve = null;
    }
  };
  
  // Check for and load draft from database
  async function loadDraft() {
    const urlParams = new URLSearchParams(window.location.search);
    const processId = urlParams.get('id');
    
    console.log('loadDraft called, processId:', processId);
    
    if (!processId) {
      console.log('No processId, returning false');
      return false;
    }
    
    try {
      // Get process data
      const processData = await CoreAPI.getProcess(processId);
      
      console.log('Process data loaded:', processData?.is_draft, 'steps:', processData?.steps?.length);
      
      if (!processData || !processData.is_draft) {
        console.log('Not a draft or no process data, returning false');
        return false;
      }
      
      // Show resume prompt using modal (returns a promise)
      const resume = await showResumeDraftModal();
      
      console.log('User chose to resume:', resume);
      
      if (!resume) {
        return false;
      }
      
      // Set flag IMMEDIATELY after user confirms
      isRestoringDraft = true;
      console.log('Set isRestoringDraft = true');
      
      // Update modal title if editing
      const modalTitle = document.getElementById('modal-title');
      const modalDescription = document.getElementById('modal-description');
      if (modalTitle) {
        modalTitle.textContent = 'Edit Process - Add Step';
      }
      if (modalDescription) {
        modalDescription.textContent = 'You can expand existing steps to edit them, or use this interactive editor to add additional steps.';
      }
      
      // Flag is already set above, but ensure it's still true
      console.log('About to restore steps, isRestoringDraft:', isRestoringDraft);
      
      // Load existing steps
      if (processData.steps && processData.steps.length > 0) {
        // Convert steps to createdSteps format
        const allSteps = processData.steps.map(step => ({
          id: step.id,
          step_number: step.step_number,
          name: step.name,
          description: step.description,
          inputs: step.inputs || [],
          outputs: step.outputs || [],
          execution_prompts: step.execution_prompts || []
        }));
        
        // Store all steps for summaries (excluding the one we'll restore for editing)
        // We'll restore the most recent step into the form, so don't include it in summaries yet
        const stepsForSummaries = allSteps.slice(0, -1); // All except the last one
        createdSteps = stepsForSummaries;
        
        // Show step summaries (for steps other than the one being edited)
        if (stepsForSummaries.length > 0) {
          updateStepSummaries();
        }
        
        // Restore the most recent step's data into the form for editing
        // This allows users to continue editing the step they were working on
        const mostRecentStep = allSteps[allSteps.length - 1];
        if (mostRecentStep) {
          // Track that we're editing this step
          editingStepId = mostRecentStep.id;
          
          // Restore step name and description
          const stepNameInput = document.getElementById('guided-step-name');
          const stepDescInput = document.getElementById('guided-step-description');
          if (stepNameInput) stepNameInput.value = mostRecentStep.name || '';
          if (stepDescInput) stepDescInput.value = mostRecentStep.description || '';
          
          // Restore inputs
          if (mostRecentStep.inputs && mostRecentStep.inputs.length > 0) {
            for (const input of mostRecentStep.inputs) {
              // Determine if it's inventory or new input based on requires_inventory_selection
              const inputType = input.requires_inventory_selection ? 'inventory' : 'new';
              await window.addGuidedInput(inputType);
              
              // Get the most recently added input container
              const inputContainers = document.querySelectorAll('#guided-inputs-list > div');
              const lastInputContainer = inputContainers[inputContainers.length - 1];
              
              if (lastInputContainer && input.name) {
                // Set name
                const nameInput = lastInputContainer.querySelector('.guided-input-name');
                if (nameInput) {
                  nameInput.value = input.name;
                  
                  // For inventory inputs, we need to mark the item as selected
                  if (nameInput.classList.contains('searchable-dropdown-input')) {
                    // Mark as selected so it doesn't appear in other dropdowns
                    selectedInventoryItems.add(input.name);
                    
                    // For inventory inputs, we need to find the item in the categorized items
                    // and trigger the onSelect callback to properly set up the dropdown
                    try {
                      const categorizedItems = await loadInventoryItems();
                      const allItems = [
                        ...(categorizedItems.raw_material || []),
                        ...(categorizedItems.work_in_progress || []),
                        ...(categorizedItems.final_product || [])
                      ];
                      const matchingItem = allItems.find(item => item.name === input.name);
                      
                      if (matchingItem) {
                        // Find the dropdown container and trigger selection
                        const dropdownContainer = nameInput.closest('.searchable-dropdown-container');
                        if (dropdownContainer) {
                          // The dropdown should have an onSelect callback - we need to call it
                          // But since it's created dynamically, we'll just set the value and unit
                          // The unit should be set from the matching item or from the input
                          const unitSelect = lastInputContainer.querySelector('.guided-input-unit');
                          if (unitSelect) {
                            // Use the input's unit if available, otherwise use the item's unit
                            unitSelect.value = input.unit || matchingItem.unit || '';
                          }
                        }
                      }
                    } catch (err) {
                      console.warn('Could not load inventory items for restoration:', err);
                    }
                    
                    // Trigger update events
                    nameInput.dispatchEvent(new Event('input'));
                    nameInput.dispatchEvent(new Event('blur'));
                  } else {
                    // For new inputs, just trigger the update events
                    nameInput.dispatchEvent(new Event('input'));
                    nameInput.dispatchEvent(new Event('blur'));
                  }
                }
                
                // Set quantity
                const quantityInput = lastInputContainer.querySelector('.guided-input-quantity');
                if (quantityInput && input.quantity !== null && input.quantity !== undefined) {
                  quantityInput.value = input.quantity;
                }
                
                // Set unit (if not already set for inventory inputs)
                const unitSelect = lastInputContainer.querySelector('.guided-input-unit');
                if (unitSelect && input.unit && !unitSelect.value) {
                  unitSelect.value = input.unit;
                }
                
                // Set execution type
                const executionTypeSelect = lastInputContainer.querySelector('.guided-input-execution-type');
                if (executionTypeSelect) {
                  if (input.requires_inventory_selection) {
                    executionTypeSelect.value = 'variable';
                  } else if (input.is_variable === false) {
                    executionTypeSelect.value = 'static';
                  } else {
                    executionTypeSelect.value = 'prompt';
                  }
                  // Trigger change event to update explanation
                  executionTypeSelect.dispatchEvent(new Event('change'));
                }
                
                // Update name display in header
                setTimeout(() => {
                  const nameDisplay = lastInputContainer.querySelector('.guided-input-name-display');
                  const titleSpan = lastInputContainer.querySelector('.guided-input-title');
                  if (nameDisplay && titleSpan && input.name) {
                    nameDisplay.textContent = input.name;
                    nameDisplay.style.display = 'inline';
                    titleSpan.style.display = 'none';
                  }
                }, 100);
              }
            }
          }
          
          // Restore outputs
          if (mostRecentStep.outputs && mostRecentStep.outputs.length > 0) {
            for (const output of mostRecentStep.outputs) {
              await window.addGuidedOutput();
              
              // Get the most recently added output container
              const outputContainers = document.querySelectorAll('#guided-outputs-list > div');
              const lastOutputContainer = outputContainers[outputContainers.length - 1];
              
              if (lastOutputContainer) {
                // Set name
                const nameInput = lastOutputContainer.querySelector('.guided-output-name');
                if (nameInput) {
                  nameInput.value = output.name || '';
                  nameInput.dispatchEvent(new Event('input'));
                  nameInput.dispatchEvent(new Event('blur'));
                }
                
                // Set quantity
                const quantityInput = lastOutputContainer.querySelector('.guided-output-quantity');
                if (quantityInput && output.quantity !== null && output.quantity !== undefined) {
                  quantityInput.value = output.quantity;
                }
                
                // Set unit
                const unitSelect = lastOutputContainer.querySelector('.guided-output-unit');
                if (unitSelect && output.unit) {
                  unitSelect.value = output.unit;
                }
                
                // Update name display in header
                const updateNameDisplay = () => {
                  const nameDisplay = lastOutputContainer.querySelector('.guided-output-name-display');
                  const titleSpan = lastOutputContainer.querySelector('.guided-output-title');
                  if (nameDisplay && titleSpan && output.name) {
                    nameDisplay.textContent = output.name;
                    nameDisplay.style.display = 'inline';
                    titleSpan.style.display = 'none';
                  }
                };
                updateNameDisplay();
              }
            }
          }
          
          // Restore execution prompts
          if (mostRecentStep.execution_prompts && mostRecentStep.execution_prompts.length > 0) {
            for (const prompt of mostRecentStep.execution_prompts) {
              window.addGuidedPrompt();
              
              // Get the most recently added prompt container
              const promptContainers = document.querySelectorAll('#guided-prompts-list > div');
              const lastPromptContainer = promptContainers[promptContainers.length - 1];
              
              if (lastPromptContainer) {
                // Set label
                const labelInput = lastPromptContainer.querySelector('.guided-prompt-label');
                if (labelInput) {
                  labelInput.value = prompt.label || '';
                  labelInput.dispatchEvent(new Event('input'));
                  labelInput.dispatchEvent(new Event('blur'));
                }
                
                // Set type
                const typeSelect = lastPromptContainer.querySelector('.guided-prompt-type');
                if (typeSelect && prompt.type) {
                  typeSelect.value = prompt.type;
                }
                
                // Set unit
                const unitSelect = lastPromptContainer.querySelector('.guided-prompt-unit');
                if (unitSelect && prompt.unit) {
                  unitSelect.value = prompt.unit;
                }
                
                // Set required
                const requiredSelect = lastPromptContainer.querySelector('.guided-prompt-required');
                if (requiredSelect) {
                  requiredSelect.value = prompt.required !== false ? 'true' : 'false';
                }
                
                // Update label display in header
                const updateLabelDisplay = () => {
                  const labelDisplay = lastPromptContainer.querySelector('.guided-prompt-label-display');
                  const titleSpan = lastPromptContainer.querySelector('.guided-prompt-title');
                  if (labelDisplay && titleSpan && prompt.label) {
                    labelDisplay.textContent = prompt.label;
                    labelDisplay.style.display = 'inline';
                    titleSpan.style.display = 'none';
                  }
                };
                updateLabelDisplay();
              }
            }
          }
          
          // Navigate to the appropriate step based on what data exists
          // Determine which step to show based on what was filled in
          let targetStep = 1;
          if (mostRecentStep.inputs && mostRecentStep.inputs.length > 0) {
            targetStep = 2; // Go to inputs step
          } else if (mostRecentStep.outputs && mostRecentStep.outputs.length > 0) {
            targetStep = 3; // Go to outputs step
          } else if (mostRecentStep.execution_prompts && mostRecentStep.execution_prompts.length > 0) {
            targetStep = 4; // Go to prompts step
          }
          
          console.log('Draft restoration complete, setting currentStep to:', targetStep, 'isRestoringDraft:', isRestoringDraft);
          
          // Set currentStep immediately (don't wait for animation frames)
          currentStep = targetStep;
          console.log('Immediately set currentStep to:', currentStep);
          
          // Update display immediately (don't wait for animation frames)
          updateStepDisplay();
          console.log('Called updateStepDisplay immediately after setting currentStep');
          
          // Also update display after all restoration is complete (double-check)
          // Use multiple animation frames to ensure modal is fully rendered
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              // Set the step again to ensure it wasn't reset (use closure variable)
              const stepToShow = targetStep;
              currentStep = stepToShow;
              console.log('In requestAnimationFrame, setting currentStep to:', currentStep, 'before updateStepDisplay');
              updateStepDisplay();
              console.log('Step display updated, currentStep:', currentStep);
              
              // Double-check that the correct step is visible
              const stepDiv = document.getElementById(`create-process-step-${currentStep}`);
              if (stepDiv) {
                console.log(`Step ${currentStep} display style:`, stepDiv.style.display);
                if (stepDiv.style.display !== 'block') {
                  console.warn(`Step ${currentStep} is not visible, forcing display`);
                  stepDiv.style.display = 'block';
                }
              }
              
              // Also hide step 1 explicitly to prevent it from showing
              const step1Div = document.getElementById('create-process-step-1');
              if (step1Div && currentStep !== 1) {
                step1Div.style.display = 'none';
                console.log('Explicitly hid step 1');
              }
              
              // Clear restoration flag AFTER display is updated
              isRestoringDraft = false;
              console.log('Cleared isRestoringDraft flag');
            });
          });
        }
      }
      
      // Only clear restoration flag if we didn't restore a step (no steps to restore)
      if (!processData.steps || processData.steps.length === 0) {
        isRestoringDraft = false;
      }
      
      return true;
    } catch (error) {
      console.error('Error loading draft:', error);
      return false;
    }
  }
  
  // Open the create process modal
  window.openCreateProcessModal = async function() {
    const modal = document.getElementById('create-process-modal');
    if (modal) {
      modal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
      
      // Clear inventory cache to get fresh data
      inventoryCache = null;
      selectedInventoryItems.clear();
      
      // Reset restoration flag before loading
      isRestoringDraft = false;
      console.log('openCreateProcessModal: Reset isRestoringDraft to false');
      
      // Try to load draft from database
      const draftLoaded = await loadDraft();
      
      console.log('openCreateProcessModal: draftLoaded =', draftLoaded, 'isRestoringDraft =', isRestoringDraft);
      
      if (!draftLoaded) {
        // Only reset if we're not restoring a draft
        if (!isRestoringDraft) {
          console.log('openCreateProcessModal: No draft loaded and not restoring, resetting to step 1');
          currentStep = 1;
          guidedInputs = [];
          guidedOutputs = [];
          updateStepDisplay();
          resetForm();
        } else {
          console.log('openCreateProcessModal: No draft loaded but isRestoringDraft is true, skipping reset');
        }
        
        // Reset modal title
        const modalTitle = document.getElementById('modal-title');
        const modalDescription = document.getElementById('modal-description');
        if (modalTitle) {
          modalTitle.textContent = 'Create Process Step';
        }
        if (modalDescription) {
          modalDescription.textContent = 'You can expand existing steps to edit them, or use this interactive editor to add additional steps.';
        }
      } else {
        // If draft loaded, loadDraft() already set currentStep to the appropriate step
        // and will call updateStepDisplay() after restoration completes
        // We don't need to do anything here - just wait for loadDraft() to finish
        // The step will be set and displayed by loadDraft()
        // DO NOT call updateStepDisplay() or resetForm() here as it will override loadDraft()
        console.log('Draft loaded, waiting for loadDraft() to set step and update display');
      }
    }
  };
  
  // Close modal
  function closeModal() {
    const modal = document.getElementById('create-process-modal');
    if (modal) {
      modal.style.display = 'none';
      document.body.style.overflow = 'auto';
    }
  }
  
  // Hide the "Save as draft or discard?" confirmation modal
  function hideSaveDraftOrDiscardModal() {
    const confirmModal = document.getElementById('save-draft-or-discard-modal');
    if (confirmModal) {
      confirmModal.style.display = 'none';
    }
  }
  
  // Show "Save as draft or discard?" when user clicks Cancel or X (instead of closing immediately)
  function requestCloseCreateProcessModal() {
    const confirmModal = document.getElementById('save-draft-or-discard-modal');
    if (confirmModal) {
      confirmModal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
    }
  }
  
  // Reset form (but keep created steps)
  function resetForm(keepSteps = false) {
    document.getElementById('guided-step-name').value = '';
    document.getElementById('guided-step-description').value = '';
    document.getElementById('guided-inputs-list').innerHTML = '';
    document.getElementById('guided-outputs-list').innerHTML = '';
    document.getElementById('guided-prompts-list').innerHTML = '';
    guidedInputs = [];
    guidedOutputs = [];
    guidedPrompts = [];
    selectedInventoryItems.clear();
    
    // Reset button text to initial state
    updateInputButtonsText();
    updateOutputButtonText();
    
    // Hide post-creation options
    const postCreationOptions = document.getElementById('post-creation-options');
    if (postCreationOptions) {
      postCreationOptions.style.display = 'none';
    }
    
    // Reset to step 1 (unless we're restoring a draft)
    if (!isRestoringDraft) {
      currentStep = 1;
      updateStepDisplay();
    }
    
    // Clear created steps if not keeping them
    if (!keepSteps) {
      createdSteps = [];
      editingStepId = null;
      const summariesContainer = document.getElementById('step-summaries-container');
      if (summariesContainer) {
        summariesContainer.style.display = 'none';
      }
      const summariesList = document.getElementById('step-summaries-list');
      if (summariesList) {
        summariesList.innerHTML = '';
      }
    }
  }
  
  // Update step display
  function updateStepDisplay() {
    console.log('updateStepDisplay called, currentStep:', currentStep, 'isRestoringDraft:', isRestoringDraft);
    
    // If we're restoring a draft and currentStep is 1, but we should be on a different step,
    // don't update (something else will set it correctly)
    // BUT: if isRestoringDraft is true and currentStep is already set to something other than 1, allow it
    if (isRestoringDraft && currentStep === 1) {
      console.warn('updateStepDisplay called with currentStep=1 during draft restoration, skipping to prevent reset');
      return;
    }
    
    // Update step indicators
    for (let i = 1; i <= totalSteps; i++) {
      const indicator = document.querySelector(`.step-indicator[data-step="${i}"]`);
      if (indicator) {
        if (i === currentStep) {
          indicator.style.background = 'var(--primary, #3b82f6)';
          indicator.style.color = 'white';
          indicator.style.border = 'none';
        } else if (i < currentStep) {
          indicator.style.background = 'var(--success, #10b981)';
          indicator.style.color = 'white';
          indicator.style.border = 'none';
        } else {
          indicator.style.background = 'var(--bg-secondary, #f3f4f6)';
          indicator.style.color = 'var(--text-secondary)';
          indicator.style.border = '2px solid var(--border-default, #e5e7eb)';
        }
      }
    }
    
    // Show/hide steps - use !important to override inline styles
    for (let i = 1; i <= totalSteps; i++) {
      const stepDiv = document.getElementById(`create-process-step-${i}`);
      if (stepDiv) {
        if (i === currentStep) {
          stepDiv.style.display = 'block';
          console.log(`Showing step ${i}`);
        } else {
          stepDiv.style.display = 'none';
          console.log(`Hiding step ${i}`);
        }
      } else {
        console.warn(`Step div not found: create-process-step-${i}`);
      }
    }
  }
  
  // Navigate to next step
  window.createProcessNextStep = function() {
    if (currentStep === 1) {
      // Validate step 1
      const stepName = document.getElementById('guided-step-name').value.trim();
      if (!stepName) {
        alert('Please enter a step name');
        return;
      }
    }
    // Step 2 and 3 don't require validation (inputs/outputs are optional)
    // Step 4 (execution prompts) is also optional
    
    if (currentStep < totalSteps) {
      currentStep++;
      updateStepDisplay();
    }
  };
  
  // Navigate to previous step
  window.createProcessPreviousStep = function() {
    if (currentStep > 1) {
      currentStep--;
      updateStepDisplay();
    }
  };
  
  // Unit groups (matching flows2.html)
  const unitGroups = {
    weight: ['kg', 'g'],
    volume: ['L', 'mL'],
    count: ['pcs', 'units']
  };
  
  // Load inventory items (all types)
  let inventoryCache = null;
  // Get previous step outputs for current step
  function getPreviousStepOutputs() {
    const previousOutputs = [];
    
    // Get outputs from all previously created steps
    // createdSteps contains steps that have been created in this session
    // Sort by step_number to ensure correct order
    const sortedSteps = [...createdSteps].sort((a, b) => (a.step_number || 0) - (b.step_number || 0));
    
    sortedSteps.forEach(step => {
      if (step.outputs && step.outputs.length > 0) {
        step.outputs.forEach(output => {
          if (output.name) {
            // Ensure step_number is valid (should be from step.step_number)
            const stepNumber = step.step_number || 0;
            previousOutputs.push({
              name: output.name,
              quantity: output.quantity !== null && output.quantity !== undefined ? output.quantity : null,
              unit: output.unit || '',
              step_number: stepNumber,
              is_previous_output: true, // Mark as previous output
              displayName: `Step ${stepNumber}: ${output.name}` // For display in dropdown
            });
          }
        });
      }
    });
    
    console.log('getPreviousStepOutputs: found', previousOutputs.length, 'outputs from', sortedSteps.length, 'steps');
    console.log('Step numbers:', sortedSteps.map(s => s.step_number));
    
    return previousOutputs;
  }
  
  async function loadInventoryItems() {
    if (inventoryCache) {
      return inventoryCache;
    }
    
    try {
      // Load all inventory types - collect from multiple sources
      let items = [];
      // Get process ID from URL params (same way as flows2.html)
      const urlParams = new URLSearchParams(window.location.search);
      const processId = urlParams.get('id') || null;
      
      console.log('Loading inventory items, processId:', processId);
      
      // Always try to load all inventory types to give users full selection
      // 1. Try loading with processId (if available)
      if (processId) {
        try {
          const inventoryData = await CoreAPI.getInventory(null, processId);
          const processItems = inventoryData.inventory_items || [];
          items.push(...processItems);
          console.log('Loaded inventory with processId:', processItems.length);
        } catch (err) {
          console.warn('Failed to load inventory with processId:', err);
        }
      }
      
      // 2. Always load raw materials (these are commonly used)
      try {
        const rawMaterialsData = await CoreAPI.getInventory('raw_material');
        const rawItems = rawMaterialsData.inventory_items || [];
        items.push(...rawItems);
        console.log('Loaded raw materials:', rawItems.length);
      } catch (err) {
        console.warn('Failed to load raw materials:', err);
      }
      
      // 3. Try loading all inventory without filters (catch-all)
      try {
        const allInventoryData = await CoreAPI.getInventory();
        const allItems = allInventoryData.inventory_items || [];
        items.push(...allItems);
        console.log('Loaded all inventory:', allItems.length);
      } catch (err) {
        console.warn('Failed to load all inventory:', err);
      }
      
      // Get unique inventory items by name and category (preserve category info)
      // Group by category first, then deduplicate within each category
      const categorizedItems = {
        raw_material: [],
        work_in_progress: [],
        final_product: []
      };
      const seenNamesByCategory = {
        raw_material: new Set(),
        work_in_progress: new Set(),
        final_product: new Set()
      };
      
      items.forEach(item => {
        if (item && item.name) {
          // Determine category - default to raw_material if not specified
          const category = item.inventory_type || 'raw_material';
          const categoryKey = category === 'work_in_progress' ? 'work_in_progress' : 
                             category === 'final_product' ? 'final_product' : 
                             'raw_material';
          
          // Only add if we haven't seen this name in this category
          if (!seenNamesByCategory[categoryKey].has(item.name)) {
            seenNamesByCategory[categoryKey].add(item.name);
            categorizedItems[categoryKey].push({
              name: item.name,
              unit: item.unit || '',
              category: categoryKey
            });
          }
        }
      });
      
      // Return categorized items
      console.log('Total inventory items by category:', {
        raw_material: categorizedItems.raw_material.length,
        work_in_progress: categorizedItems.work_in_progress.length,
        final_product: categorizedItems.final_product.length
      });
      
      inventoryCache = categorizedItems;
      return categorizedItems;
    } catch (error) {
      console.error('Failed to load inventory items:', error);
      console.error('Error details:', error.message, error.stack);
      // Return empty categorized structure on error
      return {
        raw_material: [],
        work_in_progress: [],
        final_product: []
      };
    }
  }
  
  // Create searchable dropdown for inventory with category grouping
  function createInventorySearchableDropdown(categorizedItems, onSelect, container, placeholderText = null) {
    const uniqueId = `guided-dropdown-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const dropdownContainer = document.createElement('div');
    dropdownContainer.className = 'searchable-dropdown-container';
    dropdownContainer.style.position = 'relative';
    dropdownContainer.style.width = '100%';
    
    // Determine placeholder based on whether we have previous outputs only or inventory items
    let placeholder = placeholderText;
    if (!placeholder) {
      const hasPreviousOutputs = categorizedItems.previous_outputs && categorizedItems.previous_outputs.length > 0;
      const hasInventory = (categorizedItems.raw_material?.length || 0) + 
                          (categorizedItems.work_in_progress?.length || 0) + 
                          (categorizedItems.final_product?.length || 0) > 0;
      if (hasPreviousOutputs && !hasInventory) {
        placeholder = 'Search previous step outputs...';
      } else {
        placeholder = 'Search inventory items...';
      }
    }
    
    dropdownContainer.innerHTML = `
      <input 
        type="text" 
        class="form-input guided-input-name searchable-dropdown-input" 
        placeholder="${placeholder}"
        autocomplete="off"
        style="width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); color: var(--text-primary); font-size: 13px;"
        data-dropdown-id="${uniqueId}"
      />
      <div 
        class="searchable-dropdown-list" 
        id="${uniqueId}"
        style="display: none; position: absolute; top: 100%; left: 0; right: 0; z-index: 1000; max-height: 300px; overflow-y: auto; background: var(--bg-card); border: 1px solid var(--border-default); border-radius: var(--radius-md); margin-top: 4px; box-shadow: var(--shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.12));"
      ></div>
    `;
    
    const input = dropdownContainer.querySelector('.searchable-dropdown-input');
    const dropdown = dropdownContainer.querySelector('.searchable-dropdown-list');
    let filteredItems = [];
    let selectedIndex = -1;
    
    // Flatten categorized items into a single array for easier filtering
    function flattenItems(categorized) {
      const allItems = [];
      if (categorized.raw_material) {
        allItems.push(...categorized.raw_material);
      }
      if (categorized.work_in_progress) {
        allItems.push(...categorized.work_in_progress);
      }
      if (categorized.final_product) {
        allItems.push(...categorized.final_product);
      }
      if (categorized.previous_outputs) {
        allItems.push(...categorized.previous_outputs);
      }
      return allItems;
    }
    
    // Get all items as flat array
    const allItems = flattenItems(categorizedItems);
    
    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }
    
    function getAvailableItems() {
      // Filter out already selected items (except the one currently selected in this input)
      return allItems.filter(item => {
        const isSelected = selectedInventoryItems.has(item.name);
        const isCurrentSelection = input.value.trim() === item.name;
        return !isSelected || isCurrentSelection;
      });
    }
    
    // Group items by category
    function groupByCategory(items) {
      const grouped = {
        raw_material: [],
        work_in_progress: [],
        final_product: [],
        previous_outputs: []
      };
      items.forEach(item => {
        const category = item.category || 'raw_material';
        if (grouped[category]) {
          grouped[category].push(item);
        }
      });
      return grouped;
    }
    
    // Initialize filteredItems
    filteredItems = getAvailableItems();
    
    function renderDropdown() {
      const availableItems = getAvailableItems();
      
      if (availableItems.length === 0) {
        dropdown.innerHTML = '<div style="padding: 12px; color: var(--text-secondary); text-align: center; font-size: 13px;">No items available (all items may already be selected)</div>';
        dropdown.style.display = 'block';
        return;
      }
      
      // Apply search filter if there's a search term
      let itemsToShow = availableItems;
      const searchTerm = input.value.trim().toLowerCase();
      if (searchTerm) {
        itemsToShow = availableItems.filter(item => item.name.toLowerCase().includes(searchTerm));
      }
      
      // Group filtered items by category
      const grouped = groupByCategory(itemsToShow);
      
      // Category labels
      const categoryLabels = {
        raw_material: 'Raw Materials',
        work_in_progress: 'Intermediate',
        final_product: 'Final Products',
        previous_outputs: 'Previous Step Outputs'
      };
      
      // Category order - previous outputs first so they're easy to find
      const categoryOrder = ['previous_outputs', 'raw_material', 'work_in_progress', 'final_product'];
      
      // Build flat array in the same order as rendering (for index mapping)
      const flatItemsForIndex = [];
      categoryOrder.forEach(category => {
        const categoryItems = grouped[category] || [];
        flatItemsForIndex.push(...categoryItems);
      });
      
      // Store flat items for click/keyboard handlers
      filteredItems = flatItemsForIndex;
      
      let html = '';
      let itemIndex = 0;
      
      categoryOrder.forEach(category => {
        const categoryItems = grouped[category] || [];
        if (categoryItems.length > 0) {
          // Category header
          html += `
            <div style="padding: 8px 12px; background: var(--bg-secondary, #f9fafb); border-bottom: 1px solid var(--border-default); font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; position: sticky; top: 0; z-index: 10;">
              ${escapeHtml(categoryLabels[category])}
            </div>
          `;
          
          // Category items
          categoryItems.forEach(item => {
            const isSelected = itemIndex === selectedIndex;
            // Use displayName if available (for previous outputs), otherwise use name
            const displayText = item.displayName || item.name;
            html += `
              <div 
                class="dropdown-item ${isSelected ? 'selected' : ''}"
                data-index="${itemIndex}"
                data-category="${category}"
                style="padding: 10px 12px 10px 24px; cursor: pointer; border-bottom: 1px solid var(--border-light); transition: background 0.15s; ${isSelected ? 'background: var(--bg-hover, rgba(0, 0, 0, 0.05));' : ''}"
                onmouseover="this.style.background='var(--bg-hover, rgba(0, 0, 0, 0.05))'"
                onmouseout="if (!this.classList.contains('selected')) this.style.background='transparent'"
              >
                <div style="font-weight: 500; color: var(--text-primary); font-size: 13px;">${escapeHtml(displayText)}</div>
                ${item.is_previous_output ? `<div style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">From previous step</div>` : ''}
              </div>
            `;
            itemIndex++;
          });
        }
      });
      
      dropdown.innerHTML = html;
      dropdown.style.display = 'block';
    }
    
    function filterItems(searchTerm) {
      selectedIndex = -1;
      renderDropdown(); // renderDropdown handles filtering internally
    }
    
    function selectItem(item) {
      // Remove previous selection from this input if any
      const previousValue = input.value.trim();
      if (previousValue && previousValue !== item.name) {
        selectedInventoryItems.delete(previousValue);
      }
      
      if (onSelect) {
        onSelect(item);
      }
      // Use the actual name (not displayName) for the input value
      input.value = item.name;
      // Mark this item as selected
      selectedInventoryItems.add(item.name);
      dropdown.style.display = 'none';
    }
    
    // Get flat array of all filtered items for selection (matches renderDropdown order)
    function getFilteredItemsFlat() {
      return filteredItems; // filteredItems is set by renderDropdown in the correct order
    }
    
    input.addEventListener('input', (e) => {
      filterItems(e.target.value);
    });
    
    input.addEventListener('focus', () => {
      // Re-filter to exclude newly selected items
      renderDropdown();
    });
    
    input.addEventListener('blur', () => {
      // Delay hiding to allow click events
      setTimeout(() => {
        dropdown.style.display = 'none';
      }, 200);
    });
    
    dropdown.addEventListener('click', (e) => {
      const itemEl = e.target.closest('.dropdown-item');
      if (itemEl) {
        const index = parseInt(itemEl.dataset.index);
        const flatItems = getFilteredItemsFlat();
        if (flatItems[index]) {
          const itemToSelect = flatItems[index];
          selectItem(itemToSelect);
        }
      }
    });
    
    // Keyboard navigation
    input.addEventListener('keydown', (e) => {
      const flatItems = getFilteredItemsFlat();
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIndex = Math.min(selectedIndex + 1, flatItems.length - 1);
        renderDropdown();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIndex = Math.max(selectedIndex - 1, -1);
        renderDropdown();
      } else if (e.key === 'Enter' && selectedIndex >= 0 && flatItems[selectedIndex]) {
        e.preventDefault();
        const itemToSelect = flatItems[selectedIndex];
        selectItem(itemToSelect);
      }
    });
    
    return dropdownContainer;
  }
  
  // Collapse all inputs except the specified one
  function collapseAllInputs(exceptId = null) {
    const allInputs = document.querySelectorAll('#guided-inputs-list > div');
    allInputs.forEach(inputEl => {
      if (inputEl.id !== exceptId) {
        const contentArea = inputEl.querySelector('.guided-input-content');
        const expandIcon = inputEl.querySelector('.guided-input-expand-icon');
        const expandHint = inputEl.querySelector('.guided-input-expand-hint');
        if (contentArea && expandIcon) {
          contentArea.style.display = 'none';
          expandIcon.style.transform = 'rotate(0deg)';
          inputEl.dataset.expanded = 'false';
          if (expandHint) expandHint.textContent = '(click to expand)';
        }
      }
    });
  }
  
  // Collapse all outputs except the specified one
  function collapseAllOutputs(exceptId = null) {
    const allOutputs = document.querySelectorAll('#guided-outputs-list > div');
    allOutputs.forEach(outputEl => {
      if (outputEl.id !== exceptId) {
        const contentArea = outputEl.querySelector('.guided-output-content');
        const expandIcon = outputEl.querySelector('.guided-output-expand-icon');
        const expandHint = outputEl.querySelector('.guided-output-expand-hint');
        if (contentArea && expandIcon) {
          contentArea.style.display = 'none';
          expandIcon.style.transform = 'rotate(0deg)';
          outputEl.dataset.expanded = 'false';
          if (expandHint) expandHint.textContent = '(click to expand)';
        }
      }
    });
  }
  
  // Toggle input expand/collapse
  function toggleInputExpand(inputId) {
    const inputEl = document.getElementById(inputId);
    if (!inputEl) return;
    
    const contentArea = inputEl.querySelector('.guided-input-content');
    const expandIcon = inputEl.querySelector('.guided-input-expand-icon');
    const expandHint = inputEl.querySelector('.guided-input-expand-hint');
    if (!contentArea || !expandIcon) return;
    
    const isExpanded = inputEl.dataset.expanded === 'true';
    if (isExpanded) {
      contentArea.style.display = 'none';
      expandIcon.style.transform = 'rotate(0deg)';
      inputEl.dataset.expanded = 'false';
      if (expandHint) expandHint.textContent = '(click to expand)';
    } else {
      contentArea.style.display = 'block';
      expandIcon.style.transform = 'rotate(180deg)';
      inputEl.dataset.expanded = 'true';
      if (expandHint) expandHint.textContent = '(click to collapse)';
      // Collapse all other inputs
      collapseAllInputs(inputId);
    }
  }
  
  // Toggle output expand/collapse
  function toggleOutputExpand(outputId) {
    const outputEl = document.getElementById(outputId);
    if (!outputEl) return;
    
    const contentArea = outputEl.querySelector('.guided-output-content');
    const expandIcon = outputEl.querySelector('.guided-output-expand-icon');
    const expandHint = outputEl.querySelector('.guided-output-expand-hint');
    if (!contentArea || !expandIcon) return;
    
    const isExpanded = outputEl.dataset.expanded === 'true';
    if (isExpanded) {
      contentArea.style.display = 'none';
      expandIcon.style.transform = 'rotate(0deg)';
      outputEl.dataset.expanded = 'false';
      if (expandHint) expandHint.textContent = '(click to expand)';
    } else {
      contentArea.style.display = 'block';
      expandIcon.style.transform = 'rotate(180deg)';
      outputEl.dataset.expanded = 'true';
      if (expandHint) expandHint.textContent = '(click to collapse)';
      // Collapse all other outputs
      collapseAllOutputs(outputId);
    }
  }
  
  // Add guided input
  window.addGuidedInput = async function(type) {
    // Collapse all existing inputs before adding a new one
    collapseAllInputs();
    
    const inputId = `guided-input-${Date.now()}`;
    const inputContainer = document.createElement('div');
    inputContainer.id = inputId;
    inputContainer.dataset.expanded = 'true'; // New input starts expanded
    inputContainer.style.cssText = 'background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); margin-bottom: 12px; overflow: hidden;';
    
    // Create header with expand/collapse
    const header = document.createElement('div');
    header.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 12px; cursor: pointer; background: var(--bg-secondary, #f9fafb);';
    header.onclick = () => toggleInputExpand(inputId);
    
    const headerLeft = document.createElement('div');
    headerLeft.style.cssText = 'display: flex; align-items: center; gap: 8px;';
    
    const expandIcon = document.createElement('svg');
    expandIcon.className = 'guided-input-expand-icon';
    expandIcon.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    expandIcon.setAttribute('width', '16');
    expandIcon.setAttribute('height', '16');
    expandIcon.setAttribute('viewBox', '0 0 24 24');
    expandIcon.setAttribute('fill', 'none');
    expandIcon.setAttribute('stroke', 'currentColor');
    expandIcon.setAttribute('stroke-width', '2');
    expandIcon.setAttribute('stroke-linecap', 'round');
    expandIcon.setAttribute('stroke-linejoin', 'round');
    expandIcon.style.cssText = 'transition: transform 0.2s; transform: rotate(180deg);';
    expandIcon.innerHTML = '<polyline points="6 9 12 15 18 9"></polyline>';
    headerLeft.appendChild(expandIcon);
    
    const titleSpan = document.createElement('span');
    titleSpan.className = 'guided-input-title';
    titleSpan.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary);';
    if (type === 'inventory') {
      titleSpan.textContent = 'Inventory Input';
    } else if (type === 'previous_output') {
      titleSpan.textContent = 'Previous Output Input';
    } else {
      titleSpan.textContent = 'New Input';
    }
    headerLeft.appendChild(titleSpan);
    
    // Add name display that will show when collapsed (replaces title when name is entered)
    const nameDisplay = document.createElement('span');
    nameDisplay.className = 'guided-input-name-display';
    nameDisplay.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary); display: none;';
    nameDisplay.textContent = '';
    headerLeft.appendChild(nameDisplay);
    
    // Add expand/collapse hint text
    const expandHint = document.createElement('span');
    expandHint.className = 'guided-input-expand-hint';
    expandHint.style.cssText = 'font-size: 11px; color: var(--text-tertiary, #9ca3af); margin-left: 8px; font-style: italic;';
    expandHint.textContent = '(click to collapse)';
    headerLeft.appendChild(expandHint);
    
    // Function to update name display
    const updateNameDisplay = () => {
      let name = '';
      if (type === 'inventory' || type === 'previous_output') {
        const nameInput = inputContainer.querySelector('.guided-input-name.searchable-dropdown-input');
        if (nameInput) {
          name = nameInput.value.trim();
        }
      } else {
        const nameInput = inputContainer.querySelector('.guided-input-name:not(.searchable-dropdown-input)');
        if (nameInput) {
          name = nameInput.value.trim();
        }
      }
      
      if (name) {
        nameDisplay.textContent = name;
        nameDisplay.style.display = 'inline';
        titleSpan.style.display = 'none';
      } else {
        nameDisplay.style.display = 'none';
        titleSpan.style.display = 'inline';
      }
    };
    
    header.appendChild(headerLeft);
    
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.onclick = (e) => {
      e.stopPropagation();
      window.removeGuidedInput(inputId);
    };
    removeButton.style.cssText = 'padding: 4px 8px; border: none; background: transparent; color: var(--error, #ef4444); cursor: pointer; font-size: 12px;';
    removeButton.textContent = 'Remove';
    header.appendChild(removeButton);
    
    inputContainer.appendChild(header);
    
    // Create content area
    const contentArea = document.createElement('div');
    contentArea.className = 'guided-input-content';
    contentArea.style.cssText = 'padding: 12px; display: block;';
    
    if (type === 'inventory' || type === 'previous_output') {
      // For 'previous_output' type, only show previous outputs
      // For 'inventory' type, show inventory items (but not previous outputs)
      let allCategorizedItems;
      
      if (type === 'previous_output') {
        // Only get previous step outputs
        const previousOutputs = getPreviousStepOutputs();
        
        if (previousOutputs.length === 0) {
          const messageDiv = document.createElement('div');
          messageDiv.style.cssText = 'padding: 12px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); color: var(--text-secondary); font-size: 13px;';
          messageDiv.textContent = 'No previous step outputs available. Create a step with outputs first.';
          contentArea.appendChild(messageDiv);
          inputContainer.appendChild(contentArea);
          document.getElementById('guided-inputs-list').appendChild(inputContainer);
          return;
        }
        
        allCategorizedItems = {
          raw_material: [],
          work_in_progress: [],
          final_product: [],
          previous_outputs: previousOutputs.map(output => ({
            name: output.name,
            unit: output.unit || '',
            category: 'previous_outputs',
            displayName: output.displayName || output.name,
            is_previous_output: true,
            step_number: output.step_number,
            quantity: output.quantity
          }))
        };
      } else {
        // Load inventory items (now returns categorized object)
        const categorizedItems = await loadInventoryItems();
        allCategorizedItems = {
          ...categorizedItems,
          previous_outputs: [] // Don't include previous outputs in inventory dropdown
        };
        
        // Check if we have any items at all
        const totalItems = (allCategorizedItems.raw_material?.length || 0) + 
                          (allCategorizedItems.work_in_progress?.length || 0) + 
                          (allCategorizedItems.final_product?.length || 0);
        
        if (totalItems === 0) {
          // Show a message if no inventory items are available
          const messageDiv = document.createElement('div');
          messageDiv.style.cssText = 'padding: 12px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); color: var(--text-secondary); font-size: 13px;';
          messageDiv.textContent = 'No inventory items available. Please add inventory items first.';
          contentArea.appendChild(messageDiv);
          inputContainer.appendChild(contentArea);
          document.getElementById('guided-inputs-list').appendChild(inputContainer);
          return;
        }
      }
      
      // Name field with searchable dropdown
      const nameField = document.createElement('div');
      nameField.style.marginBottom = '12px';
      const nameLabel = document.createElement('label');
      nameLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      nameLabel.textContent = type === 'previous_output' ? 'Previous Step Output' : 'Inventory Item';
      nameField.appendChild(nameLabel);
      
      // Filter out already selected items from each category
      const filteredCategorized = {
        raw_material: (allCategorizedItems.raw_material || []).filter(item => !selectedInventoryItems.has(item.name)),
        work_in_progress: (allCategorizedItems.work_in_progress || []).filter(item => !selectedInventoryItems.has(item.name)),
        final_product: (allCategorizedItems.final_product || []).filter(item => !selectedInventoryItems.has(item.name)),
        previous_outputs: (allCategorizedItems.previous_outputs || []).filter(item => !selectedInventoryItems.has(item.name))
      };
      
      const nameDropdown = createInventorySearchableDropdown(
        filteredCategorized,
        (item) => {
          // When item is selected, update unit if available
          const unitSelect = inputContainer.querySelector('.guided-input-unit');
          if (unitSelect && item.unit) {
            unitSelect.value = item.unit;
          }
          // If it's a previous output, also auto-fill quantity
          if (item.is_previous_output && item.quantity !== null && item.quantity !== undefined) {
            const quantityInput = inputContainer.querySelector('.guided-input-quantity');
            if (quantityInput) {
              quantityInput.value = item.quantity;
            }
          }
          // Mark this item as selected (use the actual name, not displayName)
          selectedInventoryItems.add(item.name);
          // Update the dropdown to exclude this item from other inputs
          updateInventoryDropdowns();
          // Update name display in header directly with the item name (not displayName)
          if (item.name) {
            nameDisplay.textContent = item.name;
            nameDisplay.style.display = 'inline';
            titleSpan.style.display = 'none';
          }
        },
        inputContainer,
        type === 'previous_output' ? 'Search previous step outputs...' : null
      );
      nameField.appendChild(nameDropdown);
      contentArea.appendChild(nameField);
      
      // Listen for changes to the name input
      const nameInput = nameDropdown.querySelector('.searchable-dropdown-input');
      if (nameInput) {
        nameInput.addEventListener('input', updateNameDisplay);
        nameInput.addEventListener('blur', updateNameDisplay);
      }
      
      // Quantity field
      const quantityField = document.createElement('div');
      quantityField.style.marginBottom = '12px';
      const quantityLabel = document.createElement('label');
      quantityLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      quantityLabel.textContent = 'Quantity';
      quantityField.appendChild(quantityLabel);
      const quantityInput = document.createElement('input');
      quantityInput.type = 'number';
      quantityInput.className = 'guided-input-quantity';
      quantityInput.placeholder = '0';
      quantityInput.step = '0.01';
      quantityInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
      quantityField.appendChild(quantityInput);
      contentArea.appendChild(quantityField);
      
      // Unit dropdown
      const unitField = document.createElement('div');
      unitField.style.marginBottom = '12px';
      const unitLabel = document.createElement('label');
      unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      unitLabel.textContent = 'Unit';
      unitField.appendChild(unitLabel);
      const unitSelect = document.createElement('select');
      unitSelect.className = 'guided-input-unit form-select';
      unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
      [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
        const option = document.createElement('option');
        option.value = unit;
        option.textContent = unit;
        unitSelect.appendChild(option);
      });
      unitField.appendChild(unitSelect);
      contentArea.appendChild(unitField);
      
      // Execution type dropdown (only for inventory, not for previous_output)
      if (type === 'inventory') {
        const typeField = document.createElement('div');
        const typeLabel = document.createElement('label');
        typeLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
        typeLabel.textContent = 'Execution Type';
        typeField.appendChild(typeLabel);
        const typeSelect = document.createElement('select');
        typeSelect.className = 'guided-input-execution-type form-select';
        typeSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
        
        const variableOption = document.createElement('option');
        variableOption.value = 'variable';
        variableOption.textContent = 'Select inventory at execution';
        typeSelect.appendChild(variableOption);
        
        const staticOption = document.createElement('option');
        staticOption.value = 'static';
        staticOption.textContent = 'Use this exact input every execution';
        typeSelect.appendChild(staticOption);
        
        typeField.appendChild(typeSelect);
        
        // Explanation text
        const explanationDiv = document.createElement('div');
        explanationDiv.style.cssText = 'margin-top: 8px; padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); font-size: 12px; color: var(--text-secondary); line-height: 1.4;';
        explanationDiv.id = `guided-input-explanation-${inputId}`;
        explanationDiv.innerHTML = '<strong>Select inventory at execution:</strong> You will choose which supplier batch is consumed when this step runs. This allows you to track specific batches through your process.';
        typeField.appendChild(explanationDiv);
        
        // Update explanation when type changes
        typeSelect.addEventListener('change', function() {
          const explanation = document.getElementById(`guided-input-explanation-${inputId}`);
          if (this.value === 'variable') {
            explanation.innerHTML = '<strong>Select inventory at execution:</strong> You will choose which supplier batch is consumed when this step runs. This allows you to track specific batches through your process.';
          } else {
            explanation.innerHTML = '<strong>Use this exact input every execution:</strong> The system will use the same quantity and unit for every execution without prompting. Use this for consistent inputs that don\'t vary between batches.';
          }
        });
        
        contentArea.appendChild(typeField);
      }
    } else {
      // New Input
      
      // Name field
      const nameField = document.createElement('div');
      nameField.style.marginBottom = '12px';
      const nameLabel = document.createElement('label');
      nameLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      nameLabel.textContent = 'Name';
      nameField.appendChild(nameLabel);
      const nameInput = document.createElement('input');
      nameInput.type = 'text';
      nameInput.className = 'guided-input-name';
      nameInput.placeholder = 'e.g., Water, Additive';
      nameInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
      nameInput.addEventListener('input', updateNameDisplay);
      nameInput.addEventListener('blur', updateNameDisplay);
      nameField.appendChild(nameInput);
      contentArea.appendChild(nameField);
      
      // Quantity field
      const quantityField = document.createElement('div');
      quantityField.style.marginBottom = '12px';
      const quantityLabel = document.createElement('label');
      quantityLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      quantityLabel.textContent = 'Quantity';
      quantityField.appendChild(quantityLabel);
      const quantityInput = document.createElement('input');
      quantityInput.type = 'number';
      quantityInput.className = 'guided-input-quantity';
      quantityInput.placeholder = '0';
      quantityInput.step = '0.01';
      quantityInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
      quantityField.appendChild(quantityInput);
      contentArea.appendChild(quantityField);
      
      // Unit dropdown
      const unitField = document.createElement('div');
      unitField.style.marginBottom = '12px';
      const unitLabel = document.createElement('label');
      unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      unitLabel.textContent = 'Unit';
      unitField.appendChild(unitLabel);
      const unitSelect = document.createElement('select');
      unitSelect.className = 'guided-input-unit form-select';
      unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
      [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
        const option = document.createElement('option');
        option.value = unit;
        option.textContent = unit;
        unitSelect.appendChild(option);
      });
      unitField.appendChild(unitSelect);
      contentArea.appendChild(unitField);
      
      // Execution type dropdown
      const typeField = document.createElement('div');
      const typeLabel = document.createElement('label');
      typeLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
      typeLabel.textContent = 'Execution Type';
      typeField.appendChild(typeLabel);
      const typeSelect = document.createElement('select');
      typeSelect.className = 'guided-input-execution-type form-select';
      typeSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
      
      const promptOption = document.createElement('option');
      promptOption.value = 'prompt';
      promptOption.textContent = 'Prompt at execution';
      typeSelect.appendChild(promptOption);
      
      const staticOption = document.createElement('option');
      staticOption.value = 'static';
      staticOption.textContent = 'Use this exact input every execution';
      typeSelect.appendChild(staticOption);
      
      typeField.appendChild(typeSelect);
      
      // Explanation text
      const explanationDiv = document.createElement('div');
      explanationDiv.style.cssText = 'margin-top: 8px; padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); font-size: 12px; color: var(--text-secondary); line-height: 1.4;';
      explanationDiv.id = `guided-input-explanation-${inputId}`;
      explanationDiv.innerHTML = '<strong>Prompt at execution:</strong> You will be asked to enter or confirm the quantity and unit when this step runs. Use this for inputs that may vary between executions.';
      typeField.appendChild(explanationDiv);
      
      // Update explanation when type changes
      typeSelect.addEventListener('change', function() {
        const explanation = document.getElementById(`guided-input-explanation-${inputId}`);
        if (this.value === 'prompt') {
          explanation.innerHTML = '<strong>Prompt at execution:</strong> You will be asked to enter or confirm the quantity and unit when this step runs. Use this for inputs that may vary between executions.';
        } else {
          explanation.innerHTML = '<strong>Use this exact input every execution:</strong> The system will use the same quantity and unit for every execution without prompting. Use this for consistent inputs that don\'t vary between batches.';
        }
      });
      
      contentArea.appendChild(typeField);
    }
    
    inputContainer.appendChild(contentArea);
    document.getElementById('guided-inputs-list').appendChild(inputContainer);
    
    // Update button text after adding input
    updateInputButtonsText();
  };
  
  // Update input button text based on number of inputs
  function updateInputButtonsText() {
    const inputCount = document.querySelectorAll('#guided-inputs-list > div').length;
    const inventoryBtn = document.getElementById('add-inventory-input-btn');
    const newInputBtn = document.getElementById('add-new-input-btn');
    const previousOutputBtn = document.getElementById('add-previous-output-input-btn');
    
    // Update inventory button
    if (inventoryBtn) {
      const mainText = inputCount > 0 ? '+ Add another input' : '+ Add input';
      inventoryBtn.innerHTML = `
        <span>${mainText}</span>
        <span style="display: block; font-size: 10px; color: var(--text-tertiary, #9ca3af); font-weight: normal; margin-top: 2px;">from inventory</span>
      `;
    }
    
    // Update new input button
    if (newInputBtn) {
      const mainText = inputCount > 0 ? '+ Add another input' : '+ Add input';
      newInputBtn.innerHTML = `
        <span>${mainText}</span>
        <span style="display: block; font-size: 10px; color: var(--text-tertiary, #9ca3af); font-weight: normal; margin-top: 2px;">not from inventory</span>
      `;
    }
    
    // Show/hide previous output button based on whether we have created steps
    if (previousOutputBtn) {
      if (createdSteps.length > 0) {
        previousOutputBtn.style.display = 'flex';
      } else {
        previousOutputBtn.style.display = 'none';
      }
    }
  }
  
  // Update all inventory dropdowns to exclude selected items
  function updateInventoryDropdowns() {
    const allInputs = document.querySelectorAll('#guided-inputs-list > div');
    allInputs.forEach(inputEl => {
      const nameInput = inputEl.querySelector('.guided-input-name.searchable-dropdown-input');
      if (nameInput) {
        // This is an inventory input - we'd need to rebuild the dropdown
        // For now, we'll just filter on the fly when showing dropdown
      }
    });
  }
  
  // Remove guided input
  window.removeGuidedInput = function(inputId) {
    const inputElement = document.getElementById(inputId);
    if (inputElement) {
      // Get the selected inventory item name before removing
      const nameInput = inputElement.querySelector('.guided-input-name.searchable-dropdown-input');
      if (nameInput && nameInput.value) {
        selectedInventoryItems.delete(nameInput.value.trim());
      }
      inputElement.remove();
      
      // Update button text after removing input
      updateInputButtonsText();
    }
  };
  
  // Add guided output
  window.addGuidedOutput = function() {
    // Collapse all existing outputs before adding a new one
    collapseAllOutputs();
    
    const outputId = `guided-output-${Date.now()}`;
    const outputContainer = document.createElement('div');
    outputContainer.id = outputId;
    outputContainer.dataset.expanded = 'true'; // New output starts expanded
    outputContainer.style.cssText = 'background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); margin-bottom: 12px; overflow: hidden;';
    
    // Create header with expand/collapse
    const header = document.createElement('div');
    header.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 12px; cursor: pointer; background: var(--bg-secondary, #f9fafb);';
    header.onclick = () => toggleOutputExpand(outputId);
    
    const headerLeft = document.createElement('div');
    headerLeft.style.cssText = 'display: flex; align-items: center; gap: 8px;';
    
    const expandIcon = document.createElement('svg');
    expandIcon.className = 'guided-output-expand-icon';
    expandIcon.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    expandIcon.setAttribute('width', '16');
    expandIcon.setAttribute('height', '16');
    expandIcon.setAttribute('viewBox', '0 0 24 24');
    expandIcon.setAttribute('fill', 'none');
    expandIcon.setAttribute('stroke', 'currentColor');
    expandIcon.setAttribute('stroke-width', '2');
    expandIcon.setAttribute('stroke-linecap', 'round');
    expandIcon.setAttribute('stroke-linejoin', 'round');
    expandIcon.style.cssText = 'transition: transform 0.2s; transform: rotate(180deg);';
    expandIcon.innerHTML = '<polyline points="6 9 12 15 18 9"></polyline>';
    headerLeft.appendChild(expandIcon);
    
    const titleSpan = document.createElement('span');
    titleSpan.className = 'guided-output-title';
    titleSpan.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary);';
    titleSpan.textContent = 'Output';
    headerLeft.appendChild(titleSpan);
    
    // Add name display that will show when collapsed (replaces title when name is entered)
    const nameDisplay = document.createElement('span');
    nameDisplay.className = 'guided-output-name-display';
    nameDisplay.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary); display: none;';
    nameDisplay.textContent = '';
    headerLeft.appendChild(nameDisplay);
    
    // Add expand/collapse hint text
    const expandHint = document.createElement('span');
    expandHint.className = 'guided-output-expand-hint';
    expandHint.style.cssText = 'font-size: 11px; color: var(--text-tertiary, #9ca3af); margin-left: 8px; font-style: italic;';
    expandHint.textContent = '(click to collapse)';
    headerLeft.appendChild(expandHint);
    
    // Function to update name display
    const updateNameDisplay = () => {
      const nameInput = outputContainer.querySelector('.guided-output-name');
      const name = nameInput ? nameInput.value.trim() : '';
      
      if (name) {
        nameDisplay.textContent = name;
        nameDisplay.style.display = 'inline';
        titleSpan.style.display = 'none';
      } else {
        nameDisplay.style.display = 'none';
        titleSpan.style.display = 'inline';
      }
    };
    
    header.appendChild(headerLeft);
    
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.onclick = (e) => {
      e.stopPropagation();
      window.removeGuidedOutput(outputId);
    };
    removeButton.style.cssText = 'padding: 4px 8px; border: none; background: transparent; color: var(--error, #ef4444); cursor: pointer; font-size: 12px;';
    removeButton.textContent = 'Remove';
    header.appendChild(removeButton);
    
    outputContainer.appendChild(header);
    
    // Create content area
    const contentArea = document.createElement('div');
    contentArea.className = 'guided-output-content';
    contentArea.style.cssText = 'padding: 12px; display: block;';
    
    // Name field
    const nameField = document.createElement('div');
    nameField.style.marginBottom = '12px';
    const nameLabel = document.createElement('label');
    nameLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    nameLabel.textContent = 'Name';
    nameField.appendChild(nameLabel);
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'guided-output-name';
    nameInput.placeholder = 'e.g., Mixed Base, Final Product';
    nameInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
    nameInput.addEventListener('input', updateNameDisplay);
    nameInput.addEventListener('blur', updateNameDisplay);
    nameField.appendChild(nameInput);
    contentArea.appendChild(nameField);
    
    // Quantity field
    const quantityField = document.createElement('div');
    quantityField.style.marginBottom = '12px';
    const quantityLabel = document.createElement('label');
    quantityLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    quantityLabel.textContent = 'Quantity';
    quantityField.appendChild(quantityLabel);
    const quantityInput = document.createElement('input');
    quantityInput.type = 'number';
    quantityInput.className = 'guided-output-quantity';
    quantityInput.placeholder = '0';
    quantityInput.step = '0.01';
    quantityInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
    quantityField.appendChild(quantityInput);
    contentArea.appendChild(quantityField);
    
    // Unit dropdown
    const unitField = document.createElement('div');
    unitField.style.marginBottom = '12px';
    const unitLabel = document.createElement('label');
    unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    unitLabel.textContent = 'Unit';
    unitField.appendChild(unitLabel);
    const unitSelect = document.createElement('select');
    unitSelect.className = 'guided-output-unit form-select';
    unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
      const option = document.createElement('option');
      option.value = unit;
      option.textContent = unit;
      unitSelect.appendChild(option);
    });
    unitField.appendChild(unitSelect);
    contentArea.appendChild(unitField);
    
    outputContainer.appendChild(contentArea);
    document.getElementById('guided-outputs-list').appendChild(outputContainer);
    
    // Update button text after adding output
    updateOutputButtonText();
  };
  
  // Update output button text based on number of outputs
  function updateOutputButtonText() {
    const outputCount = document.querySelectorAll('#guided-outputs-list > div').length;
    const outputBtn = document.getElementById('add-output-btn');
    
    if (outputBtn) {
      outputBtn.textContent = outputCount > 0 
        ? '+ Add another output' 
        : '+ Add output';
    }
  }
  
  // Remove guided output
  window.removeGuidedOutput = function(outputId) {
    const outputElement = document.getElementById(outputId);
    if (outputElement) {
      outputElement.remove();
      
      // Update button text after removing output
      updateOutputButtonText();
    }
  };
  
  // Add guided execution prompt
  window.addGuidedPrompt = function() {
    // Collapse all existing prompts before adding a new one
    collapseAllPrompts();
    
    const promptId = `guided-prompt-${Date.now()}`;
    const promptContainer = document.createElement('div');
    promptContainer.id = promptId;
    promptContainer.dataset.expanded = 'true'; // New prompt starts expanded
    promptContainer.style.cssText = 'background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); margin-bottom: 12px; overflow: hidden;';
    
    // Create header with expand/collapse
    const header = document.createElement('div');
    header.style.cssText = 'display: flex; justify-content: space-between; align-items: center; padding: 12px; cursor: pointer; background: var(--bg-secondary, #f9fafb);';
    header.onclick = () => togglePromptExpand(promptId);
    
    const headerLeft = document.createElement('div');
    headerLeft.style.cssText = 'display: flex; align-items: center; gap: 8px;';
    
    const expandIcon = document.createElement('svg');
    expandIcon.className = 'guided-prompt-expand-icon';
    expandIcon.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    expandIcon.setAttribute('width', '16');
    expandIcon.setAttribute('height', '16');
    expandIcon.setAttribute('viewBox', '0 0 24 24');
    expandIcon.setAttribute('fill', 'none');
    expandIcon.setAttribute('stroke', 'currentColor');
    expandIcon.setAttribute('stroke-width', '2');
    expandIcon.setAttribute('stroke-linecap', 'round');
    expandIcon.setAttribute('stroke-linejoin', 'round');
    expandIcon.style.cssText = 'transition: transform 0.2s; transform: rotate(180deg);';
    expandIcon.innerHTML = '<polyline points="6 9 12 15 18 9"></polyline>';
    headerLeft.appendChild(expandIcon);
    
    const titleSpan = document.createElement('span');
    titleSpan.className = 'guided-prompt-title';
    titleSpan.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary);';
    titleSpan.textContent = 'Execution Prompt';
    headerLeft.appendChild(titleSpan);
    
    // Add label display that will show when collapsed
    const labelDisplay = document.createElement('span');
    labelDisplay.className = 'guided-prompt-label-display';
    labelDisplay.style.cssText = 'font-size: 14px; font-weight: 500; color: var(--text-primary); display: none;';
    labelDisplay.textContent = '';
    headerLeft.appendChild(labelDisplay);
    
    // Add expand/collapse hint text
    const expandHint = document.createElement('span');
    expandHint.className = 'guided-prompt-expand-hint';
    expandHint.style.cssText = 'font-size: 11px; color: var(--text-tertiary, #9ca3af); margin-left: 8px; font-style: italic;';
    expandHint.textContent = '(click to collapse)';
    headerLeft.appendChild(expandHint);
    
    header.appendChild(headerLeft);
    
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.onclick = (e) => {
      e.stopPropagation();
      window.removeGuidedPrompt(promptId);
    };
    removeButton.style.cssText = 'padding: 4px 8px; border: none; background: transparent; color: var(--error, #ef4444); cursor: pointer; font-size: 12px;';
    removeButton.textContent = 'Remove';
    header.appendChild(removeButton);
    
    promptContainer.appendChild(header);
    
    // Create content area
    const contentArea = document.createElement('div');
    contentArea.className = 'guided-prompt-content';
    contentArea.style.cssText = 'padding: 12px; display: block;';
    
    // Function to update label display
    const updateLabelDisplay = () => {
      const labelInput = promptContainer.querySelector('.guided-prompt-label');
      const label = labelInput ? labelInput.value.trim() : '';
      
      if (label) {
        labelDisplay.textContent = label;
        labelDisplay.style.display = 'inline';
        titleSpan.style.display = 'none';
      } else {
        labelDisplay.style.display = 'none';
        titleSpan.style.display = 'inline';
      }
    };
    
    // Label field
    const labelField = document.createElement('div');
    labelField.style.marginBottom = '12px';
    const labelLabel = document.createElement('label');
    labelLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    labelLabel.textContent = 'Label';
    labelField.appendChild(labelLabel);
    const labelInput = document.createElement('input');
    labelInput.type = 'text';
    labelInput.className = 'guided-prompt-label';
    labelInput.placeholder = 'e.g., Batch number, Temperature';
    labelInput.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); font-size: 13px;';
    labelInput.addEventListener('input', updateLabelDisplay);
    labelInput.addEventListener('blur', updateLabelDisplay);
    labelField.appendChild(labelInput);
    contentArea.appendChild(labelField);
    
    // Type field
    const typeField = document.createElement('div');
    typeField.style.marginBottom = '12px';
    const typeLabel = document.createElement('label');
    typeLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    typeLabel.textContent = 'Type';
    typeField.appendChild(typeLabel);
    const typeSelect = document.createElement('select');
    typeSelect.className = 'guided-prompt-type form-select';
    typeSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    const textOption = document.createElement('option');
    textOption.value = 'text';
    textOption.textContent = 'Text';
    typeSelect.appendChild(textOption);
    const numberOption = document.createElement('option');
    numberOption.value = 'number';
    numberOption.textContent = 'Number';
    typeSelect.appendChild(numberOption);
    const dateOption = document.createElement('option');
    dateOption.value = 'date';
    dateOption.textContent = 'Date';
    typeSelect.appendChild(dateOption);
    const selectOption = document.createElement('option');
    selectOption.value = 'select';
    selectOption.textContent = 'Select';
    typeSelect.appendChild(selectOption);
    typeField.appendChild(typeSelect);
    contentArea.appendChild(typeField);
    
    // Unit field (optional)
    const unitField = document.createElement('div');
    unitField.style.marginBottom = '12px';
    const unitLabel = document.createElement('label');
    unitLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    unitLabel.textContent = 'Unit (optional)';
    unitField.appendChild(unitLabel);
    const unitSelect = document.createElement('select');
    unitSelect.className = 'guided-prompt-unit form-select';
    unitSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px;';
    // Add empty option for "no unit"
    const emptyUnitOption = document.createElement('option');
    emptyUnitOption.value = '';
    emptyUnitOption.textContent = 'No unit';
    unitSelect.appendChild(emptyUnitOption);
    // Add unit options from unitGroups (same as inputs/outputs)
    [...unitGroups.weight, ...unitGroups.volume, ...unitGroups.count].forEach(unit => {
      const option = document.createElement('option');
      option.value = unit;
      option.textContent = unit;
      unitSelect.appendChild(option);
    });
    unitField.appendChild(unitSelect);
    contentArea.appendChild(unitField);
    
    // Required field
    const requiredField = document.createElement('div');
    const requiredLabel = document.createElement('label');
    requiredLabel.style.cssText = 'display: block; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px;';
    requiredLabel.textContent = 'Required';
    requiredField.appendChild(requiredLabel);
    const requiredSelect = document.createElement('select');
    requiredSelect.className = 'guided-prompt-required form-select';
    requiredSelect.style.cssText = 'width: 100%; padding: 8px 12px; border-radius: var(--radius-md); border: 1px solid var(--border-default); background: var(--bg-card); font-size: 13px; margin-bottom: 4px;';
    const requiredOption = document.createElement('option');
    requiredOption.value = 'true';
    requiredOption.textContent = 'Required';
    requiredSelect.appendChild(requiredOption);
    const optionalOption = document.createElement('option');
    optionalOption.value = 'false';
    optionalOption.textContent = 'Optional';
    requiredSelect.appendChild(optionalOption);
    requiredField.appendChild(requiredSelect);
    // Add explanation text
    const requiredExplanation = document.createElement('p');
    requiredExplanation.style.cssText = 'font-size: 11px; color: var(--text-tertiary, #9ca3af); margin: 0; line-height: 1.4;';
    requiredExplanation.textContent = 'Required: This field must be filled to complete the execution. Recommended for batch numbers and traceability data. Optional: This field can be skipped during execution.';
    requiredField.appendChild(requiredExplanation);
    contentArea.appendChild(requiredField);
    
    promptContainer.appendChild(contentArea);
    document.getElementById('guided-prompts-list').appendChild(promptContainer);
  };
  
  // Collapse all prompts except the specified one
  function collapseAllPrompts(exceptId = null) {
    const allPrompts = document.querySelectorAll('#guided-prompts-list > div');
    allPrompts.forEach(promptEl => {
      if (promptEl.id !== exceptId) {
        const contentArea = promptEl.querySelector('.guided-prompt-content');
        const expandIcon = promptEl.querySelector('.guided-prompt-expand-icon');
        const expandHint = promptEl.querySelector('.guided-prompt-expand-hint');
        if (contentArea && expandIcon) {
          contentArea.style.display = 'none';
          expandIcon.style.transform = 'rotate(0deg)';
          promptEl.dataset.expanded = 'false';
          if (expandHint) expandHint.textContent = '(click to expand)';
        }
      }
    });
  }
  
  // Toggle prompt expand/collapse
  function togglePromptExpand(promptId) {
    const promptEl = document.getElementById(promptId);
    if (!promptEl) return;
    
    const contentArea = promptEl.querySelector('.guided-prompt-content');
    const expandIcon = promptEl.querySelector('.guided-prompt-expand-icon');
    const expandHint = promptEl.querySelector('.guided-prompt-expand-hint');
    if (!contentArea || !expandIcon) return;
    
    const isExpanded = promptEl.dataset.expanded === 'true';
    if (isExpanded) {
      contentArea.style.display = 'none';
      expandIcon.style.transform = 'rotate(0deg)';
      promptEl.dataset.expanded = 'false';
      if (expandHint) expandHint.textContent = '(click to expand)';
    } else {
      contentArea.style.display = 'block';
      expandIcon.style.transform = 'rotate(180deg)';
      promptEl.dataset.expanded = 'true';
      if (expandHint) expandHint.textContent = '(click to collapse)';
      // Collapse all other prompts
      collapseAllPrompts(promptId);
    }
  }
  
  // Remove guided prompt
  window.removeGuidedPrompt = function(promptId) {
    const promptElement = document.getElementById(promptId);
    if (promptElement) {
      promptElement.remove();
    }
  };
  
  // Create step from guided flow
  window.createProcessFromGuidedFlow = async function() {
    const stepName = document.getElementById('guided-step-name').value.trim();
    const stepDescription = document.getElementById('guided-step-description').value.trim();
    
    if (!stepName) {
      alert('Please enter a step name');
      return;
    }
    
    // Collect inputs
    const inputs = [];
    const inputElements = document.querySelectorAll('#guided-inputs-list > div');
    inputElements.forEach(inputEl => {
      // Get name - could be from searchable dropdown (input) or regular input
      const nameInput = inputEl.querySelector('.guided-input-name');
      let name = '';
      if (nameInput) {
        // Check if it's a searchable dropdown input or regular input
        if (nameInput.classList.contains('searchable-dropdown-input')) {
          name = nameInput.value.trim();
        } else {
          name = nameInput.value.trim();
        }
      }
      
      // Get quantity
      const quantityInput = inputEl.querySelector('.guided-input-quantity');
      const quantity = quantityInput ? (quantityInput.value || '').trim() : '';
      
      // Get unit from dropdown
      const unitSelect = inputEl.querySelector('.guided-input-unit');
      const unit = unitSelect ? unitSelect.value : '';
      
      // Get execution type (may not exist for previous_output type)
      const executionTypeSelect = inputEl.querySelector('.guided-input-execution-type');
      // Check if this is a previous output input (no execution type select means it's previous_output)
      const isPreviousOutput = !executionTypeSelect;
      const executionType = executionTypeSelect ? executionTypeSelect.value : 'variable'; // Default to variable for previous outputs
      
      if (name && unit) {
        // Map execution type to the existing structure
        // variable = Select inventory at execution (requires_inventory_selection: true, is_variable: true)
        // static = Use exact input (is_variable: false, requires_inventory_selection: false)
        // prompt = Prompt at execution (is_variable: true, requires_inventory_selection: false)
        // Previous outputs are always treated as variable (requires inventory selection at execution)
        const isVariable = isPreviousOutput ? true : (executionType === 'variable' || executionType === 'prompt');
        const requiresInventorySelection = isPreviousOutput ? true : (executionType === 'variable');
        
        inputs.push({
          name: name,
          quantity: quantity ? parseFloat(quantity) : null,
          unit: unit,
          is_variable: isVariable,
          requires_inventory_selection: requiresInventorySelection
        });
      }
    });
    
    // Collect outputs
    const outputs = [];
    const outputElements = document.querySelectorAll('#guided-outputs-list > div');
    outputElements.forEach(outputEl => {
      const name = outputEl.querySelector('.guided-output-name')?.value.trim();
      const unitSelect = outputEl.querySelector('.guided-output-unit');
      const unit = unitSelect ? unitSelect.value : '';
      const quantityInput = outputEl.querySelector('.guided-output-quantity');
      const quantity = quantityInput ? (quantityInput.value || '').trim() : '';
      
      if (name && unit) {
        // Outputs are automatically added to inventory (can be used in subsequent steps)
        outputs.push({
          name: name,
          unit: unit,
          quantity: quantity ? parseFloat(quantity) : null,
          is_variable: true, // Outputs are always variable (can be used in subsequent steps)
          requires_execution_confirmation: true
        });
      }
    });
    
    // Collect execution prompts
    const executionPrompts = [];
    const promptElements = document.querySelectorAll('#guided-prompts-list > div');
    promptElements.forEach(promptEl => {
      const label = promptEl.querySelector('.guided-prompt-label')?.value.trim();
      const typeSelect = promptEl.querySelector('.guided-prompt-type');
      const type = typeSelect ? typeSelect.value : 'text';
      const unitSelect = promptEl.querySelector('.guided-prompt-unit');
      const unit = unitSelect ? (unitSelect.value || '').trim() : null;
      const requiredSelect = promptEl.querySelector('.guided-prompt-required');
      const required = requiredSelect ? requiredSelect.value === 'true' : true;
      
      if (label) {
        executionPrompts.push({
          label: label,
          type: type,
          unit: unit || null,
          required: required
        });
      }
    });
    
    // Get process ID from URL params (same way as flows2.html)
    const urlParams = new URLSearchParams(window.location.search);
    const processId = urlParams.get('id') || null;
    
    if (!processId) {
      alert('Process ID is missing. Please ensure you are on a process page.');
      return;
    }
    
    // Calculate step number - use the maximum step_number from createdSteps or database steps + 1
    let stepCount = 1;
    
    // First, check createdSteps (steps created in this session)
    if (createdSteps.length > 0) {
      const maxStepNumber = Math.max(...createdSteps.map(s => s.step_number || 0));
      stepCount = maxStepNumber + 1;
    }
    
    // Also check database steps to ensure we don't miss any
    try {
      const processData = await CoreAPI.getProcess(processId);
      if (processData && processData.steps && processData.steps.length > 0) {
        const maxDbStepNumber = Math.max(...processData.steps.map(s => s.step_number || 0));
        // Use the higher of the two (createdSteps max or database max)
        stepCount = Math.max(stepCount, maxDbStepNumber + 1);
      }
    } catch (err) {
      console.warn('Could not fetch process data to determine step count, using createdSteps:', err);
    }
    
    console.log('Calculated stepCount:', stepCount, 'from createdSteps:', createdSteps.length);
    
    try {
      // Create or update the step via API - same structure as existing saveStep function
      const stepData = {
        step_number: stepCount,
        name: stepName,
        description: stepDescription,
        inputs: inputs || [],
        outputs: outputs || [],
        execution_prompts: executionPrompts || []
      };
      
      let saved;
      // If we're editing an existing step (resuming draft), update it instead of creating new
      if (editingStepId) {
        saved = await CoreAPI.updateStep(processId, editingStepId, stepData);
        // Clear editingStepId after update
        editingStepId = null;
      } else {
        saved = await CoreAPI.createStep(processId, stepData);
      }
      
      if (saved && saved.id) {
        // Use the step_number from the saved step (backend might have adjusted it)
        const savedStepNumber = saved.step_number || stepCount;
        
        // Store the created step
        const stepSummary = {
          id: saved.id,
          step_number: savedStepNumber, // Use step_number from saved step
          name: stepName,
          description: stepDescription,
          inputs: inputs || [],
          outputs: outputs || [],
          execution_prompts: executionPrompts || []
        };
        
        console.log('Created step with step_number:', savedStepNumber, 'step name:', stepName);
        
        // If we were editing, the step was already in createdSteps (from loadDraft), so update it
        // Otherwise, add the newly created step
        if (editingStepId && saved.id === editingStepId) {
          // Update existing step in createdSteps
          const stepIndex = createdSteps.findIndex(s => s.id === editingStepId);
          if (stepIndex !== -1) {
            createdSteps[stepIndex] = stepSummary;
            console.log('Updated step in createdSteps at index', stepIndex);
          } else {
            createdSteps.push(stepSummary);
            console.log('Added step to createdSteps (not found in array)');
          }
        } else {
          createdSteps.push(stepSummary);
          console.log('Added new step to createdSteps. Total steps:', createdSteps.length);
        }
        
        // Update process to not be draft if it was (user is actively creating steps)
        await CoreAPI.updateProcess(processId, { is_draft: false });
        
        // Show step summaries
        if (createdSteps.length > 0) {
          updateStepSummaries();
        }
        
        // Update input buttons to show/hide previous output button
        updateInputButtonsText();
        
        // Hide all step forms and show post-creation options
        document.querySelectorAll('.create-process-step').forEach(step => {
          step.style.display = 'none';
        });
        const postCreationOptions = document.getElementById('post-creation-options');
        if (postCreationOptions) {
          postCreationOptions.style.display = 'block';
        }
        
        // Show success notification
        if (window.showNotification) {
          window.showNotification(
            'success',
            'Step Created',
            `Step "${stepName}" has been created successfully.`
          );
        }
      }
    } catch (error) {
      console.error('Failed to create step:', error);
      const errorMessage = error.message || 'Unknown error';
      
      // Show error notification
      if (window.showNotification) {
        window.showNotification(
          'error',
          'Failed to Create Step',
          `Failed to create step: ${errorMessage}`
        );
      } else {
        alert('Failed to create step: ' + errorMessage);
      }
    }
  };
  
  // Update step summaries display with expand/collapse
  function updateStepSummaries() {
    const summariesList = document.getElementById('step-summaries-list');
    const summariesContainer = document.getElementById('step-summaries-container');
    if (!summariesList || !summariesContainer) return;
    
    if (createdSteps.length === 0) {
      summariesContainer.style.display = 'none';
      return;
    }
    
    summariesContainer.style.display = 'block';
    summariesList.innerHTML = '';
    
    createdSteps.forEach((step, index) => {
      const stepId = `step-summary-${step.id || index}`;
      const summaryCard = document.createElement('div');
      summaryCard.id = stepId;
      summaryCard.dataset.expanded = 'false';
      summaryCard.style.cssText = 'background: var(--bg-card, #ffffff); border: 1px solid var(--border-default, #e5e7eb); border-radius: var(--radius-md); padding: 16px; overflow: hidden;';
      
      // Header (clickable to expand/collapse)
      const stepHeader = document.createElement('div');
      stepHeader.style.cssText = 'display: flex; align-items: center; gap: 12px; cursor: pointer;';
      stepHeader.onclick = () => toggleStepSummary(stepId);
      
      const expandIcon = document.createElement('svg');
      expandIcon.className = 'step-summary-expand-icon';
      expandIcon.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
      expandIcon.setAttribute('width', '16');
      expandIcon.setAttribute('height', '16');
      expandIcon.setAttribute('viewBox', '0 0 24 24');
      expandIcon.setAttribute('fill', 'none');
      expandIcon.setAttribute('stroke', 'currentColor');
      expandIcon.setAttribute('stroke-width', '2');
      expandIcon.setAttribute('stroke-linecap', 'round');
      expandIcon.setAttribute('stroke-linejoin', 'round');
      expandIcon.style.cssText = 'transition: transform 0.2s; transform: rotate(0deg); color: var(--text-tertiary, #9ca3af); flex-shrink: 0;';
      expandIcon.innerHTML = '<polyline points="6 9 12 15 18 9"></polyline>';
      stepHeader.appendChild(expandIcon);
      
      const stepNumber = document.createElement('div');
      stepNumber.style.cssText = 'width: 32px; height: 32px; border-radius: 50%; background: var(--primary, #3b82f6); color: white; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 14px; flex-shrink: 0;';
      stepNumber.textContent = step.step_number || (index + 1);
      stepHeader.appendChild(stepNumber);
      
      const stepInfo = document.createElement('div');
      stepInfo.style.cssText = 'flex: 1;';
      
      const stepName = document.createElement('h4');
      stepName.style.cssText = 'font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0;';
      stepName.textContent = step.name;
      stepInfo.appendChild(stepName);
      
      if (step.description) {
        const stepDesc = document.createElement('p');
        stepDesc.style.cssText = 'font-size: 13px; color: var(--text-secondary); margin: 0;';
        stepDesc.textContent = step.description;
        stepInfo.appendChild(stepDesc);
      }
      
      stepHeader.appendChild(stepInfo);
      summaryCard.appendChild(stepHeader);
      
      // Collapsed summary (always visible)
      const collapsedSummary = document.createElement('div');
      collapsedSummary.className = 'step-summary-collapsed';
      collapsedSummary.style.cssText = 'margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-light, #e5e7eb); font-size: 12px; color: var(--text-secondary);';
      
      const details = [];
      if (step.inputs && step.inputs.length > 0) {
        details.push(`${step.inputs.length} input${step.inputs.length > 1 ? 's' : ''}`);
      }
      if (step.outputs && step.outputs.length > 0) {
        details.push(`${step.outputs.length} output${step.outputs.length > 1 ? 's' : ''}`);
      }
      if (step.execution_prompts && step.execution_prompts.length > 0) {
        details.push(`${step.execution_prompts.length} execution prompt${step.execution_prompts.length > 1 ? 's' : ''}`);
      }
      
      if (details.length > 0) {
        collapsedSummary.textContent = details.join(' • ');
        summaryCard.appendChild(collapsedSummary);
      }
      
      // Expanded details (hidden by default)
      const expandedDetails = document.createElement('div');
      expandedDetails.className = 'step-summary-expanded';
      expandedDetails.style.cssText = 'margin-top: 16px; padding-top: 16px; border-top: 2px solid var(--border-default, #e5e7eb); display: none;';
      
      // Inputs
      if (step.inputs && step.inputs.length > 0) {
        const inputsSection = document.createElement('div');
        inputsSection.style.cssText = 'margin-bottom: 16px;';
        const inputsTitle = document.createElement('h5');
        inputsTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
        inputsTitle.textContent = 'Inputs:';
        inputsSection.appendChild(inputsTitle);
        
        step.inputs.forEach(input => {
          const inputItem = document.createElement('div');
          inputItem.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
          const quantity = input.quantity !== null && input.quantity !== undefined ? input.quantity : '';
          const unit = input.unit || '';
          inputItem.textContent = `• ${input.name}${quantity ? ` (${quantity} ${unit})` : unit ? ` (${unit})` : ''}`;
          inputsSection.appendChild(inputItem);
        });
        expandedDetails.appendChild(inputsSection);
      }
      
      // Outputs
      if (step.outputs && step.outputs.length > 0) {
        const outputsSection = document.createElement('div');
        outputsSection.style.cssText = 'margin-bottom: 16px;';
        const outputsTitle = document.createElement('h5');
        outputsTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
        outputsTitle.textContent = 'Outputs:';
        outputsSection.appendChild(outputsTitle);
        
        step.outputs.forEach(output => {
          const outputItem = document.createElement('div');
          outputItem.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
          const quantity = output.quantity !== null && output.quantity !== undefined ? output.quantity : '';
          const unit = output.unit || '';
          outputItem.textContent = `• ${output.name}${quantity ? ` (${quantity} ${unit})` : unit ? ` (${unit})` : ''}`;
          outputsSection.appendChild(outputItem);
        });
        expandedDetails.appendChild(outputsSection);
      }
      
      // Execution Prompts
      if (step.execution_prompts && step.execution_prompts.length > 0) {
        const promptsSection = document.createElement('div');
        const promptsTitle = document.createElement('h5');
        promptsTitle.style.cssText = 'font-size: 13px; font-weight: 600; color: var(--text-primary); margin: 0 0 8px 0;';
        promptsTitle.textContent = 'Execution Prompts:';
        promptsSection.appendChild(promptsTitle);
        
        step.execution_prompts.forEach(prompt => {
          const promptItem = document.createElement('div');
          promptItem.style.cssText = 'padding: 8px; background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-sm); margin-bottom: 4px; font-size: 12px; color: var(--text-secondary);';
          const unit = prompt.unit ? ` (${prompt.unit})` : '';
          const required = prompt.required !== false ? 'Required' : 'Optional';
          promptItem.textContent = `• ${prompt.label} - ${prompt.type}${unit} - ${required}`;
          promptsSection.appendChild(promptItem);
        });
        expandedDetails.appendChild(promptsSection);
      }
      
      summaryCard.appendChild(expandedDetails);
      summariesList.appendChild(summaryCard);
    });
  }
  
  // Toggle step summary expand/collapse
  function toggleStepSummary(stepId) {
    const summaryCard = document.getElementById(stepId);
    if (!summaryCard) return;
    
    const expandedDetails = summaryCard.querySelector('.step-summary-expanded');
    const collapsedSummary = summaryCard.querySelector('.step-summary-collapsed');
    const expandIcon = summaryCard.querySelector('.step-summary-expand-icon');
    
    if (!expandedDetails || !expandIcon) return;
    
    const isExpanded = summaryCard.dataset.expanded === 'true';
    if (isExpanded) {
      expandedDetails.style.display = 'none';
      if (collapsedSummary) collapsedSummary.style.display = 'block';
      expandIcon.style.transform = 'rotate(0deg)';
      summaryCard.dataset.expanded = 'false';
    } else {
      expandedDetails.style.display = 'block';
      if (collapsedSummary) collapsedSummary.style.display = 'none';
      expandIcon.style.transform = 'rotate(180deg)';
      summaryCard.dataset.expanded = 'true';
    }
  }
  
  // Add another step
  window.addAnotherStep = function() {
    // Hide post-creation options
    const postCreationOptions = document.getElementById('post-creation-options');
    if (postCreationOptions) {
      postCreationOptions.style.display = 'none';
    }
    
    // Show step summaries
    if (createdSteps.length > 0) {
      updateStepSummaries();
    }
    
    // Reset form but keep created steps
    resetForm(true);
    
    // Update button visibility (previous output button should now be visible)
    updateInputButtonsText();
    
    // Show step 1 again
    currentStep = 1;
    updateStepDisplay();
  };
  
  // Finish process
  window.finishProcess = function() {
    // Show confirmation modal
    const confirmationModal = document.getElementById('finish-process-confirmation-modal');
    if (confirmationModal) {
      confirmationModal.style.display = 'flex';
    }
  };
  
  // Confirm finish process
  window.confirmFinishProcess = async function() {
    // Close confirmation modal
    const confirmationModal = document.getElementById('finish-process-confirmation-modal');
    if (confirmationModal) {
      confirmationModal.style.display = 'none';
    }
    
    // Get process ID and mark as not draft
    const urlParams = new URLSearchParams(window.location.search);
    const processId = urlParams.get('id');
    if (processId) {
      try {
        await CoreAPI.updateProcess(processId, { is_draft: false });
      } catch (error) {
        console.error('Error updating process draft status:', error);
      }
    }
    
    // Close main modal
    closeModal();
    
    // Reload process data to update step count and display
    if (window.loadProcessData) {
      await window.loadProcessData();
    } else if (window.loadSteps) {
      await window.loadSteps();
    }
    
    // Show success notification
    if (window.showNotification) {
      window.showNotification(
        'success',
        'Process Created',
        `Process has been created successfully with ${createdSteps.length} step${createdSteps.length > 1 ? 's' : ''}.`
      );
    }
    
    // Reset everything
    resetForm(false);
  };
  
  // Close modal on overlay click or close button — show "Save as draft or discard?" first
  // Use data-create-step-close so the global [data-modal-close] handler (e.g. on flows2) does not run and close the modal before our prompt appears
  document.addEventListener('DOMContentLoaded', function() {
    const modal = document.getElementById('create-process-modal');
    if (modal) {
      const closeButtons = modal.querySelectorAll('[data-create-step-close]');
      closeButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
          e.preventDefault();
          e.stopPropagation();
          requestCloseCreateProcessModal();
        });
      });
    }
    
    // Save as draft or discard confirmation modal buttons
    const saveDraftSaveBtn = document.getElementById('save-draft-save-btn');
    const saveDraftDiscardBtn = document.getElementById('save-draft-discard-btn');
    const saveDraftContinueBtn = document.getElementById('save-draft-continue-btn');
    if (saveDraftSaveBtn) {
      saveDraftSaveBtn.addEventListener('click', function() {
        hideSaveDraftOrDiscardModal();
        window.saveDraft();
      });
    }
    if (saveDraftDiscardBtn) {
      saveDraftDiscardBtn.addEventListener('click', function() {
        hideSaveDraftOrDiscardModal();
        resetForm(false);
        closeModal();
      });
    }
    if (saveDraftContinueBtn) {
      saveDraftContinueBtn.addEventListener('click', function() {
        hideSaveDraftOrDiscardModal();
        // Keep create-process-modal open; user continues creating steps
      });
    }
  });
})();
